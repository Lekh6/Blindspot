"""
BlindSpot Stage 3: Candidate Filtering — Deterministic Filtering + Bounded Evidence Construction

Implements hybrid deterministic + LLM approach per updated AGENTS.md §3:

- Deterministic filtering: eliminate/deprioritize obvious coincidences before LLM.
- Bounded evidence construction: for each surviving candidate, build one compact
  evidence package with deterministically resolved context (service/image/internal-external,
  named-volume identity, related config, filtering signals).

Input: List[Candidate] from discovery + Project for resolution context
Output: List[Candidate] filtered (kept) with enriched evidence + bounded EvidencePackage per survivor

Cost model: obvious/common coincidence → 0 LLM calls, interesting candidate → 1 LLM call (via evidence package).
"""

from __future__ import annotations

from dataclasses import dataclass, replace, field, asdict
from typing import List, Tuple, Dict, Optional, Any

from .discovery import Candidate

# Forward import for type hints (avoid circular at runtime we import under TYPE_CHECKING)
try:
    from .parser import Project  # type: ignore
except Exception:  # pragma: no cover
    Project = Any  # type: ignore

# Generic environment keys that are often coincidental when shared.
# Conservative list: standard ports, debug flags, logging, plus
# generic fixture noise. Do NOT include DB_HOST/DB_NAME/shared-data.
GENERIC_ENV_KEYS = {
    "PORT",
    "HOST",
    "HOSTNAME",
    "DEBUG",
    "LOG_LEVEL",
    "LOGLEVEL",
    "LOGGING_LEVEL",
    "LOGGING",
    "NODE_ENV",
    "ENV",
    "ENVIRONMENT",
    "APP_ENV",
    "PYTHON_ENV",
    "RAILS_ENV",
    "TZ",
    "LANG",
    "DATA_PATH",
    "SHARED_EXTRA",
    "SHARED_NOISE",
    "VERBOSE",
    "QUIET",
    "CI",
}


def _is_generic_key(key: str) -> bool:
    return key.upper() in GENERIC_ENV_KEYS


# ---------------------------------------------------------------------------
# Bounded Evidence Package (§4 of mod spec)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidencePackage:
    """One compact, bounded evidence package per surviving candidate.

    Required:
      service_a, service_b, resource, resource_type, value, evidence (base)
    Deterministically resolved context:
      resolved_service, resolved_image, is_internal, reference_type, volume info
    Small relevant surrounding config:
      related_config {service -> {key: value}}
    Filtering signals:
      generic_variable, same_value, resolved_reference
    Provenance (best-effort, may be None if parser did not preserve):
      interpolation_source, env_file_origin
    """

    service_a: str
    service_b: str
    resource: str
    resource_type: str  # "env_var" | "named_volume"
    value: Optional[str]
    evidence: str  # base evidence from discovery

    # Resolved context
    resolved_service: Optional[str] = None  # e.g. "postgres" if value resolves to compose service
    resolved_image: Optional[str] = None  # e.g. "postgres:16"
    is_internal: Optional[bool] = None  # True if compose_service/named_volume, False if external, None unknown
    reference_type: str = "unknown"  # "compose_service" | "named_volume" | "external" | "unknown"

    # Small relevant surrounding configuration (bounded, sorted, max 5 per service)
    related_config: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict)

    # Filtering signals
    generic_variable: bool = False
    same_value: bool = False
    different_values: bool = False

    # Volume-specific (for named_volume)
    volume_targets: Optional[Dict[str, str]] = None  # {service -> target}

    # Provenance (best-effort; parser will preserve more in future)
    interpolation_source: Optional[str] = None  # e.g. "${DB_HOST}" origin
    env_file_origin: Optional[str] = None  # e.g. "common.env" origin

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "evidence": self.evidence,
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
            "is_internal": self.is_internal,
            "reference_type": self.reference_type,
            "related_config": {k: dict(v) for k, v in self.related_config.items()},
            "filtering_signals": {
                "generic_variable": self.generic_variable,
                "same_value": self.same_value,
                "different_values": self.different_values,
                "resolved_reference": self.reference_type,
            },
            "volume_targets": dict(self.volume_targets) if self.volume_targets else None,
        }

    def cache_key_dict(self) -> Dict[str, Any]:
        """Deterministic dict used for cache.json key generation — candidate + relevant evidence."""
        # Include all fields that change meaning if evidence changes materially
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
            "is_internal": self.is_internal,
            "reference_type": self.reference_type,
            "related_config": {k: dict(sorted(v.items())) for k, v in sorted(self.related_config.items())},
            "generic_variable": self.generic_variable,
            "same_value": self.same_value,
        }


def _is_host_like_resource(resource: str) -> bool:
    """Values of HOST/URL/ADDRESS-like keys can plausibly resolve to a Compose service."""
    upper = resource.upper()
    return any(k in upper for k in ("HOST", "URL", "ADDRESS", "ENDPOINT", "SERVER", "BROKER"))

def _resolve_candidate(candidate: Candidate, project: Any) -> Tuple[Optional[str], Optional[str], Optional[bool], str, Optional[Dict[str, str]]]:
    """Resolve what candidate value/resource points to using Project deterministically.

    Returns: (resolved_service, resolved_image, is_internal, reference_type, volume_targets)
    No LLM calls — pure static analysis.
    """
    if candidate.resource_type == "named_volume":
        # Named volume is internal by definition (shared named volume identity)
        # Collect targets for evidence completeness
        targets: Dict[str, str] = {}
        for svc_name in [candidate.service_a, candidate.service_b]:
            svc = project.services.get(svc_name) if project else None
            if svc:
                for vol in svc.volumes:
                    if vol.type == "named" and vol.source == candidate.resource:
                        targets[svc_name] = vol.target
                        break
        return None, None, True, "named_volume", targets if targets else None

    # env_var
    if candidate.value is None:
        # No shared value to resolve (different values or both None)
        return None, None, None, "unknown", None

    # Only HOST/URL-like resources plausibly point to a service; DB_NAME etc. should not
    # auto-resolve to an app service name (e.g. DB_NAME=orders → orders service is not a DB host)
    if not _is_host_like_resource(candidate.resource):
        return None, None, False, "external", None

    # Try direct service name match
    if project and candidate.value in project.services:
        svc = project.services[candidate.value]
        return candidate.value, svc.image, True, "compose_service", None

    # Handle value that looks like "host:port" or "host/db" — try prefix before : or /
    base = candidate.value.split(":")[0].split("/")[0].strip()
    if base and project and base in project.services:
        svc = project.services[base]
        return base, svc.image, True, "compose_service", None

    # Not an internal compose service → external/unknown (e.g. external DB host, cloud URL)
    return None, None, False, "external", None


def _collect_related_config(candidate: Candidate, project: Any, max_per_service: int = 5) -> Dict[str, Dict[str, Optional[str]]]:
    """Collect small relevant surrounding config — only directly relevant to candidate.

    For DB candidate (resource=DB_HOST), include DB_HOST/DB_NAME/DB_PORT etc.
    Do not send unrelated PORT/DEBUG/LOG_LEVEL/TZ/SECRET_KEY.
    Bounded to max_per_service entries, deterministically sorted.
    """
    if project is None:
        return {}
    if candidate.resource_type != "env_var":
        return {}

    # Determine prefix for grouping — e.g. DB_HOST -> DB
    if "_" in candidate.resource:
        prefix = candidate.resource.split("_")[0]
    else:
        prefix = candidate.resource

    related: Dict[str, Dict[str, Optional[str]]] = {}
    for svc_name in [candidate.service_a, candidate.service_b]:
        svc = project.services.get(svc_name)
        if not svc:
            continue
        # Include vars that share prefix or equal resource
        candidates = {
            k: v
            for k, v in svc.environment.items()
            if k == candidate.resource or k.startswith(prefix + "_")
        }
        # Bound and sort for determinism
        if len(candidates) > max_per_service:
            keys = sorted(candidates.keys())[:max_per_service]
            candidates = {k: candidates[k] for k in keys}
        else:
            candidates = dict(sorted(candidates.items()))
        related[svc_name] = candidates
    return related


def build_evidence_package(candidate: Candidate, project: Any) -> EvidencePackage:
    """Build one bounded evidence package for a surviving candidate.

    Deterministically resolves what the value points to, collects related config,
    and captures filtering signals. No LLM calls.
    """
    resolved_service, resolved_image, is_internal, reference_type, volume_targets = _resolve_candidate(candidate, project)
    related_config = _collect_related_config(candidate, project)
    generic = _is_generic_key(candidate.resource) if candidate.resource_type == "env_var" else False
    same = candidate.value is not None
    diff = "different values" in candidate.evidence

    return EvidencePackage(
        service_a=candidate.service_a,
        service_b=candidate.service_b,
        resource=candidate.resource,
        resource_type=candidate.resource_type,
        value=candidate.value,
        evidence=candidate.evidence,
        resolved_service=resolved_service,
        resolved_image=resolved_image,
        is_internal=is_internal,
        reference_type=reference_type,
        related_config=related_config,
        generic_variable=generic,
        same_value=same,
        different_values=diff,
        volume_targets=volume_targets,
    )


def build_evidence_packages(candidates: List[Candidate], project: Any) -> List[EvidencePackage]:
    """Filter candidates then build bounded evidence packages for survivors.

    This is the Stage 3 combined entry point: deterministic filtering + evidence construction.
    Returns evidence packages sorted deterministically (same key as discovery).
    """
    kept = filter_candidates(candidates)
    packages = [build_evidence_package(c, project) for c in kept]
    packages.sort(key=lambda p: (p.service_a, p.service_b, p.resource_type, p.resource))
    return packages


def filter_and_build_evidence(candidates: List[Candidate], project: Any) -> Tuple[List[Candidate], List[EvidencePackage]]:
    """Convenience: return both kept candidates (with enriched evidence) and packages.

    Useful for callers that need candidate list for filtering metrics and packages for LLM judge.
    """
    kept = filter_candidates(candidates)
    packages = [build_evidence_package(c, project) for c in kept]
    packages.sort(key=lambda p: (p.service_a, p.service_b, p.resource_type, p.resource))
    return kept, packages


# ---------------------------------------------------------------------------
# Original filtering (unchanged behavior, preserved for backward compatibility)
# ---------------------------------------------------------------------------

def filter_candidates(candidates: List[Candidate]) -> List[Candidate]:
    """Filter candidates, keeping only likely-meaningful couplings.

    Rules (conservative, deterministic):
    - env_var with same key but different values (value is None + evidence notes
      different values) → drop (coincidence, not shared config)
    - env_var where resource is generic (PORT/DEBUG/LOG_LEVEL etc) → drop
    - named_volume → keep (shared named volumes are strong coupling signal)
    Remaining candidates get enriched evidence with filter reason.
    """
    kept: List[Candidate] = []
    for cand in candidates:
        keep, reason = _decide(cand)
        if keep:
            # Enrich evidence for LLM with filtering rationale
            enriched = f"{cand.evidence} | filter: kept — {reason}"
            kept.append(replace(cand, evidence=enriched))
        # else dropped — not returned (deprioritized)
    # Deterministic ordering (same as discovery)
    kept.sort(key=lambda c: (c.service_a, c.service_b, c.resource_type, c.resource))
    return kept


def filter_with_reasons(candidates: List[Candidate]) -> List[Tuple[Candidate, bool, str]]:
    """Return all candidates annotated with (kept, reason) for reporting/testing."""
    result: List[Tuple[Candidate, bool, str]] = []
    for cand in candidates:
        keep, reason = _decide(cand)
        result.append((cand, keep, reason))
    result.sort(key=lambda t: (t[0].service_a, t[0].service_b, t[0].resource_type, t[0].resource))
    return result


def _decide(cand: Candidate) -> Tuple[bool, str]:
    # Volumes: keep all named volumes (strong signal)
    if cand.resource_type == "named_volume":
        return True, "shared named volume — likely coupling"

    # Env vars
    if cand.resource_type == "env_var":
        # Different values for same key → coincidence, not shared config
        if cand.value is None and "different values" in cand.evidence:
            return False, f"same key {cand.resource!r} with different values — likely coincidence (e.g. PORT)"

        # Generic keys → likely coincidence
        if _is_generic_key(cand.resource):
            # If value is None (mismatched) already handled, but generic with same value also filtered
            return False, f"generic key {cand.resource!r} — standard port/debug/logging/generic noise"

        # Otherwise keep (e.g. DB_HOST, DB_NAME)
        if cand.value is not None:
            return True, f"shared {cand.resource}={cand.value!r} — specific config, likely coupling"
        else:
            # Same key, both None (rare) — keep as possible coupling but weak
            return True, f"shared key {cand.resource!r} with no value — possible coupling, needs LLM"

    # Unknown type → keep conservatively
    return True, "unknown resource_type — kept conservatively"
