"""
BlindSpot Stage 1: Input Adapters — format handling boundary.

Architecture:
    Input format → adapter/parser → canonical Project → existing pipeline.

Downstream stages consume the normalized Project/Service/Volume model and
must not depend on YAML syntax or a particular filename. Docker Compose is
the primary, fully supported input. JSON is supported only as an equivalent
representation of the same Compose model (same semantics, same discovery).

Supported (tested):
  - docker-compose.yml, docker-compose.yaml, compose.yml, compose.yaml
  - docker-compose.json, compose.json (equivalent Compose model as JSON)
  - .env next to compose file, service-level env_file (string/list/{path,required})
  - environment mapping + list syntax, ${VAR}/${VAR:-default}/$VAR, unresolved preserved
  - multi-file merge (docker compose -f a -f b): env override, volumes union, image override
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

# ---------------------------------------------------------------------------
# Supported filenames
# ---------------------------------------------------------------------------

SUPPORTED_YAML_NAMES: List[str] = [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
]

SUPPORTED_JSON_NAMES: List[str] = [
    "docker-compose.json",
    "compose.json",
]

SUPPORTED_COMPOSE_FILENAMES: List[str] = SUPPORTED_YAML_NAMES + SUPPORTED_JSON_NAMES


def is_json_path(path: Union[Path, str]) -> bool:
    return Path(path).suffix.lower() == ".json"


def load_compose_document(compose_path: Union[Path, str]) -> Dict[str, Any]:
    """Load a Compose document from YAML or equivalent JSON.

    JSON support preserves Compose semantics: the parsed dict flows through the
    same normalization as YAML (no separate discovery implementation).
    Raises ValueError on invalid encoding/content, FileNotFoundError if missing.
    """
    p = Path(compose_path)
    if not p.exists():
        raise FileNotFoundError(f"Compose file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Compose file {p} is not valid UTF-8: {e}") from e
    try:
        if is_json_path(p):
            data = json.loads(text) if text.strip() else {}
        else:
            data = yaml.safe_load(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Compose file {p} is not valid JSON: {e}") from e
    except yaml.YAMLError as e:
        raise ValueError(f"Compose file {p} is not valid YAML: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Compose file {p} top-level must be a mapping")
    return data


def discover_compose_files(repo: Path) -> List[Path]:
    """Discover all supported Compose files under repo (deterministic, deduped)."""
    found: List[Path] = []
    for name in SUPPORTED_COMPOSE_FILENAMES:
        found.extend(repo.rglob(name))
    uniq = sorted({p.resolve() for p in found}, key=lambda p: p.as_posix())
    return uniq


def find_compose_file(repo: Path, compose_arg: Optional[str] = None) -> Optional[Path]:
    """Find the Compose file to parse: explicit arg wins, else top-level, else recursive.

    Deterministic: top-level names checked in SUPPORTED order; recursive fallback
    picks shallowest path then lexicographically smallest.
    """
    if compose_arg:
        p = Path(compose_arg)
        if not p.is_absolute():
            cand = repo / p
            if cand.exists():
                return cand
            if p.exists():
                return p
        return p if p.exists() else None
    for name in SUPPORTED_COMPOSE_FILENAMES:
        cand = repo / name
        if cand.exists():
            return cand
    candidates: List[Path] = []
    for name in SUPPORTED_COMPOSE_FILENAMES:
        candidates.extend(repo.rglob(name))
    if candidates:
        candidates.sort(key=lambda q: (len(q.relative_to(repo).parts), q.as_posix()))
        return candidates[0]
    return None
