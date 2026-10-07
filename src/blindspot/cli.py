"""
BlindSpot CLI — interactive menu (simple) + advanced flags.

Pipeline: Parse -> Discovery -> Filtering -> Judge -> Model -> Graph -> Report

Interactive mode (default when run with no args):
  User runs:  set PYTHONPATH=src && python -m blindspot.cli
  CLI asks for absolute application path (e.g. C:\\Users\\...\\MyApp) and AI thinking level.
  No flags needed.

Advanced mode (flags still supported for scripting/tests):
  python -m blindspot.cli "C:\\path\\to\\repo" --thinking low --provider auto
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv  # type: ignore[import-untyped]

from .aggregation import aggregate_evidence_packages
from .coupling import CouplingModel
from .discovery import discover_candidates
from .filtering import build_evidence_packages
from .graph import build_graph_from_groups
from .parser import parse_compose_file
from .report import build_grouped_report

VALID_THINKING = {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# API key handling — prompt every time no key is present
# ---------------------------------------------------------------------------

def _has_api_key() -> bool:
    import os
    return bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY"))


def _prompt_for_api_key() -> bool:
    """Prompt user for API key when none is present.

    Returns:
        True  -> deterministic-only mode (user said No or input unavailable)
        False -> key now available (user provided one, saved to .env + environ)
    Prompted every time no key is found — if user says No, we do NOT save
    anything, so next run will prompt again.
    """
    import os

    # Non-interactive (e.g. CI, piped) -> cannot prompt, go deterministic with warning
    if not sys.stdin.isatty():
        print("  [warning] No LLM API key found in .env and not in an interactive terminal.")
        print("            Running in deterministic-only mode — only JSONs will be produced,")
        print("            without AI reasoning. Output will be less accurate.")
        return True

    print("")
    print("  No LLM API key found in .env")
    print("  LLM analysis enables semantic judgment (meaningful vs coincidental).")
    print("  Without a key, BlindSpot runs deterministically — only structural")
    print("  JSONs (graph.json, report.json) are produced, without AI reasoning.")
    print("")

    # Ask Yes/No
    while True:
        try:
            ans = input("  Would you like to enter an API key? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Proceeding without API key.")
            print("  Deterministic-only mode — only JSONs, no AI reasoning.")
            return True

        if ans in ("", "y", "yes"):
            # Prompt for the actual key
            try:
                raw_key = input("  Paste your API key (OpenRouter sk-or-... or Gemini AIza...): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled — proceeding deterministically.")
                return True

            raw_key = raw_key.strip().strip('"').strip("'").strip()
            if not raw_key:
                print("  [error] Key cannot be empty. Try again or answer 'n' for deterministic mode.")
                continue

            # Detect provider from key format
            if raw_key.startswith("sk-or-"):
                env_name = "OPENROUTER_API_KEY"
                provider_hint = "OpenRouter"
            elif raw_key.startswith("AIza"):
                env_name = "GEMINI_API_KEY"
                provider_hint = "Gemini"
            else:
                print("  Could not detect provider from key format.")
                try:
                    prov = input("  Is this an [1] OpenRouter or [2] Gemini key? [1/2] (default: 1): ").strip()
                except (EOFError, KeyboardInterrupt):
                    prov = "1"
                if prov == "2":
                    env_name = "GEMINI_API_KEY"
                    provider_hint = "Gemini"
                else:
                    env_name = "OPENROUTER_API_KEY"
                    provider_hint = "OpenRouter"

            # Save to .env (preserve existing entries)
            env_path = Path(".env")
            existing: dict[str, str] = {}
            if env_path.exists():
                try:
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()
                except Exception:
                    pass
            existing[env_name] = raw_key
            try:
                with env_path.open("w", encoding="utf-8") as f:
                    for k, v in existing.items():
                        f.write(f"{k}={v}\n")
                print(f"  Saved {env_name} ({provider_hint}) to .env — will be used for LLM analysis.")
                # Also set in current process
                os.environ[env_name] = raw_key
            except Exception as e:
                print(f"  [warning] Could not save to .env: {e}")
                print("  Using key for this session only.")
                os.environ[env_name] = raw_key
            return False

        elif ans in ("n", "no"):
            print("")
            print("  Proceeding in deterministic-only mode.")
            print("  Only structural JSONs will be produced (graph.json, report.json) —")
            print("  AI reasoning (verdict/confidence/reason) will be skipped.")
            print("  Output will be less accurate and harder to interpret.")
            print("  You will be prompted again for an API key on the next run.")
            print("")
            return True
        else:
            print("  Please answer Y (yes) or n (no).")


def _deterministic_pairs(grouped):
    """Create deterministic-only CouplingModel pairs without LLM.

    Each group gets verdict=uncertain, confidence=0.0, reason indicating
    deterministic mode — graph/report still render but clearly mark
    that no semantic judgment was performed.
    """
    from .judge import JudgeResult
    pairs = []
    for g in grouped:
        jr = JudgeResult(
            verdict="uncertain",
            confidence=0.0,
            reason="Deterministic-only mode — no LLM analysis. Shared configuration detected via static analysis only; semantic judgment skipped.",
            model="deterministic-no-llm",
        )
        pairs.append((g, jr))
    return pairs


# ---------------------------------------------------------------------------
# Polished UI helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print("")
    print("=" * 56)
    print("  BlindSpot — Implicit Cross-Service Coupling Detector")
    print("=" * 56)
    print("  Finds hidden couplings via shared env vars & volumes")
    print("  in docker-compose.yml — deterministic + LLM judgment")
    print("-" * 56)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1].strip()
    return s


def _is_absolute_windows_path(p: Path) -> bool:
    """Must be absolute from a drive root, e.g. C:\\...  """
    # Path.is_absolute() covers C:\\ and / on Windows
    if not p.is_absolute():
        return False
    # Require a drive letter (C:) — enforce the "from root C drive" contract
    # On Windows p.drive is 'C:'; on non-Windows it may be '' so allow is_absolute only
    if p.drive:
        return len(p.drive) >= 2 and p.drive[1] == ":"
    # Non-Windows fallback: must be absolute
    return True


def _prompt_absolute_path() -> Path:
    """Prompt until a valid absolute directory path from C drive is given."""
    while True:
        try:
            raw = input("  Enter absolute application path (e.g. C:\\path\\to\\YourApp): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            raise SystemExit(0)

        raw = _strip_quotes(raw)

        if not raw:
            print("  [error] Path cannot be empty. Enter an absolute path from C:\\ drive.")
            continue

        p = Path(raw)

        if not _is_absolute_windows_path(p):
            print(f"  [error] Path must be absolute from C drive (e.g. C:\\Users\\...). Got: {raw!r}")
            print("          Hint: use full path starting with  C:\\  and keep quotes if it contains spaces.")
            continue

        if not p.exists():
            print(f"  [error] Path does not exist: {p}")
            continue

        if not p.is_dir():
            print(f"  [error] Path is not a directory: {p}")
            print("          Provide the application root folder that contains docker-compose.yml")
            continue

        # Warn if no compose file found, but still accept — let user confirm
        compose_found = find_compose(p, None)
        if compose_found is None:
            print(f"  [warning] No docker-compose.yml / compose.yml found in {p} (searched recursively).")
            try:
                ans = input("          Continue anyway? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.")
                raise SystemExit(0)
            if ans not in ("y", "yes"):
                continue

        return p


def _prompt_thinking() -> str:
    """Prompt until valid thinking level (low/medium/high) is given."""
    while True:
        try:
            raw = input("  Select AI thinking level [low / medium / high] (default: low): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            raise SystemExit(0)

        if not raw:
            return "low"
        raw = raw.strip().lower()
        # Allow common variations, map strictly
        if raw in VALID_THINKING:
            return raw
        # Also accept "none" with guidance but map to low per spec user said low/medium/high only
        if raw == "none":
            print("  [error] 'none' is no longer supported. Choose: low, medium, or high.")
            continue
        print(f"  [error] Invalid thinking level {raw!r}. Allowed: low, medium, high.")
        print("          low = fast/cheap, medium = balanced, high = thorough.")


def _run_interactive() -> int:
    _print_banner()
    print("  Interactive setup — answer 2 questions to run analysis.\n")

    repo_path = _prompt_absolute_path()
    thinking = _prompt_thinking()

    print("")
    print("-" * 56)
    print(f"  Application : {repo_path}")
    print(f"  Thinking    : {thinking}")
    print(f"  Output      : out/{repo_path.name}/")
    print("-" * 56)
    print("  Running BlindSpot pipeline...")
    print("")

    # Use defaults: provider auto, out=out, cache=cache.json, meaningful_only=True
    out_root = Path("out")
    cache_path: Optional[Path] = Path("cache.json")
    try:
        result = run_one_repo(repo_path, None, out_root, "auto", thinking, cache_path, True)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n  [error] Pipeline failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if result.get("error"):
        print(f"\n  [error] {result['error']}")
        print(f"  Output written to: {result['out_dir']}")
        return 0

    print("")
    print("  " + "=" * 44)
    if result.get("deterministic_only"):
        print("  Analysis complete — deterministic-only mode")
    else:
        print("  Analysis complete")
    print("  " + "=" * 44)
    # New accounting (prompt §10) — separate services from candidates, same as report.json
    acc = result.get("accounting", {})
    # Fallback to result top-level if accounting not present (backward compat)
    if acc:
        src_used = acc.get("sources", {}).get("used", result.get("sources_used", []))
        parsed = acc.get("parsed", {})
        disc = acc.get("discovery", {})
        agg = acc.get("aggregation", {})
        judg = acc.get("judgment", {})
        graph_a = acc.get("graph", {})
        print("")
        print("  Input")
        print(f"    Compose sources used : {len(src_used)}" + (f" ({', '.join(src_used)})" if src_used else " (none)"))
        print("")
        print("  Parsed")
        print(f"    Services             : {parsed.get('services', result.get('services_analyzed', 0))}")
        print(f"    Named volumes        : {parsed.get('named_volumes', result.get('named_volumes', 0))}")
        print("")
        print("  Analysis")
        print(f"    Candidates generated : {disc.get('raw_candidates', result.get('raw_candidates', result.get('candidates', 0)))}")
        print(f"    Observations         : {disc.get('observations', result.get('observations', 0))}")
        print(f"    Resource groups      : {agg.get('resource_groups', result.get('resource_groups', result.get('groups', 0)))}")
        print(f"    Groups judged        : {judg.get('groups_judged', result.get('groups_judged', 0))}")
        if "llm_calls" in judg or "cache_hits" in judg:
            print(f"    LLM calls            : {judg.get('llm_calls', result.get('llm_calls', 0))}")
            print(f"    Cache hits           : {judg.get('cache_hits', result.get('cache_hits', 0))}")
        print(f"    Meaningful couplings : {judg.get('meaningful', result.get('meaningful', 0))}")
        print("")
        print("  Graph")
        print(f"    Nodes                : {graph_a.get('nodes', result.get('nodes', 0))}")
        print(f"    Edges                : {graph_a.get('edges', result.get('edges', 0))}")
    else:
        # Fallback for old reports without accounting
        print(f"  Services analyzed     : {result.get('services_analyzed', result.get('services', 0))} services in compose")
        print(f"  Candidates scanned    : {result.get('candidates', 0)} shared env/volume candidates")
        print(f"  Observations          : {result.get('observations', 0)}")
        print(f"  Resource groups       : {result.get('groups', 0)}")
        print(f"  Meaningful couplings  : {result.get('meaningful', 0)}")
        print(f"  Graph                 : {result.get('nodes', 0)} nodes, {result.get('edges', 0)} edges")
    if result.get("deterministic_only"):
        print("  Mode                  : deterministic-only (no LLM)")
    else:
        print(f"  Provider / Thinking   : {result.get('provider', 'auto')} / {result.get('thinking', thinking)}")
    # Show versioned file names (report.json vs report_1.json etc.)
    print("")
    print(f"  Report   : {result.get('report.md', result['out_dir'] + '\\\\report.md')}")
    print(f"  Data     : {result.get('report.json', result['out_dir'] + '\\\\report.json')}")
    print(f"  Graph    : {result.get('graph.json', result['out_dir'] + '\\\\graph.json')}")
    print(f"  Log      : {result.get('report.log.json', result['out_dir'] + '\\\\report.log.json')}")
    if result.get("deterministic_only"):
        print("")
        print("  Note: deterministic-only output contains structural JSONs only.")
        print("  Re-run and provide an API key for AI reasoning (verdict/confidence).")
    # Hint if versioned (history kept)
    if result.get("report.json") and result["report.json"] != str(Path(result["out_dir"]) / "report.json"):
        print(f"  History  : previous outputs kept as report.json, report_1.json, ... in {result['out_dir']}")
    print("  " + "=" * 44)
    return 0


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _versioned_path(base: Path) -> Path:
    """Return versioned path to avoid overwriting history.

    Default is base (e.g. report.json). If base exists, first duplicate is
    base_1 (report_1.json), next is base_2, etc. Handles report.log.json
    specially as report_1.log.json.
    """
    if not base.exists():
        return base
    # Determine stem/suffix handling for report.log.json
    if base.name == "report.log.json":
        stem = "report"
        suffix = ".log.json"
    else:
        # e.g. report.json -> stem report, suffix .json; report.md -> stem report, suffix .md
        stem = base.stem  # for report.json -> report, for report.md -> report, for graph.json -> graph
        # Handle double suffix already done; otherwise use suffix
        suffix = "".join(base.suffixes) if len(base.suffixes) > 1 else base.suffix
        # For report.json, suffixes is ['.json'], stem is 'report' — correct
        # For graph.json, same
    # Find next available version
    n = 1
    while True:
        if base.name == "report.log.json":
            cand = base.parent / f"{stem}_{n}{suffix}"
        else:
            cand = base.parent / f"{stem}_{n}{suffix}"
        if not cand.exists():
            return cand
        n += 1


def _discover_compose_sources(repo: Path) -> list[Path]:
    """Discover all compose files under repo (for accounting)."""
    found: list[Path] = []
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        found.extend(repo.rglob(name))
    # Also check top-level directly (rglob already covers)
    # Deduplicate and sort for determinism
    uniq = sorted({p.resolve() for p in found})
    return uniq


def _relative_to_root(path: Path, root: Path) -> str:
    """Prefer relative path to root; fallback to absolute if outside."""
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except ValueError:
        return path.resolve().as_posix()
    except Exception:
        return str(path)


def find_compose(repo: Path, compose_arg: Optional[str]) -> Optional[Path]:
    if compose_arg:
        p = Path(compose_arg)
        if not p.is_absolute():
            cand = repo / p
            if cand.exists():
                return cand
            if p.exists():
                return p
        return p if p.exists() else None
    # Prefer top-level files first; only rglob once if not found at top level
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        cand = repo / name
        if cand.exists():
            return cand
    # Fallback: search recursively (single scan, shallowest first)
    candidates: list[Path] = []
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        candidates.extend(repo.rglob(name))
    if candidates:
        # shallowest (fewest parents) first, then lexicographically for determinism
        candidates.sort(key=lambda p: (len(p.relative_to(repo).parts), str(p)))
        return candidates[0]
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
    repo_name = repo_path.name or "repo"  # empty when path is C:\
    # Deterministic out dir: always out_root / repo_name (no sys.argv hack)
    # If out_root has a suffix (e.g. out/custom.json) treat as file parent; otherwise treat as directory root
    if out_root.suffix:
        out_dir = out_root.parent / repo_name
    else:
        out_dir = out_root / repo_name
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {"repo": str(repo_path), "out_dir": str(out_dir), "error": None}

    # Input sources accounting (prompt §1)
    discovered_sources = _discover_compose_sources(repo_path)
    discovered_rel = [_relative_to_root(p, repo_path) for p in discovered_sources]

    compose_file = find_compose(repo_path, str(compose_path) if compose_path else None)
    # sources_used: actual file(s) parsed (relative to root)
    sources_used: list[str] = []
    if compose_file is not None and compose_file.exists():
        sources_used = [_relative_to_root(compose_file, repo_path)]
    sources_parsed: list[str] = []  # will be filled after successful parse
    successfully_parsed_count = 0

    if compose_file is None or not compose_file.exists():
        result["error"] = f"docker-compose.yml not found in {repo_path} (tried {compose_path or 'auto'})"
        model = CouplingModel([])
        graph = build_graph_from_groups(model, meaningful_only=True)
        # Accounting for no-source case
        accounting = {
            "application_root": str(repo_path),
            "sources": {
                "discovered": discovered_rel,
                "discovered_count": len(discovered_rel),
                "successfully_parsed": [],
                "successfully_parsed_count": 0,
                "used": sources_used,
                "used_count": len(sources_used),
            },
            "parsed": {"services": 0, "named_volumes": 0},
            "discovery": {"raw_candidates": 0, "observations": 0, "filtered_out": 0},
            "aggregation": {"resource_groups": 0, "observations": 0},
            "judgment": {"groups_judged": 0, "meaningful": 0, "coincidental": 0, "uncertain": 0, "llm_calls": 0, "cache_hits": 0},
            "graph": {"nodes": 0, "edges": 0, "service_nodes": 0, "resource_nodes": 0},
        }
        report = build_grouped_report(model, graph_data=graph, meaningful_only=meaningful_only, total_services=0, accounting=accounting)
        for base_name, content in [
            ("report.json", report.to_json()),
            ("report.md", report.to_markdown()),
            ("graph.json", json.dumps(graph, indent=2, ensure_ascii=False)),
        ]:
            p = _versioned_path(out_dir / base_name)
            p.write_text(content, encoding="utf-8")
            result[base_name] = str(p)
        result.update({"candidates": 0, "packages": 0, "observations": 0, "groups": 0, "meaningful": 0, "nodes": 0, "edges": 0, "services_analyzed": 0, "accounting": accounting})
        return result

    try:
        project = parse_compose_file(str(compose_file))
        sources_parsed = list(sources_used)
        successfully_parsed_count = 1
    except Exception as e:
        result["error"] = f"Failed to parse {compose_file}: {type(e).__name__}: {e}"
        model = CouplingModel([])
        graph = build_graph_from_groups(model, meaningful_only=True)
        accounting = {
            "application_root": str(repo_path),
            "sources": {
                "discovered": discovered_rel,
                "discovered_count": len(discovered_rel),
                "successfully_parsed": [],
                "successfully_parsed_count": 0,
                "used": sources_used,
                "used_count": len(sources_used),
            },
            "parsed": {"services": 0, "named_volumes": 0},
            "discovery": {"raw_candidates": 0, "observations": 0, "filtered_out": 0},
            "aggregation": {"resource_groups": 0, "observations": 0},
            "judgment": {"groups_judged": 0, "meaningful": 0, "coincidental": 0, "uncertain": 0, "llm_calls": 0, "cache_hits": 0},
            "graph": {"nodes": 0, "edges": 0, "service_nodes": 0, "resource_nodes": 0},
        }
        report = build_grouped_report(model, graph_data=graph, meaningful_only=meaningful_only, total_services=0, accounting=accounting)
        for base_name, content in [
            ("report.json", report.to_json()),
            ("report.md", report.to_markdown()),
            ("graph.json", json.dumps(graph, indent=2, ensure_ascii=False)),
        ]:
            p = _versioned_path(out_dir / base_name)
            p.write_text(content, encoding="utf-8")
            result[base_name] = str(p)
        result.update({"candidates": 0, "packages": 0, "observations": 0, "groups": 0, "meaningful": 0, "nodes": 0, "edges": 0, "services_analyzed": 0, "accounting": accounting})
        return result
    # Successful parse
    sources_parsed = list(sources_used)
    successfully_parsed_count = 1
    candidates = discover_candidates(project)
    packages = build_evidence_packages(candidates, project)

    load_dotenv(".env")
    import os

    # --- API key check: prompt every time no key is present ---
    deterministic_only = False
    if not _has_api_key():
        # Prompt user; deterministic_only indicates they said No or non-interactive
        deterministic_only = _prompt_for_api_key()
        # Re-evaluate provider after potential key entry
        if not deterministic_only and not _has_api_key():
            # Still no key after prompt (e.g. empty) — treat as deterministic
            deterministic_only = True

    if provider == "auto":
        if os.getenv("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            provider = "gemini"
        else:
            provider = "openrouter"
            if not deterministic_only:
                # No key but we didn't go deterministic (edge) — will failsafe
                print("  [warning] No API key found — LLM calls will failsafe to uncertain 0.5")
    else:
        # Explicit provider but missing key for that provider
        need = "OPENROUTER_API_KEY" if provider == "openrouter" else "GEMINI_API_KEY"
        alt = "GEMINI_API_KEY" if provider == "openrouter" else "OPENROUTER_API_KEY"
        if not os.getenv(need) and not os.getenv(alt) and not deterministic_only:
            # Already prompted above if no key at all; if we are here provider-specific missing but other exists, no prompt needed
            pass

    # Validate thinking early for non-interactive callers
    if thinking not in VALID_THINKING:
        # Map legacy 'none' to 'low' with warning, otherwise error
        if thinking == "none":
            thinking = "low"
        else:
            result["error"] = f"Invalid thinking level {thinking!r}. Allowed: low, medium, high."
            return result

    if provider == "gemini":
        from .judge import GeminiJudgeClient
        client = GeminiJudgeClient(thinking_level=thinking)  # type: ignore[arg-type]
    else:
        from .judge import OpenRouterJudgeClient
        client = OpenRouterJudgeClient(thinking_level=thinking)  # type: ignore[arg-type]

    grouped = aggregate_evidence_packages(packages)

    # --- Deterministic-only branch: skip LLM, only JSONs, no AI reasoning ---
    # Track LLM vs cache for accounting (prompt §4 groups_judged vs LLM calls)
    cache_hits = 0
    llm_calls = 0
    if deterministic_only:
        if grouped:
            print("  [info] Deterministic-only mode: skipped", len(grouped), "LLM call(s) — producing structural JSONs only.")
        else:
            print("  [info] Deterministic-only mode: no resource groups to judge.")
        from .judge import JudgeResult as _JR  # noqa: F401 (kept for clarity)
        pairs = _deterministic_pairs(grouped)
        # Do not use cache in deterministic mode
        c_path = None
        # client not needed, but keep for type; we won't call judge
        client = None  # type: ignore[assignment]
        llm_calls = 0
        cache_hits = 0
        model = CouplingModel.from_grouped_judgments(pairs)
    else:
        c_path = str(cache_path) if cache_path else None
        # BASE fast-track: contextual judge + deterministic scoring (primary),
        # legacy grouped judge as fallback. D-042 pipeline otherwise intact.
        try:
            from .context import build_context_bundle
            from .context_judge import judge_contextual_packages
            from .judge import JudgeResult as _JR2
            from .scoring import score_group, verdict_from_scoring

            bundles = {g.grouping_key: build_context_bundle(g, project, repo_path) for g in grouped}
            # Pre-count contextual cache hits for accounting
            if c_path and Path(c_path).exists():
                try:
                    from .judge import _load_cache as _lc2
                    from .context_judge import _cache_key as _ctx_key
                    _cb = _lc2(c_path)
                    for g in grouped:
                        try:
                            if _ctx_key(g, bundles[g.grouping_key]) in _cb:
                                cache_hits += 1
                        except Exception:
                            pass
                    llm_calls = len(grouped) - cache_hits
                except Exception:
                    llm_calls = len(grouped)
                    cache_hits = 0
            else:
                llm_calls = len(grouped)
                cache_hits = 0
            ctx_results = judge_contextual_packages(grouped, bundles, client,
                                                    cache_path=c_path, use_cache=bool(c_path))
            pairs = []
            _scorings = []
            for g, signals, mname in ctx_results:
                sc = score_group(g, signals)
                verdict, conf, reason = verdict_from_scoring(sc, signals)
                pairs.append((g, _JR2(verdict=verdict, confidence=conf, reason=reason, model=mname)))
                _scorings.append(sc)
            model = CouplingModel.from_grouped_judgments(pairs)
            # Enrich with deterministic scoring (replaceable layer output)
            try:
                model = CouplingModel([g.with_scoring(sc) for g, sc in zip(model.groups, _scorings)])
            except Exception:
                pass
        except Exception as e:
            print(f"  [warning] BASE contextual path failed ({type(e).__name__}), falling back to legacy judge.")
            from .judge import judge_grouped_packages
            if c_path and Path(c_path).exists():
                try:
                    from .judge import _load_cache
                    from .judge import _cache_key_for_grouped
                    _cache_before = _load_cache(c_path)
                    for g in grouped:
                        try:
                            k = _cache_key_for_grouped(g)
                            if k in _cache_before:
                                cache_hits += 1
                        except Exception:
                            pass
                    llm_calls = len(grouped) - cache_hits
                except Exception:
                    llm_calls = len(grouped)
                    cache_hits = 0
            else:
                llm_calls = len(grouped)
                cache_hits = 0
            pairs = judge_grouped_packages(grouped, client, cache_path=c_path, use_cache=bool(c_path))
            model = CouplingModel.from_grouped_judgments(pairs)
            # Score fallback too (signals = failsafe) so report still shows classification
            try:
                from .scoring import score_group as _sg
                from .context_judge import validate_signals as _vs
                _sig = _vs([])
                model = CouplingModel([g.with_scoring(_sg(g.grouped_package or g, _sig)) for g in model.groups])
            except Exception:
                pass
        # After judging, if cache was used, actual cache hits may be higher than pre-count
        # For simplicity, keep pre-count; llm_calls is groups not in cache before call

    # Deterministic-only scoring enrichment (no LLM): run scoring on failsafe signals
    if deterministic_only:
        try:
            from .scoring import score_group as _sg2
            from .context_judge import _failsafe_signal, QUESTION_IDS
            _sig2 = [_failsafe_signal(q, "deterministic-only") for q in QUESTION_IDS]
            model = CouplingModel([g.with_scoring(_sg2(g.grouped_package or g, _sig2)) for g in model.groups])
        except Exception:
            pass
    graph = build_graph_from_groups(model, meaningful_only=meaningful_only)
    # Build full accounting (prompt §2)
    raw_candidates = len(candidates)
    observations = len(packages)
    filtered_out = max(0, raw_candidates - observations)
    resource_groups = len(grouped)
    groups_judged = len(grouped)  # all groups sent through judgment (even if deterministic)
    # meaningful/coincidental/uncertain from model (judged)
    meaningful_cnt = len([g for g in model.groups if g.verdict == "meaningful"])
    coincidental_cnt = len([g for g in model.groups if g.verdict == "coincidental"])
    uncertain_cnt = len([g for g in model.groups if g.verdict == "uncertain"])
    named_volumes_cnt = 0
    try:
        named_volumes_cnt = project.count_named_volumes()  # type: ignore[attr-defined]
    except Exception:
        # Fallback: count distinct named volumes from services
        seen = set()
        for svc in project.services.values():
            for vol in svc.volumes:
                if vol.type == "named" and vol.source:
                    seen.add(vol.source)
        named_volumes_cnt = len(seen)
    accounting = {
        "application_root": str(repo_path),
        "sources": {
            "discovered": discovered_rel,
            "discovered_count": len(discovered_rel),
            "successfully_parsed": sources_parsed,
            "successfully_parsed_count": len(sources_parsed),
            "used": sources_used,
            "used_count": len(sources_used),
        },
        "parsed": {"services": len(project.services), "named_volumes": named_volumes_cnt},
        "discovery": {"raw_candidates": raw_candidates, "observations": observations, "filtered_out": filtered_out},
        "aggregation": {"resource_groups": resource_groups, "observations": observations},
        "judgment": {
            "groups_judged": groups_judged,
            "meaningful": meaningful_cnt,
            "coincidental": coincidental_cnt,
            "uncertain": uncertain_cnt,
            "llm_calls": llm_calls,
            "cache_hits": cache_hits,
        },
        "graph": {
            "nodes": len(graph.get("nodes", [])),
            "edges": len(graph.get("edges", [])),
            "service_nodes": len([n for n in graph.get("nodes", []) if n.get("type") == "service"]),
            "resource_nodes": len([n for n in graph.get("nodes", []) if n.get("type") == "resource"]),
        },
    }
    report = build_grouped_report(model, graph_data=graph, meaningful_only=meaningful_only, total_services=len(project.services), accounting=accounting)

    # Versioned writes — keep history: report.json, report_1.json, report_2.json, ...
    report_json_path = _versioned_path(out_dir / "report.json")
    report_json_path.write_text(report.to_json(), encoding="utf-8")
    result["report.json"] = str(report_json_path)
    # In deterministic-only mode, still write report.md but it will clearly state
    # that AI reasoning was skipped; user asked for "only JSONs" — we keep the
    # markdown as minimal notice rather than full AI verdicts to avoid confusion.
    if deterministic_only:
        det_notice = (
            "# BlindSpot Report — Deterministic-Only Mode\n\n"
            "> No LLM API key was provided, so semantic judgment was skipped.\n"
            "> Outputs below are structural only (graph + raw evidence) and may be less accurate.\n\n"
        )
        md_content = det_notice + report.to_markdown()
    else:
        md_content = report.to_markdown()
    report_md_path = _versioned_path(out_dir / "report.md")
    report_md_path.write_text(md_content, encoding="utf-8")
    result["report.md"] = str(report_md_path)
    graph_json_path = _versioned_path(out_dir / "graph.json")
    graph_json_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    result["graph.json"] = str(graph_json_path)
    # In deterministic mode still log for audit
    log_provider = "deterministic" if deterministic_only else provider
    report_log_path = _versioned_path(out_dir / "report.log.json")
    report_log_path.write_text(
        json.dumps(
            {
                "model": "report_log",
                "provider": log_provider,
                "thinking": thinking,
                "deterministic_only": deterministic_only,
                "coupling_log": model.to_log_list(),
                "grouped": True,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result["report.log.json"] = str(report_log_path)

    result.update(
        {
            "compose": str(compose_file),
            "application_root": str(repo_path),
            "sources_used": sources_used,
            "sources_discovered": discovered_rel,
            "services_analyzed": len(project.services),
            "services": len(project.services),
            "named_volumes": named_volumes_cnt,
            "candidates": len(candidates),
            "raw_candidates": raw_candidates,
            "packages": len(packages),
            "observations": len(packages),
            "filtered_out": filtered_out,
            "groups": len(model.groups),
            "resource_groups": resource_groups,
            "groups_judged": groups_judged,
            "llm_calls": llm_calls,
            "cache_hits": cache_hits,
            "dependencies": len(model.groups),
            "meaningful": len(model.meaningful_only().groups),
            "reported": len(report.findings),
            "accounting": accounting,
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "provider": provider,
            "thinking": thinking,
            "deterministic_only": deterministic_only,
        }
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    # If no args at all (user just runs: python -m blindspot.cli), launch interactive menu
    raw_argv = sys.argv[1:] if argv is None else argv
    if argv is None and len(sys.argv) == 1:
        return _run_interactive()
    if argv is not None and len(argv) == 0:
        return _run_interactive()

    p = argparse.ArgumentParser(
        prog="blindspot",
        description="BlindSpot — interactive analysis (default) or advanced flags for scripting.",
        epilog="Interactive:  python -m blindspot.cli   (asks for absolute path + thinking)\nAdvanced:   python -m blindspot.cli \"C:\\path\\to\\repo\" --thinking low",
    )
    p.add_argument(
        "repos",
        nargs="*",
        default=None,
        help="Repo dirs to analyze (absolute paths, e.g. C:\\path\\to\\repo). If omitted, interactive menu is shown.",
    )
    p.add_argument("--compose", default=None, help="Explicit compose file (relative to repo or absolute). Default: auto-find docker-compose.yml")
    p.add_argument("--out", dest="out", default="out", help="Output root dir (default: out/<repo_name>/)")
    p.add_argument("--provider", choices=["auto", "openrouter", "gemini"], default="auto", help="LLM provider (default: auto)")
    p.add_argument("--thinking", choices=["low", "medium", "high"], default=None, help="Thinking effort: low (fast) | medium | high")
    p.add_argument("--cache", default="cache.json", help="Cache file for LLM verdicts (default: cache.json, use 'none' to disable)")
    p.add_argument("--all", action="store_true", help="Include coincidental/uncertain in graph/report (default: meaningful_only)")
    p.add_argument("--list-fixtures", action="store_true", help="List bundled fixtures and exit")
    p.add_argument("--interactive", action="store_true", help="Force interactive menu (asks for absolute path + thinking)")

    args = p.parse_args(argv)

    if args.list_fixtures:
        print("Bundled fixtures:")
        for f in ["fixtures/shared_env", "fixtures/shared_volume", "fixtures/near_miss"]:
            print(f"  {f}")
        return 0

    # Interactive trigger: --interactive or no repos supplied
    if args.interactive or args.repos is None or len(args.repos) == 0:
        # If user explicitly passed --thinking with no repos, honour it without prompting
        if args.thinking is not None and args.repos is not None and len(args.repos) == 0:
            # Means caller did: --thinking low with no path — treat as error, show interactive
            pass
        # If repos is None (no positional) -> interactive
        if args.repos is None or args.interactive or len(args.repos) == 0:
            # If advanced flags like --compose/--provider were explicitly set, don't hide interactive;
            # but still prefer interactive when no repos. To avoid confusion, if any repo-independent flag
            # besides defaults was set, warn and proceed to interactive.
            return _run_interactive()

    # Advanced / batch mode: repos provided
    out_root = Path(args.out)
    cache_path = None if (args.cache or "").lower() == "none" else Path(args.cache)
    meaningful_only = not args.all
    thinking = args.thinking or "low"

    if thinking not in VALID_THINKING:
        print(f"[error] Invalid thinking level {thinking!r}. Allowed: low, medium, high.")
        return 2

    # Validate each repo path is absolute from C drive
    for repo_str in list(args.repos or []):
        rp = Path(_strip_quotes(repo_str))
        if not _is_absolute_windows_path(rp):
            print(f"[error] Repo path must be absolute from C drive: {repo_str!r}")
            print("        Example: \"C:\\path\\to\\YourApp\"")
            return 2

    print(f"Provider: {args.provider}  Thinking: {thinking}  Out: {out_root}")

    for repo_str in args.repos or []:
        repo = Path(_strip_quotes(repo_str))
        if not repo.exists():
            print(f"[error] repo not found: {repo}")
            print("        Path must be absolute from C drive, e.g. C:\\path\\to\\YourApp")
            continue
        if repo.is_file():
            repo = repo.parent
        try:
            res = run_one_repo(repo, Path(args.compose) if args.compose else None, out_root, args.provider, thinking, cache_path, meaningful_only)
        except Exception as e:
            print(f"  [error] {e}")
            import traceback
            traceback.print_exc()
            continue
        if res.get("error"):
            print(f"  {res['error']}")
        # Show versioned files (report.json vs report_1.json etc.)
        rf = Path(res.get("report.json", "")).name if res.get("report.json") else "report.json"
        rm = Path(res.get("report.md", "")).name if res.get("report.md") else "report.md"
        gf = Path(res.get("graph.json", "")).name if res.get("graph.json") else "graph.json"
        print(f"Out: {res['out_dir']}/{rf} + {rm} + {gf}  (history kept as _1, _2, ...)")
        if res.get("report.json") and res["report.json"] != str(Path(res["out_dir"]) / "report.json"):
            print(f"     previous outputs preserved in {res['out_dir']}")
        # Also print accounting summary for batch mode (same as interactive)
        acc = res.get("accounting")
        if acc:
            print(f"  Services: {acc.get('parsed', {}).get('services', 0)} | Candidates: {acc.get('discovery', {}).get('raw_candidates', 0)} -> Observations: {acc.get('discovery', {}).get('observations', 0)} -> Groups: {acc.get('aggregation', {}).get('resource_groups', 0)} -> Meaningful: {acc.get('judgment', {}).get('meaningful', 0)} | Graph: {acc.get('graph', {}).get('nodes', 0)} nodes/{acc.get('graph', {}).get('edges', 0)} edges")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
