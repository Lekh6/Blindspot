"""BlindSpot BASE — Bounded context bundle (evidence construction).

Isolated, replaceable. No LLM calls here. Deterministic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

MAX_TREE_DEPTH = 2
MAX_TREE_ENTRIES = 30
MAX_SNIPPET_FILES = 3
MAX_SNIPPET_CHARS = 2000
MAX_SNIPPET_LINES = 40

SKIP_DIRS = {".venv", ".git", "out", "__pycache__", "node_modules", ".cache",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".java", ".go", ".rb",
             ".php", ".env", ".yml", ".yaml", ".toml", ".ini", ".cfg"}

_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _tokens_for_group(grouped: Any) -> List[str]:
    toks: List[str] = []
    for var in list(getattr(grouped, "observation_resources", []) or []):
        toks.append(str(var))
        for part in _TOKEN_SPLIT_RE.split(str(var)):
            if len(part) >= 3:
                toks.append(part)
    ident = getattr(grouped, "resource_identity", None) or ""
    for part in _TOKEN_SPLIT_RE.split(str(ident)):
        if len(part) >= 3 and part.lower() not in {"postgresql", "postgres", "mysql", "mongodb", "redis"}:
            toks.append(part)
    # de-dup, keep order, cap
    seen: List[str] = []
    for t in toks:
        if t and t not in seen:
            seen.append(t)
        if len(seen) >= 12:
            break
    return seen


def build_file_tree(repo_root: Path, max_depth: int = MAX_TREE_DEPTH,
                    max_entries: int = MAX_TREE_ENTRIES) -> List[str]:
    """Bounded relevant file tree (relative paths, sorted). Never walks whole repo deeply."""
    root = Path(repo_root)
    out: List[str] = []
    if not root.exists() or not root.is_dir():
        return out
    try:
        # top-level + 1-2 levels only
        for p in sorted(root.iterdir()):
            if len(out) >= max_entries:
                break
            if p.name in SKIP_DIRS or p.name.startswith("."):
                if p.name not in (".env",):
                    continue
            rel = p.name
            out.append(rel + ("/" if p.is_dir() else ""))
            if p.is_dir() and max_depth >= 2 and len(out) < max_entries:
                try:
                    for q in sorted(p.iterdir())[:10]:
                        if len(out) >= max_entries:
                            break
                        if q.name in SKIP_DIRS:
                            continue
                        out.append(f"{rel}{q.name}" + ("/" if q.is_dir() else ""))
                except Exception:
                    continue
    except Exception:
        return out
    return out[:max_entries]


def collect_source_snippets(repo_root: Path, grouped: Any,
                            max_files: int = MAX_SNIPPET_FILES,
                            max_chars: int = MAX_SNIPPET_CHARS) -> List[Dict[str, Any]]:
    """Cheap heuristic: grep tokens in code-like files. Bounded. No AST."""
    root = Path(repo_root)
    if not root.exists():
        return []
    tokens = _tokens_for_group(grouped)
    if not tokens:
        return []
    candidates: List[Path] = []
    try:
        for p in sorted(root.rglob("*")):
            if len(candidates) >= 100:
                break
            if not p.is_file():
                continue
            if any(part in p.parts for part in SKIP_DIRS):
                continue
            if p.suffix.lower() not in CODE_EXTS:
                continue
            # skip huge files
            try:
                if p.stat().st_size > 200_000:
                    continue
            except Exception:
                continue
            candidates.append(p)
    except Exception:
        return []
    snippets: List[Dict[str, Any]] = []
    lowered = [t.lower() for t in tokens]
    for p in candidates:
        if len(snippets) >= max_files:
            break
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        low = text.lower()
        hit_line: Optional[int] = None
        hit_tok: Optional[str] = None
        lines = text.splitlines()
        for i, line in enumerate(lines[:500], 1):
            ll = line.lower()
            for tok in lowered:
                if tok and tok in ll:
                    hit_line = i
                    hit_tok = tok
                    break
            if hit_line is not None:
                break
        if hit_line is None:
            continue
        start = max(0, hit_line - 1 - 10)
        end = min(len(lines), start + MAX_SNIPPET_LINES)
        snippet_text = "\n".join(lines[start:end])[:max_chars]
        try:
            rel = str(p.relative_to(root))
        except Exception:
            rel = p.name
        snippets.append({"file": rel, "line": hit_line, "token": hit_tok,
                         "text": snippet_text})
    return snippets


@dataclass(frozen=True)
class ContextBundle:
    grouping_key: str
    compose_slice: Dict[str, Any]  # service -> {image, vars}
    deterministic_facts: Dict[str, Any]
    file_tree: tuple = field(default_factory=tuple)
    snippets: tuple = field(default_factory=tuple)  # tuple of dicts

    def to_dict(self) -> Dict[str, Any]:
        return {"grouping_key": self.grouping_key,
                "compose_slice": dict(self.compose_slice),
                "deterministic_facts": dict(self.deterministic_facts),
                "file_tree": list(self.file_tree),
                "snippets": list(self.snippets)}

    def cache_key_dict(self) -> Dict[str, Any]:
        import hashlib, json
        snip_hashes = []
        for s in self.snippets:
            if isinstance(s, dict):
                payload = json.dumps(s, sort_keys=True)[:500]
                snip_hashes.append(hashlib.sha256(payload.encode()).hexdigest()[:16])
        return {"grouping_key": self.grouping_key,
                "compose_slice": self.compose_slice,
                "facts": self.deterministic_facts,
                "tree": list(self.file_tree),
                "snippet_hashes": sorted(snip_hashes)}


def build_context_bundle(grouped: Any, project: Any = None,
                         repo_root: Optional[Path] = None) -> ContextBundle:
    """One bounded bundle per resource group. Deterministic."""
    services = list(getattr(grouped, "services", []) or [])
    config_ev = dict(getattr(grouped, "configuration_evidence", {}) or {})
    compose_slice: Dict[str, Any] = {}
    if project is not None and hasattr(project, "services"):
        for svc in services:
            s = project.services.get(svc)
            if s is None:
                continue
            wanted = set(config_ev.get(svc, []) or [])
            env = {k: v for k, v in (s.environment or {}).items() if k in wanted} if wanted else {}
            compose_slice[svc] = {"image": getattr(s, "image", None), "vars": env}
    else:
        for svc in services:
            compose_slice[svc] = {"image": None, "vars": {k: None for k in config_ev.get(svc, [])}}
    facts = {"resource_identity": getattr(grouped, "resource_identity", None),
             "resource_protocol": getattr(grouped, "resource_protocol", None),
             "resource_type": getattr(grouped, "resource_type", None),
             "resolution_status": getattr(grouped, "resolution_status", None),
             "identity_strength": getattr(grouped, "identity_strength", None),
             "services": sorted(services),
             "evidence_count": getattr(grouped, "evidence_count", 0),
             "unresolved_vars": sorted(getattr(grouped, "unresolved_vars", []) or [])}
    tree: List[str] = []
    snippets: List[Dict[str, Any]] = []
    if repo_root is not None:
        tree = build_file_tree(Path(repo_root))
        snippets = collect_source_snippets(Path(repo_root), grouped)
    return ContextBundle(grouping_key=getattr(grouped, "grouping_key", ""),
                         compose_slice=compose_slice,
                         deterministic_facts=facts,
                         file_tree=tuple(tree),
                         snippets=tuple(snippets))
