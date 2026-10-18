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
from .secrets import redact_value_for_key, redact_mapping, redact_url_credentials, REDACTED

# Evidence schema version — bump on any material structure/meaning change.
# Cache keys include this so old entries invalidate automatically.
EVIDENCE_SCHEMA_VERSION = "2"

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


def _is_secret_value(key: str, val: str) -> bool:
    """True when a free-text occurrence must be scrubbed (secret key or URL creds)."""
    try:
        from .secrets import is_secret_key as _iss

        if _iss(key):
            return True
    except Exception:
        pass
    # URL-embedded credentials always scrubbed regardless of key name.
    return "@" in val and "://" in val


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

    # Stage 3+4 contract additions (backward-compatible defaults):
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    candidate_id: str = ""  # stable Stage-2 candidate ID, preserved through pipeline
    raw_value: Optional[str] = None  # raw configured value before resolution (may equal value)
    provenance: Optional[str] = None  # originating Compose file label (best-effort)
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)  # stable refs LLM can cite
    missing_info: Tuple[str, ...] = field(default_factory=tuple)  # explicit uncertainty list
    filter_rule: str = ""  # deterministic rule that kept this candidate
    filter_reason: str = ""  # human-readable keep reason

    def _redacted_chain(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for step in self.resolution_chain:
            if isinstance(step, dict):
                s = dict(step)
                # Redact from/to values that may embed credentials.
                if isinstance(s.get("from_value"), str):
                    s["from_value"] = redact_url_credentials(s["from_value"])
                if isinstance(s.get("to_value"), str):
                    s["to_value"] = redact_url_credentials(s["to_value"])
                out.append(s)
            else:
                out.append(step)  # type: ignore
        # Scrub plain secret values when this package's resource is secret-keyed.
        try:
            from .secrets import is_secret_key as _iss

            if _iss(self.resource):
                for secret_val in (self.value, self.raw_value, self.final_value, self.original_value):
                    if secret_val and isinstance(secret_val, str) and len(secret_val) >= 4:
                        for s in out:
                            for k in ("from_value", "to_value"):
                                if isinstance(s.get(k), str) and secret_val in s[k]:
                                    s[k] = s[k].replace(secret_val, REDACTED)
        except Exception:
            pass
        return out

    def to_dict(self) -> Dict[str, Any]:
        """Secret-safe serialization (default for reports/cache/prompts).

        Secret-keyed values are redacted; URL userinfo is stripped.
        Free-text evidence/reason strings are also scrubbed of credentials.
        Raw in-memory values are never serialized verbatim when sensitive.
        Deterministic key order is enforced by callers via sort_keys.
        """
        red_evidence = redact_url_credentials(self.evidence) or ""
        red_reason = redact_url_credentials(self.filter_reason) or ""
        # Scrub whole secret values that appear inside free text.
        for key, val in ((self.resource, self.value), (self.resource, self.raw_value)):
            if val and isinstance(val, str) and len(val) >= 4:
                if key and val in red_evidence and _is_secret_value(key, val):
                    red_evidence = red_evidence.replace(val, REDACTED)
                if key and val in red_reason and _is_secret_value(key, val):
                    red_reason = red_reason.replace(val, REDACTED)
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": redact_value_for_key(self.resource, self.value),
            "raw_value": redact_value_for_key(self.resource, self.raw_value),
            "evidence": red_evidence,
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
            "is_internal": self.is_internal,
            "reference_type": self.reference_type,
            "resolution_status": self.resolution_status,
            "resource_protocol": self.resource_protocol,
            "normalized_identity": self.normalized_identity,
            "identity_strength": self.identity_strength,
            "resolution_chain": self._redacted_chain(),
            "final_value": redact_value_for_key(self.resource, redact_url_credentials(self.final_value)),
            "original_value": redact_value_for_key(self.resource, redact_url_credentials(self.original_value)),
            "unresolved_vars": list(self.unresolved_vars),
            "is_cyclic": self.is_cyclic,
            "depth_reached": self.depth_reached,
            "related_config": {
                k: redact_mapping(v) for k, v in sorted(self.related_config.items())
            },
            "filtering_signals": {
                "generic_variable": self.generic_variable,
                "same_value": self.same_value,
                "different_values": self.different_values,
                "resolved_reference": self.reference_type,
                "resolution_status": self.resolution_status,
                "identity_strength": self.identity_strength,
            },
            "volume_targets": dict(self.volume_targets) if self.volume_targets else None,
            "provenance": self.provenance,
            "evidence_refs": list(self.evidence_refs),
            "missing_info": list(self.missing_info),
            "filter_rule": self.filter_rule,
            "filter_reason": red_reason,
        }

    def to_canonical_json(self) -> str:
        """Deterministic JSON independent of iteration order/timestamps."""
        import json as _json

        return _json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def cache_key_dict(self) -> Dict[str, Any]:
        """Deterministic dict used for cache.json key generation — candidate + relevant evidence.

        Secret-safe: uses redacted values so cache keys never contain secrets.
        Includes schema_version so structure changes invalidate entries.
        """
        # Include all fields that materially change meaning if evidence changes
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": redact_value_for_key(self.resource, self.value),
            "final_value": redact_value_for_key(self.resource, redact_url_credentials(self.final_value)),
            "resolved_service": self.resolved_service,
            "resolved_image": self.resolved_image,
            "is_internal": self.is_internal,
            "reference_type": self.reference_type,
            "resolution_status": self.resolution_status,
            "resource_protocol": self.resource_protocol,
            "normalized_identity": self.normalized_identity,
            "identity_strength": self.identity_strength,
            "unresolved_vars": list(self.unresolved_vars),
            "related_config": {
                k: redact_mapping(dict(sorted(v.items())))
                for k, v in sorted(self.related_config.items())
            },
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
    # L0 explicit dependency fast path (Stage 2): target is a service name, not a value.
    if candidate.resource_type == "service_dependency":
        target = candidate.resource
        svc = (project.services.get(target) if project and hasattr(project, "services") else None)
        if svc is not None:
            rr_dep = ResolutionResult(
                original_value=target,
                final_value=target,
                chain=(),
                resolution_status=STATUS_INTERNAL,
                resource_protocol=None,
                normalized_identity=f"service|{target}",
                identity_strength="exact",
                unresolved_vars=(),
                is_cyclic=False,
                depth_reached=0,
                resolved_service=target,
                resolved_image=getattr(svc, "image", None),
            )
            return target, getattr(svc, "image", None), True, "compose_service", None, rr_dep
        rr_un = ResolutionResult(
            original_value=target,
            final_value=target,
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

    # L1 shared-endpoint fast path (Stage 2): resource is already a normalized identity.
    if candidate.resource_type == "shared_endpoint":
        norm = candidate.resource_identity or candidate.resource or ""
        proto: Optional[str] = None
        host: Optional[str] = None
        if "|" in norm:
            parts = norm.split("|")
            proto = parts[0] or None
            host = parts[1] if len(parts) > 1 else None
        services = getattr(project, "services", {}) if project and hasattr(project, "services") else {}
        resolved_svc: Optional[str] = None
        resolved_img: Optional[str] = None
        if host and host in services:
            resolved_svc = host
            resolved_img = getattr(services[host], "image", None)
            status = STATUS_INTERNAL
            is_int: Optional[bool] = True
            ref = "compose_service"
        elif proto:
            status = STATUS_EXTERNAL_CONFIRMED
            is_int = False
            ref = "external"
        else:
            status = STATUS_UNRESOLVED
            is_int = None
            ref = "unknown"
        rr_ep = ResolutionResult(
            original_value=candidate.value,
            final_value=candidate.value,
            chain=(),
            resolution_status=status,
            resource_protocol=proto,
            normalized_identity=norm or None,
            identity_strength="exact" if norm else "unknown",
            unresolved_vars=(),
            is_cyclic=False,
            depth_reached=0,
            resolved_service=resolved_svc,
            resolved_image=resolved_img,
        )
        return resolved_svc, resolved_img, is_int, ref, None, rr_ep

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
    and captures filtering signals. No LLM calls. No confidence scoring.
    Populates stable candidate_id, provenance, evidence refs, and uncertainty.
    """
    resolved_service, resolved_image, is_internal, reference_type, volume_targets, rr = _resolve_candidate(candidate, project)
    related_config = _collect_related_config(candidate, project)
    generic = _is_generic_key(candidate.resource) if candidate.resource_type == "env_var" else False
    same = candidate.value is not None
    diff = "different values" in candidate.evidence

    # Provenance: prefer candidate provenance, else project sources.
    prov = getattr(candidate, "provenance", None)
    if not prov and project is not None and hasattr(project, "sources"):
        try:
            srcs = sorted(project.sources)
            prov = srcs[0] if srcs else None
        except Exception:
            prov = None

    # Stable evidence refs the LLM can cite: candidate + resolution + related.
    base_ref = getattr(candidate, "candidate_id", "") or ""
    refs = []
    if base_ref:
        refs.append(f"candidate:{base_ref}")
    refs.append(f"evidence:{candidate.service_a}/{candidate.service_b}/{candidate.resource_type}/{candidate.resource}")
    if rr.normalized_identity:
        refs.append(f"identity:{rr.normalized_identity}")
    if rr.resolved_service:
        refs.append(f"service:{rr.resolved_service}")

    # Missing info / uncertainty: explicit, never silent.
    missing: List[str] = []
    if rr.unresolved_vars:
        missing.append(f"unresolved vars: {', '.join(sorted(rr.unresolved_vars))}")
    if rr.resolution_status in (STATUS_UNRESOLVED, STATUS_PARTIAL):
        missing.append(f"resolution {rr.resolution_status} (strength {rr.identity_strength})")
    if rr.is_cyclic:
        missing.append("resolution cycle detected")
    if reference_type == "unknown":
        missing.append("reference type unknown")

    keep, reason = _decide_with_project(candidate, project)
    # Derive stable rule id from reason prefix.
    if "explicit depends_on" in reason:
        rule = "keep-explicit-l0"
    elif "shared normalized endpoint" in reason:
        rule = "keep-shared-endpoint"
    elif "named volume" in reason:
        rule = "keep-named-volume"
    elif "same normalized identity" in reason or "same resolved final" in reason:
        rule = "keep-converged-identity"
    elif "specific config" in reason:
        rule = "keep-specific-config"
    else:
        rule = "keep-conservative"

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
        schema_version=EVIDENCE_SCHEMA_VERSION,
        candidate_id=base_ref,
        raw_value=candidate.value,
        provenance=prov,
        evidence_refs=tuple(refs),
        missing_info=tuple(sorted(missing)),
        filter_rule=rule,
        filter_reason=reason,
    )


def _decide_with_project(cand: Candidate, project: Any) -> Tuple[bool, str]:
    """Project-aware decide: same as _decide but different-values may be kept if normalized identity converges."""
    # L0 explicit dependencies are baseline context, never generic noise — always kept.
    if cand.resource_type == "service_dependency":
        return True, f"explicit depends_on {cand.service_a!r}->{cand.resource!r} (L0 baseline, not hidden coupling)"
    # L1 shared endpoints carry a normalized protocol|host|port|db identity — specific, not generic.
    if cand.resource_type == "shared_endpoint":
        return True, f"shared normalized endpoint {cand.resource!r} via different variables — specific resource"
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
    Filtering produces selection only — never a confidence score or final decision.
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


@dataclass(frozen=True)
class FilterDecision:
    """Auditable filtering outcome for one candidate (kept or rejected).

    Rejected candidates are recorded with rule + reason and original
    evidence preserved — never silently discarded.
    """

    candidate_id: str
    service_a: str
    service_b: str
    resource: str
    resource_type: str
    kept: bool
    rule: str
    reason: str
    original_evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "kept": self.kept,
            "rule": self.rule,
            "reason": self.reason,
            "original_evidence": self.original_evidence,
        }


def _rule_for_rejection(reason: str) -> str:
    if "different values" in reason:
        return "drop-different-values"
    if "generic key" in reason:
        return "drop-generic-key"
    return "drop-other"


def filter_with_decisions(candidates: List[Candidate], project: Any) -> List[FilterDecision]:
    """Record deterministic filtering decision + reason for every candidate.

    Unresolved candidates are kept (uncertainty preserved), never silently lost.
    Returns decisions sorted deterministically.
    """
    out: List[FilterDecision] = []
    for cand in sorted(candidates, key=lambda c: (c.service_a, c.service_b, c.resource_type, c.resource)):
        keep, reason = _decide_with_project(cand, project)
        if keep:
            # Mirror rule derivation in build_evidence_package.
            if "explicit depends_on" in reason:
                rule = "keep-explicit-l0"
            elif "shared normalized endpoint" in reason:
                rule = "keep-shared-endpoint"
            elif "named volume" in reason:
                rule = "keep-named-volume"
            elif "same normalized identity" in reason or "same resolved final" in reason:
                rule = "keep-converged-identity"
            elif "specific config" in reason or "no value" in reason:
                rule = "keep-specific-config"
            else:
                rule = "keep-conservative"
        else:
            rule = _rule_for_rejection(reason)
        out.append(
            FilterDecision(
                candidate_id=getattr(cand, "candidate_id", ""),
                service_a=cand.service_a,
                service_b=cand.service_b,
                resource=cand.resource,
                resource_type=cand.resource_type,
                kept=keep,
                rule=rule,
                reason=reason,
                original_evidence=cand.evidence,
            )
        )
    return out


def server_identity(normalized_identity: Optional[str]) -> Optional[str]:
    """Extract server-level identity (protocol|host|port) from a full identity.

    Two services sharing a server but different logical DBs share server
    identity but NOT logical identity — callers must not conflate them.
    """
    if not normalized_identity or normalized_identity.startswith("named_volume|"):
        return None
    if normalized_identity.startswith("service|"):
        return normalized_identity
    parts = normalized_identity.split("|")
    if len(parts) >= 3:
        return "|".join(parts[:3])
    return None


def logical_identity(normalized_identity: Optional[str]) -> Optional[str]:
    """Full logical identity including database (protocol|host|port|db)."""
    if not normalized_identity:
        return None
    if normalized_identity.startswith(("named_volume|", "service|")):
        return normalized_identity
    parts = normalized_identity.split("|")
    if len(parts) >= 4:
        return normalized_identity
    return normalized_identity


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
    # L0 / L1 new types: kept (explicit context / normalized identity, never generic noise)
    if cand.resource_type == "service_dependency":
        return True, f"explicit depends_on {cand.service_a!r}->{cand.resource!r} (L0 baseline)"
    if cand.resource_type == "shared_endpoint":
        return True, f"shared normalized endpoint {cand.resource!r} — specific resource"
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
