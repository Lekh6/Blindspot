"""
BlindSpot Stage 2: Candidate Discovery (+ dependency levels L0/L1).

Finds services that share resources or configuration and could therefore be
coupled. Does NOT decide whether the shared resource is a real dependency —
that is Stage 3 (Filtering) and Stage 4 (LLM Judge).

Levels (conceptual, evidence depth separate from strength):
  L0 — Service-level relationship: declared `depends_on` or explicit reference.
       Baseline graph context, NOT automatically hidden coupling.
  L1 — Shared-resource relationship: two+ services independently reference the
       same underlying resource (datastore/queue/cache/object store/volume).
       Central to BlindSpot's hidden-coupling objective.
  L2 — Application-state (table-level): future extension, NOT implemented here.

Tier 1 sources (preserved): shared env keys + shared named volumes.
Stage 1+2 additions: L0 `depends_on` + L1 cross-variable shared-endpoint
identity (same normalized postgresql|host|port|db reached via different var
names). Generic names alone never create a resource dependency; unresolved
references preserve uncertainty (never invented, never silently dropped).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from .parser import Project, Volume

# Relationship types (stable strings for data contract)
REL_EXPLICIT_DEPENDENCY = "explicit_dependency"
REL_SHARED_ENV = "shared_env"
REL_SHARED_VOLUME = "shared_volume"
REL_SHARED_ENDPOINT = "shared_endpoint"

LEVEL_L0 = "L0"
LEVEL_L1 = "L1"

# Candidate sources / origins
ORIGIN_DEPENDS_ON = "compose:depends_on"
ORIGIN_ENVIRONMENT = "compose:environment"
ORIGIN_VOLUMES = "compose:volumes"
ORIGIN_ENDPOINT_IDENTITY = "derived:endpoint-identity"


def stable_candidate_id(
    level: str,
    relationship_type: str,
    resource_type: str,
    resource: str,
    value: Optional[str],
    service_a: str,
    service_b: str,
) -> str:
    """Deterministic 16-hex-char ID for identical normalized inputs.

    Pairwise L1 candidates pass services sorted (a <= b); L0 passes
    directional (dependent, dependency). Never depends on iteration order:
    callers sort names/keys before invoking.
    """
    payload = {
        "level": level,
        "relationship_type": relationship_type,
        "resource_type": resource_type,
        "resource": resource,
        "value": value,
        "service_a": service_a,
        "service_b": service_b,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Candidate:
    service_a: str
    service_b: str
    resource: str
    resource_type: str  # "env_var" | "named_volume" | "service_dependency" | "shared_endpoint"
    value: Optional[str]  # shared value for env_var, None for volumes/mismatched
    evidence: str
    # Stage 1+2 contract (additive, defaults preserve backward compat)
    level: str = LEVEL_L1  # L0 explicit | L1 shared-resource
    relationship_type: str = ""  # explicit_dependency | shared_env | shared_volume | shared_endpoint
    origin: str = ""  # candidate source: compose:environment | compose:volumes | ...
    resource_identity: Optional[str] = None  # normalized identity where established
    provenance: Optional[str] = None  # originating Compose file label (best-effort)
    candidate_id: str = ""  # deterministic stable ID (auto-filled when empty)

    def __post_init__(self) -> None:
        # Backfill defaults derived from resource_type when caller omitted them.
        rel = self.relationship_type
        if not rel:
            if self.resource_type == "env_var":
                rel = REL_SHARED_ENV
            elif self.resource_type == "named_volume":
                rel = REL_SHARED_VOLUME
            elif self.resource_type == "service_dependency":
                rel = REL_EXPLICIT_DEPENDENCY
            elif self.resource_type == "shared_endpoint":
                rel = REL_SHARED_ENDPOINT
            else:
                rel = "unknown"
            object.__setattr__(self, "relationship_type", rel)
        lvl = self.level
        if self.level not in (LEVEL_L0, LEVEL_L1):
            # Default by relationship: explicit -> L0, else L1
            lvl = LEVEL_L0 if rel == REL_EXPLICIT_DEPENDENCY else LEVEL_L1
            object.__setattr__(self, "level", lvl)
        origin = self.origin
        if not origin:
            if rel == REL_EXPLICIT_DEPENDENCY:
                origin = ORIGIN_DEPENDS_ON
            elif rel == REL_SHARED_ENV:
                origin = ORIGIN_ENVIRONMENT
            elif rel == REL_SHARED_VOLUME:
                origin = ORIGIN_VOLUMES
            elif rel == REL_SHARED_ENDPOINT:
                origin = ORIGIN_ENDPOINT_IDENTITY
            else:
                origin = "unknown"
            object.__setattr__(self, "origin", origin)
        if not self.candidate_id:
            cid = stable_candidate_id(
                lvl, rel, self.resource_type, self.resource,
                self.value, self.service_a, self.service_b,
            )
            object.__setattr__(self, "candidate_id", cid)

    def to_dict(self) -> Dict[str, Optional[str]]:
        d: Dict[str, Optional[str]] = {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "evidence": self.evidence,
        }
        d["candidate_id"] = self.candidate_id
        d["level"] = self.level
        d["relationship_type"] = self.relationship_type
        d["origin"] = self.origin
        d["resource_identity"] = self.resource_identity
        d["provenance"] = self.provenance
        return d


def _provenance_label(project: Project) -> Optional[str]:
    sources = getattr(project, "sources", ())
    if sources:
        return sorted(sources)[0]
    # Fall back to per-service source_file if uniform
    files = {s.source_file for s in project.services.values() if getattr(s, "source_file", None)}
    if len(files) == 1:
        return next(iter(files))
    return None


def _discover_shared_env(project: Project, prov: Optional[str]) -> List[Candidate]:
    candidates: List[Candidate] = []
    svc_names = sorted(project.services.keys())
    for a, b in combinations(svc_names, 2):
        svc_a = project.services[a]
        svc_b = project.services[b]
        shared_keys = set(svc_a.environment.keys()) & set(svc_b.environment.keys())
        for key in sorted(shared_keys):
            val_a = svc_a.environment.get(key)
            val_b = svc_b.environment.get(key)
            if val_a is not None and val_a == val_b:
                resource = key
                value: Optional[str] = val_a
                evidence = (
                    f"both services define {key}={val_a!r} "
                    f"({a}={val_a!r}, {b}={val_b!r}); shared environment configuration"
                )
            elif val_a is None and val_b is None:
                resource = key
                value = None
                evidence = (
                    f"both services define {key} with no value "
                    f"({a}=None, {b}=None); shared environment key"
                )
            else:
                resource = key
                value = None
                evidence = (
                    f"both services define {key} but with different values "
                    f"({a}={val_a!r} vs {b}={val_b!r}); same key alone may be coincidence"
                )
            candidates.append(
                Candidate(
                    service_a=a,
                    service_b=b,
                    resource=resource,
                    resource_type="env_var",
                    value=value,
                    evidence=evidence,
                    level=LEVEL_L1,
                    relationship_type=REL_SHARED_ENV,
                    origin=ORIGIN_ENVIRONMENT,
                    provenance=prov,
                )
            )
    return candidates


def _discover_shared_volumes(project: Project, prov: Optional[str]) -> List[Candidate]:
    candidates: List[Candidate] = []
    svc_names = sorted(project.services.keys())
    for a, b in combinations(svc_names, 2):
        svc_a = project.services[a]
        svc_b = project.services[b]
        vols_a = [v for v in svc_a.volumes if v.type == "named" and v.source is not None]
        vols_b = [v for v in svc_b.volumes if v.type == "named" and v.source is not None]
        src_to_vol_a: Dict[str, Volume] = {v.source: v for v in vols_a if v.source is not None}  # type: ignore[dict-item]
        src_to_vol_b: Dict[str, Volume] = {v.source: v for v in vols_b if v.source is not None}  # type: ignore[dict-item]
        shared_sources = set(src_to_vol_a.keys()) & set(src_to_vol_b.keys())
        for src in sorted(shared_sources):
            va = src_to_vol_a[src]
            vb = src_to_vol_b[src]
            resource = src
            evidence = (
                f"both services mount named volume {src} "
                f"({a}:{va.target!r} {va.type}, {b}:{vb.target!r} {vb.type}); shared volume"
            )
            if va.target != vb.target:
                evidence += f" — targets differ ({va.target!r} vs {vb.target!r})"
            candidates.append(
                Candidate(
                    service_a=a,
                    service_b=b,
                    resource=resource,
                    resource_type="named_volume",
                    value=None,
                    evidence=evidence,
                    level=LEVEL_L1,
                    relationship_type=REL_SHARED_VOLUME,
                    origin=ORIGIN_VOLUMES,
                    resource_identity=f"named_volume|{src}",
                    provenance=prov,
                )
            )
    return candidates


def _discover_explicit_dependencies(project: Project, prov: Optional[str]) -> List[Candidate]:
    """L0: Compose `depends_on`. Directional (dependent -> dependency).

    Targets missing from the Compose model are kept with unresolved uncertainty
    (never silently dropped, never confirmed).
    """
    candidates: List[Candidate] = []
    for svc_name in sorted(project.services.keys()):
        svc = project.services[svc_name]
        for dep in sorted(set(getattr(svc, "depends_on", ()) or ())):
            if dep in project.services:
                evidence = (
                    f"{svc_name} declares depends_on {dep!r}; "
                    f"explicit service-level relationship (L0 baseline context, not hidden coupling)"
                )
                identity = f"service|{dep}"
            else:
                evidence = (
                    f"{svc_name} declares depends_on {dep!r} but {dep!r} is not "
                    f"a Compose service in this project; target unresolved"
                )
                identity = None
            candidates.append(
                Candidate(
                    service_a=svc_name,
                    service_b=dep,
                    resource=dep,
                    resource_type="service_dependency",
                    value=None,
                    evidence=evidence,
                    level=LEVEL_L0,
                    relationship_type=REL_EXPLICIT_DEPENDENCY,
                    origin=ORIGIN_DEPENDS_ON,
                    resource_identity=identity,
                    provenance=prov,
                )
            )
    return candidates


def _discover_shared_endpoints(project: Project, prov: Optional[str]) -> List[Candidate]:
    """L1: same normalized endpoint reached via different variable names.

    Uses deterministic bounded_resolve (no LLM). Only emits when the normalized
    identity has a known protocol and exact/config strength. Skips pairs already
    covered by a same-key env candidate (to avoid duplicating Stage 3 evidence)
    and skips unresolved/unknown identities (uncertainty preserved, not invented).
    """
    try:
        from .resolution import bounded_resolve
    except Exception:  # pragma: no cover
        return []

    # Map: normalized_identity -> {service -> [vars]}
    ident_to_svc_vars: Dict[str, Dict[str, List[str]]] = {}
    ident_protocol: Dict[str, Optional[str]] = {}
    for svc_name in sorted(project.services.keys()):
        svc = project.services[svc_name]
        for var in sorted(svc.environment.keys()):
            raw = svc.environment.get(var)
            if raw is None:
                continue
            try:
                rr = bounded_resolve(raw, project, svc_name, svc_name, resource=var, resource_type="env_var")
            except Exception:
                continue
            norm = rr.normalized_identity
            if not norm or not rr.resource_protocol:
                continue
            if rr.identity_strength not in ("exact", "config"):
                continue
            ident_to_svc_vars.setdefault(norm, {}).setdefault(svc_name, []).append(var)
            ident_protocol[norm] = rr.resource_protocol

    candidates: List[Candidate] = []
    for norm in sorted(ident_to_svc_vars.keys()):
        svc_map = ident_to_svc_vars[norm]
        services = sorted(svc_map.keys())
        if len(services) < 2:
            continue
        for a, b in combinations(services, 2):
            vars_a = set(svc_map[a])
            vars_b = set(svc_map[b])
            # Same-key coverage already yields an env_var candidate — don't duplicate.
            if vars_a & vars_b:
                continue
            va_list = sorted(vars_a)
            vb_list = sorted(vars_b)
            evidence = (
                f"{a} ({', '.join(va_list)}) and {b} ({', '.join(vb_list)}) "
                f"resolve to the same normalized endpoint {norm!r}; "
                f"shared logical resource via different variable names"
            )
            candidates.append(
                Candidate(
                    service_a=a,
                    service_b=b,
                    resource=norm,
                    resource_type="shared_endpoint",
                    value=norm,
                    evidence=evidence,
                    level=LEVEL_L1,
                    relationship_type=REL_SHARED_ENDPOINT,
                    origin=ORIGIN_ENDPOINT_IDENTITY,
                    resource_identity=norm,
                    provenance=prov,
                )
            )
    return candidates


def discover_candidates(project: Project) -> List[Candidate]:
    """Discover candidate hidden couplings + L0 explicit context from a Project.

    Preserves Tier 1 sources (shared env keys, shared named volumes) and adds:
      - L0 `depends_on` (explicit, directional, unresolved targets kept)
      - L1 shared-endpoint identity across different variable names

    Returns deterministic deduplicated list sorted by
    (service_a, service_b, resource_type, resource). IDs stable for identical
    normalized inputs; equivalent candidates merged, distinct resources kept.
    """
    prov = _provenance_label(project)
    all_cands: List[Candidate] = []
    all_cands.extend(_discover_shared_env(project, prov))
    all_cands.extend(_discover_shared_volumes(project, prov))
    all_cands.extend(_discover_explicit_dependencies(project, prov))
    all_cands.extend(_discover_shared_endpoints(project, prov))

    # Deduplicate equivalent candidates (same level/type/resource/value/pair).
    seen: Dict[Tuple[str, str, str, str, str, str, str], Candidate] = {}
    for c in all_cands:
        key = (c.level, c.relationship_type, c.resource_type, c.resource, str(c.value or ""), c.service_a, c.service_b)
        if key not in seen:
            seen[key] = c
        # else: genuinely equivalent — keep first deterministically

    result = sorted(seen.values(), key=lambda c: (c.service_a, c.service_b, c.resource_type, c.resource, c.level, str(c.value or "")))
    return result
