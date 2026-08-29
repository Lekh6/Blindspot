"""BlindSpot — Hidden Dependency Discovery (Stages 1-4, hybrid)."""

from .discovery import Candidate, discover_candidates
from .filtering import (
    EvidencePackage,
    build_evidence_package,
    build_evidence_packages,
    filter_and_build_evidence,
    filter_candidates,
    filter_with_reasons,
)
from .judge import (
    JudgeResult,
    MockJudgeClient,
    FixedJudgeClient,
    build_judge_prompt,
    judge_evidence_package,
    judge_evidence_packages,
)
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
    "EvidencePackage",
    "JudgeResult",
    "Project",
    "Service",
    "Volume",
    "MockJudgeClient",
    "FixedJudgeClient",
    "build_evidence_package",
    "build_evidence_packages",
    "build_judge_prompt",
    "discover_candidates",
    "filter_and_build_evidence",
    "filter_candidates",
    "filter_with_reasons",
    "judge_evidence_package",
    "judge_evidence_packages",
    "load_env_file",
    "normalize_environment",
    "normalize_volume",
    "normalize_volumes",
    "parse_compose_file",
    "parse_project",
]
