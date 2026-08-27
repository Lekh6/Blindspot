"""BlindSpot — Hidden Dependency Discovery (Stage 2: Parse + Normalize)."""

from .parser import (
    Project,
    Service,
    Volume,
    load_env_file,
    normalize_environment,
    normalize_volume,
    normalize_volumes,
    parse_compose_file,
    parse_project,
)

__all__ = [
    "Project",
    "Service",
    "Volume",
    "load_env_file",
    "normalize_environment",
    "normalize_volume",
    "normalize_volumes",
    "parse_compose_file",
    "parse_project",
]
