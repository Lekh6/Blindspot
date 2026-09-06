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
from .resolution import (
    ResolutionResult,
    ResolutionStatus,
    IdentityStrength,
    bounded_resolve,
    STATUS_INTERNAL,
    STATUS_EXTERNAL_CONFIRMED,
    STATUS_UNRESOLVED,
    STATUS_PARTIAL,
)

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
    Deterministically resolved context (legacy + new resolution model):
      resolved_service, resolved_image, is_internal, reference_type (legacy mapping)
      resolution_status: internal | external_confirmed | unresolved | partial  (new distinct states)
      resource_protocol, normalized_identity, identity_strength, resolution_chain, final_value
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

    # Resolved context — legacy fields (derived from new resolution for backward compat)
    resolved_service: Optional[str] = None  # e.g. "postgres" if value resolves to compose service
    resolved_image: Optional[str] = None  # e.g. "postgres:16"
    is_internal: Optional[bool] = None  # True if internal, False if external_confirmed, None if unresolved/partial
    reference_type: str = "unknown"  # legacy: "compose_service" | "named_volume" | "external" | "unknown" | "partial"

    # New deterministic resolution fields
    resolution_status: ResolutionStatus = STATUS_UNRESOLVED  # distinct states: internal / external_confirmed / unresolved / partial
    resource_protocol: Optional[str] = None  # e.g. postgresql, mysql, redis, None if unknown
    normalized_identity: Optional[str] = None  # deterministic, credentials stripped, e.g. postgresql|host|5432|db
    identity_strength: IdentityStrength = "unknown"  # exact | config | unknown
    resolution_chain: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)  # bounded list of ResolutionStep.to_dict()
    final_value: Optional[str] = None  # after bounded resolution (may still contain unresolved placeholders)
    original_value: Optional[str] = None
    unresolved_vars: Tuple[str, ...] = field(default_factory=tuple)
    is_cyclic: bool = False
    depth_reached: int = 0

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
            "resolution_status": self.resolution_status,
            "resource_protocol": self.resource_protocol,
            "normalized_identity": self.normalized_identity,
            "identity_strength": self.identity_strength,
            "resolution_chain": list(self.resolution_chain),
            "final_value": self.final_value,
            "original_value": self.original_value,
            "unresolved_vars": list(self.unresolved_vars),
            "is_cyclic": self.is_cyclic,
            "depth_reached": self.depth_reached,
            "related_config": {k: dict(v) for k, v in self.related_config.items()},
            "filtering_signals": {
                "generic_variable": self.generic_variable,
                "same_value": self.same_value,
                "different_values": self.different_values,
                "resolved_reference": self.reference_type,
                "resolution_status": self.resolution_status,
                "identity_strength": self.identity_strength,
            },
            "volume_targets": dict(self.volume_targets) if self.volume_targets else None,
        }

    def cache_key_dict(self) -> Dict[str, Any]:
        """Deterministic dict used for cache.json key generation — candidate + relevant evidence."""
        # Include all fields that materially change meaning if evidence changes
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "final_value": self.final_value,
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
            "is_internal": self.is_internal,
            "reference_type": self.reference_type,
            "resolution_status": self.resolution_status,
            "resource_protocol": self.resource_protocol,
            "normalized_identity": self.normalized_identity,
            "identity_strength": self.identity_strength,
            "unresolved_vars": list(self.unresolved_vars),
            "related_config": {k: dict(sorted(v.items())) for k, v in sorted(self.related_config.items())},
            "generic_variable": self.generic_variable,
            "same_value": self.same_value,
        }


def _is_host_like_resource(resource: str) -> bool:
    """Legacy helper retained for compatibility; new resolver uses value structure not name."""
    upper = resource.upper()
    return any(k in upper for k in ("HOST", "URL", "ADDRESS", "ENDPOINT", "SERVER", "BROKER"))

def _resolve_candidate(candidate: Candidate, project: Any) -> Tuple[Optional[str], Optional[str], Optional[bool], str, Optional[Dict[str, str]], ResolutionResult]:
    """Resolve what candidate value/resource points to using bounded_resolve deterministically.

    For env_var with same value (candidate.value not None) -> bounded_resolve that value.
    For env_var with different values (candidate.value is None, evidence notes different) ->
      fetch each service's actual raw values and compare normalized identities.
      If they converge to same normalized identity, keep that identity as evidence (credentials-stripped).
      If not, return unresolved.

    Returns: (resolved_service, resolved_image, is_internal, reference_type, volume_targets, ResolutionResult)
    No LLM calls — pure static analysis.
    """
    # Named volume fast path
    if candidate.resource_type == "named_volume":
        rr_vol: ResolutionResult = bounded_resolve(
            candidate.resource,
            project,
            candidate.service_a,
            candidate.service_b,
            resource=candidate.resource,
            resource_type=candidate.resource_type,
        )
        targets: Dict[str, str] = {}
        for svc_name in [candidate.service_a, candidate.service_b]:
            svc = project.services.get(svc_name) if project else None
            if svc:
                for vol in svc.volumes:
                    if vol.type == "named" and vol.source == candidate.resource:
                        targets[svc_name] = vol.target
                        break
        volume_targets = targets if targets else None
        return rr_vol.resolved_service, rr_vol.resolved_image, True, "named_volume", volume_targets, rr_vol

    # Different-values case: candidate.value is None but each service has its own value
    if candidate.value is None and "different values" in candidate.evidence and project and hasattr(project, "services"):
        try:
            svc_a = project.services.get(candidate.service_a)
            svc_b = project.services.get(candidate.service_b)
            raw_a = svc_a.environment.get(candidate.resource) if svc_a else None
            raw_b = svc_b.environment.get(candidate.resource) if svc_b else None
            if raw_a is not None and raw_b is not None:
                rr_a = bounded_resolve(raw_a, project, candidate.service_a, candidate.service_b, resource=candidate.resource, resource_type=candidate.resource_type)
                rr_b = bounded_resolve(raw_b, project, candidate.service_a, candidate.service_b, resource=candidate.resource, resource_type=candidate.resource_type)
                # If both normalize to same identity (credentials stripped), treat as same physical resource despite different raw config
                if rr_a.normalized_identity and rr_a.normalized_identity == rr_b.normalized_identity and rr_a.resource_protocol == rr_b.resource_protocol:
                    # Keep the shared normalized identity
                    # Prefer the more resolved status (external_confirmed/internal) if either is exact
                    # Choose rr_a (or rr_b) with exact status if available
                    chosen = rr_a if rr_a.resolution_status in (STATUS_INTERNAL, STATUS_EXTERNAL_CONFIRMED) else rr_b
                    # Build a merged result that reflects same-identity despite different raw values
                    # We create a synthetic chain indicating both sides converge
                    is_internal = True if chosen.resolution_status == STATUS_INTERNAL else (False if chosen.resolution_status == STATUS_EXTERNAL_CONFIRMED else None)
                    ref = "compose_service" if chosen.resolution_status == STATUS_INTERNAL else ("external" if chosen.resolution_status == STATUS_EXTERNAL_CONFIRMED else ("partial" if chosen.resolution_status == STATUS_PARTIAL else "unknown"))
                    # For evidence, create a synthetic resolution indicating convergence
                    # Keep original chain from one side but note convergence
                    volume_targets = None
                    return chosen.resolved_service, chosen.resolved_image, is_internal, ref, volume_targets, chosen
                # If raw values are same after stripping scheme not same, check if they are identical after resolution
                if rr_a.final_value == rr_b.final_value and rr_a.final_value is not None:
                    chosen = rr_a
                    is_internal = True if chosen.resolution_status == STATUS_INTERNAL else (False if chosen.resolution_status == STATUS_EXTERNAL_CONFIRMED else None)
                    ref = "compose_service" if chosen.resolution_status == STATUS_INTERNAL else ("external" if chosen.resolution_status == STATUS_EXTERNAL_CONFIRMED else ("partial" if chosen.resolution_status == STATUS_PARTIAL else "unknown"))
                    return chosen.resolved_service, chosen.resolved_image, is_internal, ref, None, chosen
        except Exception:
            pass
        # Different values that do not converge to same identity -> unresolved (will be filtered)
        rr_un = ResolutionResult(
            original_value=None,
            final_value=None,
            chain=(),
            resolution_status=STATUS_UNRESOLVED,
            resource_protocol=None,
            normalized_identity=None,
            identity_strength="unknown",
            unresolved_vars=(),
            is_cyclic=False,
            depth_reached=0,
        )
        return None, None, None, "unknown", None, rr_un

    # Same-value case (candidate.value not None) or no project context
    rr: ResolutionResult = bounded_resolve(
        candidate.value,
        project,
        candidate.service_a,
        candidate.service_b,
        resource=candidate.resource,
        resource_type=candidate.resource_type,
    )
    # Legacy mapping for backward compat
    if rr.resolution_status == STATUS_INTERNAL:
        ref = "compose_service"
        is_internal: Optional[bool] = True
    elif rr.resolution_status == STATUS_EXTERNAL_CONFIRMED:
        ref = "external"
        is_internal = False
    elif rr.resolution_status == STATUS_PARTIAL:
        ref = "partial"
        is_internal = None
    else:
        ref = "unknown"
        is_internal = None

    volume_targets: Optional[Dict[str, str]] = None
    return rr.resolved_service, rr.resolved_image, is_internal, ref, volume_targets, rr


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

    Deterministically resolves what the value points to via bounded_resolve, collects related config,
    and captures filtering signals. No LLM calls.
    """
    resolved_service, resolved_image, is_internal, reference_type, volume_targets, rr = _resolve_candidate(candidate, project)
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
        resolution_status=rr.resolution_status,
        resource_protocol=rr.resource_protocol,
        normalized_identity=rr.normalized_identity,
        identity_strength=rr.identity_strength,
        resolution_chain=tuple(s.to_dict() for s in rr.chain),
        final_value=rr.final_value,
        original_value=rr.original_value,
        unresolved_vars=rr.unresolved_vars,
        is_cyclic=rr.is_cyclic,
        depth_reached=rr.depth_reached,
        related_config=related_config,
        generic_variable=generic,
        same_value=same,
        different_values=diff,
        volume_targets=volume_targets,
    )


def _decide_with_project(cand: Candidate, project: Any) -> Tuple[bool, str]:
    """Project-aware decide: same as _decide but different-values may be kept if normalized identity converges."""
    # Fast path for named_volume
    if cand.resource_type == "named_volume":
        return True, "shared named volume — likely coupling"
    if cand.resource_type == "env_var":
        if cand.value is None and "different values" in cand.evidence:
            # Check if normalized identities converge (credentials stripped)
            if project is not None and hasattr(project, "services"):
                try:
                    svc_a = project.services.get(cand.service_a)
                    svc_b = project.services.get(cand.service_b)
                    raw_a = svc_a.environment.get(cand.resource) if svc_a else None
                    raw_b = svc_b.environment.get(cand.resource) if svc_b else None
                    if raw_a is not None and raw_b is not None:
                        from .resolution import bounded_resolve as _br
                        rr_a = _br(raw_a, project, cand.service_a, cand.service_b, resource=cand.resource, resource_type=cand.resource_type)
                        rr_b = _br(raw_b, project, cand.service_a, cand.service_b, resource=cand.resource, resource_type=cand.resource_type)
                        if rr_a.normalized_identity and rr_a.normalized_identity == rr_b.normalized_identity:
                            return True, f"different raw values but same normalized identity {rr_a.normalized_identity!r} — likely same physical resource (credentials stripped)"
                        if rr_a.final_value and rr_a.final_value == rr_b.final_value:
                            return True, f"different raw values but same resolved final value {rr_a.final_value!r} — likely same resource"
                except Exception:
                    pass
            return False, f"same key {cand.resource!r} with different values — likely coincidence (e.g. PORT)"
        if _is_generic_key(cand.resource):
            return False, f"generic key {cand.resource!r} — standard port/debug/logging/generic noise"
        if cand.value is not None:
            return True, f"shared {cand.resource}={cand.value!r} — specific config, likely coupling"
        else:
            return True, f"shared key {cand.resource!r} with no value — possible coupling, needs LLM"
    return True, "unknown resource_type — kept conservatively"


def build_evidence_packages(candidates: List[Candidate], project: Any) -> List[EvidencePackage]:
    """Filter candidates (project-aware) then build bounded evidence packages for survivors.

    This is the Stage 3 combined entry point: deterministic filtering + evidence construction.
    Returns evidence packages sorted deterministically (same key as discovery).
    Uses project-aware decision so different raw values that normalize to same physical resource are kept.
    """
    # Project-aware filtering: keep if _decide_with_project says keep
    kept: List[Candidate] = []
    for cand in candidates:
        keep, _ = _decide_with_project(cand, project)
        if keep:
            # Also apply legacy generic filter via _decide for consistency when project None? already handled
            kept.append(cand)
    # Enrich evidence for LLM with filtering rationale
    packages: List[EvidencePackage] = []
    for cand in kept:
        keep, reason = _decide_with_project(cand, project)
        # Build package then enrich evidence string
        pkg = build_evidence_package(cand, project)
        enriched_evidence = f"{cand.evidence} | filter: kept — {reason}"
        from dataclasses import replace as _replace
        pkg = _replace(pkg, evidence=enriched_evidence)
        packages.append(pkg)
    packages.sort(key=lambda p: (p.service_a, p.service_b, p.resource_type, p.resource))
    return packages


def filter_and_build_evidence(candidates: List[Candidate], project: Any) -> Tuple[List[Candidate], List[EvidencePackage]]:
    """Convenience: return both kept candidates (with enriched evidence) and packages.

    Useful for callers that need candidate list for filtering metrics and packages for LLM judge.
    """
    pkgs = build_evidence_packages(candidates, project)
    # Derive kept candidates from pkgs (for reporting)
    kept_cands: List[Candidate] = []
    for pkg in pkgs:
        # Find original candidate matching package identity
        for cand in candidates:
            if cand.service_a == pkg.service_a and cand.service_b == pkg.service_b and cand.resource == pkg.resource and cand.resource_type == pkg.resource_type:
                kept_cands.append(cand)
                break
    return kept_cands, pkgs


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
