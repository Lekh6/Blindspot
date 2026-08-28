"""BlindSpot — Hidden Dependency Discovery (Stage 2: Parse + Normalize + Candidate Discovery)."""

from .discovery import Candidate, discover_candidates
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
    "Candidate",
    "Project",
    "Service",
    "Volume",
    "discover_candidates",
    "load_env_file",
    "normalize_environment",
    "normalize_volume",
    "normalize_volumes",
    "parse_compose_file",
    "parse_project",
]
