"""
BlindSpot Stage 2: Parse + Normalize

Separation:
  1. Reading YAML          -> _load_yaml
  2. Reading .env          -> load_env_file
  3. Normalizing env       -> normalize_environment (+ _resolve_value)
  4. Normalizing volumes   -> normalize_volume / normalize_volumes
  5. Project representation -> parse_project / parse_compose_file / dataclasses
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Union

import yaml
from dotenv import dotenv_values  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Volume:
    source: Optional[str]
    target: str
    type: str  # "named" | "bind" | "anonymous"
    read_only: bool = False
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "read_only": self.read_only,
        }


@dataclass(frozen=True)
class Service:
    name: str
    environment: Dict[str, Optional[str]] = field(default_factory=dict)
    volumes: List[Volume] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": dict(self.environment),
            "volumes": [v.to_dict() for v in self.volumes],
        }


@dataclass(frozen=True)
class Project:
    services: Dict[str, Service] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "services": {name: svc.to_dict() for name, svc in self.services.items()}
        }


# ---------------------------------------------------------------------------
# 1. Reading YAML
# ---------------------------------------------------------------------------

def _load_yaml(compose_path: Path) -> Dict[str, Any]:
    text = compose_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Compose file {compose_path} top-level must be a mapping")
    return data


# ---------------------------------------------------------------------------
# 2. Reading .env
# ---------------------------------------------------------------------------

def load_env_file(env_path: Optional[Path]) -> Dict[str, str]:
    """Load .env file if it exists. Return empty dict if missing or None."""
    if env_path is None:
        return {}
    if not env_path.exists() or not env_path.is_file():
        return {}
    # dotenv_values handles quotes, comments, etc.
    values = dotenv_values(str(env_path))
    # dotenv returns None only for malformed/comment lines; "" for `VAR=` is
    # a valid value (empty string) and must be preserved — do NOT filter it.
    # Filtering None is correct; empty strings flow through as real values and
    # downstream LLM judgment must treat "" as intentional, not missing.
    return {k: v for k, v in values.items() if v is not None}


# ---------------------------------------------------------------------------
# 3. Normalizing environment
# ---------------------------------------------------------------------------

# Matches ${VAR} , ${VAR:-default} , $VAR
# We preserve unresolved references instead of inventing values.
_ENV_VAR_PATTERN = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}|\$(?P<unbraced>[A-Za-z_][A-Za-z0-9_]*)"
)


def _resolve_value(value: str, env_vars: Dict[str, str]) -> str:
    """Resolve ${VAR} / $VAR references using env_vars.

    If VAR exists in env_vars, substitute. If it has :-default, use default.
    Otherwise preserve the original reference (do not invent empty string).
    """

    def _repl(match: re.Match) -> str:
        braced = match.group("braced")
        default = match.group("default")
        unbraced = match.group("unbraced")
        var_name = braced if braced is not None else unbraced

        if var_name in env_vars:
            return env_vars[var_name]
        if default is not None:
            return default
        # Unresolved — keep original text
        return match.group(0)

    return _ENV_VAR_PATTERN.sub(_repl, value)


def normalize_environment(
    raw_env: Any,
    env_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[str]]:
    """Normalize Compose environment section to dict.

    Supports:
      - mapping: {DB_HOST: postgres, DB_NAME: orders}
      - list: ["DB_HOST=postgres", "DB_NAME=orders", "DEBUG"]
      - None -> {}

    For entries without '=', value is None (do not invent).
    String values are resolved against env_vars for ${VAR} references.
    """
    if env_vars is None:
        env_vars = {}

    if raw_env is None:
        return {}

    result: Dict[str, Optional[str]] = {}

    if isinstance(raw_env, dict):
        for key, val in raw_env.items():
            if val is None:
                # Explicit null -> None (no value)
                result[str(key)] = None
            else:
                # Convert to string then resolve
                str_val = str(val)
                result[str(key)] = _resolve_value(str_val, env_vars)
        return result

    if isinstance(raw_env, list):
        for item in raw_env:
            if not isinstance(item, str):
                # Unexpected non-string — coerce
                item = str(item)
            if "=" in item:
                key, val = item.split("=", 1)
                result[key] = _resolve_value(val, env_vars)
            else:
                # No value — preserve as None (do not invent)
                result[item] = None
        return result

    raise ValueError(f"Unsupported environment format: {type(raw_env)} -> {raw_env!r}")


# ---------------------------------------------------------------------------
# 4. Normalizing volumes
# ---------------------------------------------------------------------------

_KNOWN_RO_OPTIONS = {"ro", "rw"}
_KNOWN_VOLUME_OPTIONS = {"ro", "rw", "consistent", "delegated", "cached", "z", "Z", "nocopy"}


def _is_bind_source(source: str) -> bool:
    # Bind mounts have path-like sources
    if source.startswith(".") or source.startswith("/") or source.startswith("~"):
        return True
    if "/" in source or "\\" in source:
        return True
    return False


def normalize_volume(entry: Any, env_vars: Optional[Dict[str, str]] = None) -> Volume:
    """Normalize a single volume entry.

    Supports short string syntax and long dict syntax.
    Returns a Volume with structured source/target/type/read_only.
    """
    if env_vars is None:
        env_vars = {}

    # Long syntax: dict
    if isinstance(entry, dict):
        vol_type = entry.get("type", "volume")
        source = entry.get("source")
        target = entry.get("target", "")
        read_only = bool(entry.get("read_only", False))
        # Also check string options
        raw = str(entry)

        # Map long-syntax type to our type
        if vol_type == "bind":
            norm_type = "bind"
        elif vol_type == "volume":
            norm_type = "named"
        elif vol_type == "tmpfs":
            norm_type = "anonymous"
        else:
            norm_type = vol_type

        # Resolve env vars in source/target if needed
        if source is not None:
            source = _resolve_value(str(source), env_vars)
        if target:
            target = _resolve_value(str(target), env_vars)

        return Volume(
            source=source,
            target=str(target),
            type=norm_type,
            read_only=read_only,
            raw=raw,
        )

    # Short syntax: string
    if not isinstance(entry, str):
        entry = str(entry)

    raw = entry
    # Resolve env vars in whole string before splitting (minimal)
    # This is shallow: we resolve after split for accuracy but also try whole
    # For simplicity, resolve source/target after split

    # Split by ":" — handle 1, 2, or 3 parts
    parts = entry.split(":")

    # Heuristic for options: last part may be a comma-separated option list
    # Detect if last part is options-only
    def _is_option_part(p: Optional[str]) -> bool:
        if p is None:
            return False
        # Comma-separated options like "ro,consistent"
        sub = [s.strip() for s in p.split(",")]
        return all(s in _KNOWN_VOLUME_OPTIONS for s in sub if s) and len(sub) > 0

    source: Optional[str] = None
    target: str = ""
    read_only = False
    options_part: Optional[str] = None

    if len(parts) == 1:
        # Anonymous volume: just target
        target = _resolve_value(parts[0], env_vars)
        source = None
        norm_type = "anonymous"
        return Volume(source=source, target=target, type=norm_type, read_only=False, raw=raw)

    elif len(parts) == 2:
        a, b = parts
        # Could be source:target OR target:options
        if _is_option_part(b):
            # target:options -> anonymous with options
            target = _resolve_value(a, env_vars)
            source = None
            options_part = b
            norm_type = "anonymous"
        else:
            source = _resolve_value(a, env_vars)
            target = _resolve_value(b, env_vars)
            if source == "" or source is None:
                source = None
                norm_type = "anonymous"
            elif _is_bind_source(source):
                norm_type = "bind"
            else:
                norm_type = "named"

        if options_part and "ro" in options_part.split(","):
            read_only = True
        return Volume(source=source, target=target, type=norm_type, read_only=read_only, raw=raw)

    elif len(parts) >= 3:
        # source:target:options (or more colons in Windows paths — keep simple)
        # For >3 parts (e.g., Windows C:\path:/target:ro) we re-join middle
        # Simplistic: first part is source, last part is options, middle is target
        source = _resolve_value(parts[0], env_vars)
        options_part = parts[-1]
        target = _resolve_value(":".join(parts[1:-1]), env_vars)

        if _is_option_part(options_part) and options_part is not None:
            if "ro" in options_part.split(","):
                read_only = True
        else:
            # No valid options — treat as source:target with colon in target
            target = _resolve_value(":".join(parts[1:]), env_vars)
            options_part = None

        if source is None or source == "":
            norm_type = "anonymous"
            source = None
        elif _is_bind_source(source):
            norm_type = "bind"
        else:
            norm_type = "named"

        return Volume(source=source, target=target, type=norm_type, read_only=read_only, raw=raw)

    # Fallback
    return Volume(source=None, target=entry, type="anonymous", read_only=False, raw=raw)


def normalize_volumes(
    raw_volumes: Any,
    env_vars: Optional[Dict[str, str]] = None,
) -> List[Volume]:
    if raw_volumes is None:
        return []
    if not isinstance(raw_volumes, list):
        raise ValueError(f"Unsupported volumes format: {type(raw_volumes)} -> {raw_volumes!r}")
    return [normalize_volume(v, env_vars) for v in raw_volumes]


# ---------------------------------------------------------------------------
# 5. Final project representation
# ---------------------------------------------------------------------------

def _resolve_env_file_path(raw_path: str | Path, base: Path) -> Path:
    """Resolve env_file path relative to compose file's directory."""
    p = Path(raw_path)
    if not p.is_absolute():
        p = base / p
    return p


def _load_service_env_files(
    raw_env_file: Any,
    compose_dir: Path,
) -> Dict[str, str]:
    """Load env_file entries (string or list, str or {path, required}) and merge.

    Files are processed in order; later files override earlier ones.
    Uses ``load_env_file`` so ``VAR=`` yields ``""`` (preserved) and malformed
    lines (None) are dropped.
    """
    if raw_env_file is None:
        return {}
    # Normalize to list of entries
    if isinstance(raw_env_file, (str, Path)):
        entries: List[Any] = [raw_env_file]
    elif isinstance(raw_env_file, dict):
        # single object form: {path: "...", required: false}
        entries = [raw_env_file]
    elif isinstance(raw_env_file, list):
        entries = raw_env_file
    else:
        raise ValueError(f"Unsupported env_file format: {type(raw_env_file)} -> {raw_env_file!r}")

    merged: Dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict):
            raw_path = entry.get("path")
            if not raw_path:
                continue
            required = bool(entry.get("required", True))
            ef_path = _resolve_env_file_path(raw_path, compose_dir)
            if not ef_path.exists() and not required:
                continue
        elif isinstance(entry, (str, Path)):
            ef_path = _resolve_env_file_path(entry, compose_dir)
        else:
            # Coerce unexpected types to string path
            ef_path = _resolve_env_file_path(str(entry), compose_dir)

        loaded = load_env_file(ef_path)
        # Later files override earlier (Docker spec)
        merged.update(loaded)
    return merged


def _merge_projects(projects: List[Project]) -> Project:
    """Deep-merge projects in order (for multi-file `docker compose -f`)."""
    merged_services: Dict[str, Service] = {}
    for proj in projects:
        for svc_name, svc in proj.services.items():
            if svc_name not in merged_services:
                merged_services[svc_name] = svc
            else:
                existing = merged_services[svc_name]
                # Env dicts: later overrides earlier
                merged_env: Dict[str, Optional[str]] = dict(existing.environment)
                merged_env.update(svc.environment)
                # Volumes: appended/unioned, deduplicated by (source,target,type,ro) preserving order
                combined = list(existing.volumes) + list(svc.volumes)
                seen: set = set()
                deduped: List[Volume] = []
                for v in combined:
                    key = (v.source, v.target, v.type, v.read_only)
                    if key not in seen:
                        seen.add(key)
                        deduped.append(v)
                merged_services[svc_name] = Service(
                    name=svc_name, environment=merged_env, volumes=deduped
                )
    return Project(services=merged_services)


def parse_compose_file(
    compose_path: Union[Path, str, List[Union[Path, str]]],
    env_path: Optional[Union[Path, str]] = None,
) -> Project:
    """Parse a docker-compose file and optional .env into a normalized Project.

    compose_path: path to docker-compose.yml, or list of paths for
        ``docker compose -f file1 -f file2`` style merging.
    env_path: path to .env file. If None, looks for .env next to compose file.

    Priority 1 in this update: per-service ``env_file`` (string or list) is
    loaded via ``load_env_file`` and merged into the service's environment,
    with explicit ``environment:`` keys overriding ``env_file:`` keys (Docker spec).

    Priority 2: when ``compose_path`` is a list, files are parsed sequentially
    and deep-merged: env dicts updated, volume lists appended/unioned.
    """
    # --- Multi-file merging (priority 2) ---
    if isinstance(compose_path, list):
        # Parse each file independently (respects per-file .env / env_file)
        # If env_path is explicitly given, pass it through to each file;
        # otherwise each file uses its own adjacent .env.
        projects: List[Project] = []
        for p in compose_path:
            projects.append(parse_compose_file(p, env_path))
        return _merge_projects(projects)

    compose_path = Path(compose_path)
    if not compose_path.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_path}")

    data = _load_yaml(compose_path)

    # Resolve env_path default: .env next to compose file
    if env_path is None:
        candidate = compose_path.parent / ".env"
        env_path = candidate if candidate.exists() else None
    else:
        env_path = Path(env_path)  # type: ignore[arg-type]

    env_vars = load_env_file(env_path) if env_path else {}  # type: ignore[arg-type]

    services_raw = data.get("services", {})
    if services_raw is None:
        services_raw = {}
    if not isinstance(services_raw, dict):
        raise ValueError(f"'services' must be a mapping, got {type(services_raw)}")

    services: Dict[str, Service] = {}
    for svc_name, svc_data in services_raw.items():
        if svc_data is None:
            svc_data = {}
        if not isinstance(svc_data, dict):
            raise ValueError(f"Service {svc_name} must be a mapping")

        raw_env = svc_data.get("environment")
        raw_env_file = svc_data.get("env_file")
        raw_volumes = svc_data.get("volumes")

        # Priority 1: load env_file (string or list) and merge; explicit env overrides
        env_from_files = _load_service_env_files(raw_env_file, compose_path.parent)
        env_explicit = normalize_environment(raw_env, env_vars)
        # env_file as base, explicit environment wins (Docker spec)
        merged_env: Dict[str, Optional[str]] = dict(env_from_files)  # type: ignore[assignment]
        merged_env.update(env_explicit)
        env = merged_env
        volumes = normalize_volumes(raw_volumes, env_vars)

        services[str(svc_name)] = Service(
            name=str(svc_name),
            environment=env,
            volumes=volumes,
        )

    return Project(services=services)


# Backward-compatible alias
parse_project = parse_compose_file


def parse_compose_string(
    yaml_content: str,
    env_vars: Optional[Dict[str, str]] = None,
) -> Project:
    """Parse compose YAML from string (useful for tests) with optional env_vars dict."""
    if env_vars is None:
        env_vars = {}
    data = yaml.safe_load(yaml_content) or {}
    services_raw = data.get("services", {}) or {}
    services: Dict[str, Service] = {}
    for svc_name, svc_data in services_raw.items():
        if svc_data is None:
            svc_data = {}
        raw_env = svc_data.get("environment")
        raw_volumes = svc_data.get("volumes")
        env = normalize_environment(raw_env, env_vars)
        volumes = normalize_volumes(raw_volumes, env_vars)
        services[str(svc_name)] = Service(name=str(svc_name), environment=env, volumes=volumes)
    return Project(services=services)
