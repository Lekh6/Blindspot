"""
BlindSpot CLI — one-command testing on one or more repos (user-friendly).

Pipeline: Parse -> Discovery -> Filtering -> Judge -> Model -> Graph -> Report

What enters CLI: one or more repo dirs (each must contain docker-compose.yml or explicit --compose file).
What leaves CLI: per repo out/<name>/report.json + report.md + graph.json + summary to stdout.
Why user-friendly: no code edits, just `pip install -r requirements.txt`, fill `.env`, run one command.

Provider-agnostic: --provider auto (default) picks OpenRouter if OPENROUTER_API_KEY present else Gemini.
Thinking low/medium dynamically via --thinking. Model hidden from report/graph.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv  # type: ignore[import-untyped]

from .discovery import discover_candidates
from .filtering import build_evidence_packages
from .graph import build_graph
from .model import DependencyModel
from .parser import parse_compose_file
from .report import build_report


def find_compose(repo: Path, compose_arg: Optional[str]) -> Optional[Path]:
    if compose_arg:
        p = Path(compose_arg)
        # If compose_arg is relative to repo
        if not p.is_absolute():
            cand = repo / p
            if cand.exists():
                return cand
            if p.exists():
                return p
        return p if p.exists() else None
    # Search common locations inside repo
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        cand = repo / name
        if cand.exists():
            return cand
        # also search one level down (services/<name>/docker-compose.yml) — common for OSS repos
        for sub in repo.rglob(name):
            # Prefer shallowest
            if sub.exists():
                return sub
    return None


def run_one_repo(
    repo_path: Path,
    compose_path: Optional[Path],
    out_root: Path,
    provider: str,
    thinking: str,
    cache_path: Optional[Path],
    meaningful_only: bool,
) -> dict:
    """Run full pipeline on one repo. Returns summary dict for printing."""
    repo_path = repo_path.resolve()
    repo_name = repo_path.name
    # Out dir: out/<repo_name> or out_root/<repo_name> if out_root is dir
    out_dir = (out_root / repo_name) if out_root.is_dir() or not out_root.suffix else out_root.parent
    if len(sys.argv) > 2 and out_root == Path("out"):
        out_dir = out_root / repo_name
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {"repo": str(repo_path), "out_dir": str(out_dir), "error": None}

    compose_file = find_compose(repo_path, str(compose_path) if compose_path else None)
    if compose_file is None or not compose_file.exists():
        result["error"] = f"docker-compose.yml not found in {repo_path} (tried {compose_path or 'auto'})"
        # Still write empty report
        from .model import DependencyModel as DM

        model = DM([])
        graph = build_graph(model, meaningful_only=True)
        report = build_report(model, graph_data=graph, meaningful_only=meaningful_only)
        (out_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
        (out_dir / "report.md").write_text(report.to_markdown(), encoding="utf-8")
        (out_dir / "graph.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
        result.update({"candidates": 0, "packages": 0, "dependencies": 0, "meaningful": 0, "nodes": 0, "edges": 0})
        return result

    # Stage 1-3 deterministic
    project = parse_compose_file(str(compose_file))
    candidates = discover_candidates(project)
    packages = build_evidence_packages(candidates, project)

    # Stage 4 Judge — provider-agnostic, thinking low/medium
    load_dotenv(".env")
    import os

    if provider == "auto":
        # Prefer OpenRouter if key present, else Gemini
        if os.getenv("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            provider = "gemini"
        else:
            provider = "openrouter"  # will failsafe to uncertain 0.5 internally

    if provider == "gemini":
        from .judge import GeminiJudgeClient

        client = GeminiJudgeClient(thinking_level=thinking)  # type: ignore[arg-type]
    else:
        from .judge import OpenRouterJudgeClient

        client = OpenRouterJudgeClient(thinking_level=thinking)  # type: ignore[arg-type]

    # Stage 4: judge (0+1 per package, cached)
    c_path = str(cache_path) if cache_path else None
    # Use per-repo cache file if not specified? Keep global cache.json for reuse
    from .judge import judge_evidence_packages

    pairs = judge_evidence_packages(packages, client, cache_path=c_path, use_cache=bool(c_path))

    # Stage 5 Model — service-to-resource, model hidden externally
    model = DependencyModel.from_judgments(pairs)

    # Stage 6 Graph — DATA, bipartite
    graph = build_graph(model, meaningful_only=meaningful_only)

    # Stage 7 Report — human-readable, model hidden
    report = build_report(model, graph_data=graph, meaningful_only=meaningful_only)

    # Write out files (model hidden)
    (out_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "report.md").write_text(report.to_markdown(), encoding="utf-8")
    (out_dir / "graph.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    # Also write log with model (internal) — out/<name>/log.json
    (out_dir / "report.log.json").write_text(
        json.dumps(
            {
                "model": "report_log",
                "provider": provider,
                "thinking": thinking,
                "dependencies_log": model.to_log_list(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result.update(
        {
            "compose": str(compose_file),
            "candidates": len(candidates),
            "packages": len(packages),
            "dependencies": len(model.dependencies),
            "meaningful": len(model.meaningful_only().dependencies),
            "reported": len(report.findings),
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "provider": provider,
            "thinking": thinking,
        }
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="blindspot",
        description="BlindSpot -- run full pipeline (Parse->Report) on one or more repos. One command, provider-agnostic.",
        epilog="Examples:  blindspot fixtures/shared_env  |  blindspot /path/to/repo1 /path/to/repo2 --out out --provider openrouter --thinking low",
    )
    p.add_argument(
        "repos",
        nargs="*",
        default=["fixtures/shared_env", "fixtures/shared_volume", "fixtures/near_miss"],
        help="Repo dirs to analyze (each must contain docker-compose.yml). Default: all three fixtures.",
    )
    p.add_argument("--compose", default=None, help="Explicit compose file (relative to repo or absolute). Default: auto-find docker-compose.yml")
    p.add_argument("--out", dest="out", default="out", help="Output root dir (default: out/<repo_name>/)")
    p.add_argument("--provider", choices=["auto", "openrouter", "gemini"], default="auto", help="LLM provider (default: auto picks OPENROUTER_API_KEY else GEMINI_API_KEY)")
    p.add_argument("--thinking", choices=["none", "low", "medium", "high"], default="low", help="Thinking effort low/medium (default: low for testing, cheap)")
    p.add_argument("--cache", default="cache.json", help="Cache file for LLM verdicts (default: cache.json, use 'none' to disable)")
    p.add_argument("--all", action="store_true", help="Include coincidental/uncertain in graph/report (default: meaningful_only)")
    p.add_argument("--list-fixtures", action="store_true", help="List bundled fixtures and exit")

    args = p.parse_args(argv)

    if args.list_fixtures:
        print("Bundled fixtures:")
        for f in ["fixtures/shared_env", "fixtures/shared_volume", "fixtures/near_miss"]:
            print(f"  {f}")
        return 0

    out_root = Path(args.out)
    cache_path = None if args.cache.lower() == "none" else Path(args.cache)
    meaningful_only = not args.all

    # Header (ASCII for Windows cp1252 safety)
    print("BlindSpot -- Tier 1 pipeline: Parse -> Discovery -> Filtering -> Judge -> Model -> Graph -> Report")
    print(f"Provider: {args.provider}  Thinking: {args.thinking}  Cache: {args.cache}  Out: {out_root}")
    print(f"Repos: {', '.join(args.repos)}")
    print("")

    summaries = []
    for repo_str in args.repos:
        repo = Path(repo_str)
        if not repo.exists():
            print(f"[error] repo not found: {repo}")
            continue
        # If repo_str is file, use its parent
        if repo.is_file():
            repo = repo.parent
        print(f"--- {repo} ---".encode('utf-8', errors='replace').decode('utf-8'))
        try:
            res = run_one_repo(repo, Path(args.compose) if args.compose else None, out_root, args.provider, args.thinking, cache_path, meaningful_only)
        except Exception as e:
            print(f"  [error] {e}")
            import traceback

            traceback.print_exc()
            continue
        if res.get("error"):
            print(f"  {res['error']}")
        print(f"  compose: {res.get('compose', 'not found')}")
        print(f"  candidates: {res.get('candidates',0)} -> packages: {res.get('packages',0)} -> dependencies: {res.get('dependencies',0)} (meaningful {res.get('meaningful',0)} reported {res.get('reported',0)})")
        print(f"  graph: {res.get('nodes',0)} nodes, {res.get('edges',0)} edges")
        print(f"  out: {res['out_dir']}/report.json + report.md + graph.json (model hidden, see log.json for provider)")
        print("")
        summaries.append(res)

    # Final table
    if len(summaries) > 1:
        print("Summary across repos:")
        print(f"{'repo':<30} {'cand':>6} {'pkgs':>6} {'deps':>6} {'mean':>6} {'nodes':>6} {'edges':>6}")
        for r in summaries:
            print(f"{Path(r['repo']).name:<30} {r.get('candidates',0):>6} {r.get('packages',0):>6} {r.get('dependencies',0):>6} {r.get('meaningful',0):>6} {r.get('nodes',0):>6} {r.get('edges',0):>6}")
        print("")
        print(f"All reports in {out_root}/<repo>/ -- open report.md in any markdown viewer. Graph JSON is React Flow ready.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
