"""
BlindSpot Stage 2: Candidate Discovery

Finds services that share resources or configuration and could therefore be coupled.
Does NOT decide whether the shared resource is a real dependency — that is
Stage 3 (Filtering) and Stage 4 (LLM Judge).

Tier 1: shared environment configuration (env_var) and shared named volumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import List, Dict, Optional

from .parser import Project, Volume


@dataclass(frozen=True)
class Candidate:
    service_a: str
    service_b: str
    resource: str
    resource_type: str  # "env_var" | "named_volume"
    value: Optional[str]  # shared value for env_var, None for volumes or mismatched
    evidence: str

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "evidence": self.evidence,
        }


def discover_candidates(project: Project) -> List[Candidate]:
    """Discover candidate hidden couplings from a normalized Project.

    - Shared env: any key appearing in both services' environment (value
      equality is captured in evidence but does not suppress candidate — filtering
      decides).
    - Shared named volumes: same `source` where `type == "named"` on both sides.

    Returns deterministic sorted list (by service_a, service_b, resource).
    """
    candidates: List[Candidate] = []
    svc_names = sorted(project.services.keys())

    # Pairwise comparison
    for a, b in combinations(svc_names, 2):
        svc_a = project.services[a]
        svc_b = project.services[b]

        # ---- shared env vars ----
        # Use set intersection of keys; presence matters, value equality is evidence
        keys_a = set(svc_a.environment.keys())
        keys_b = set(svc_b.environment.keys())
        shared_keys = keys_a & keys_b
        for key in sorted(shared_keys):
            val_a = svc_a.environment.get(key)
            val_b = svc_b.environment.get(key)
            # Cleaner split: resource is the key, value is shared value if equal else None
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
                )
            )

        # ---- shared named volumes ----
        # Only named volumes count as hidden coupling; bind/anonymous are ignored
        vols_a = [v for v in svc_a.volumes if v.type == "named" and v.source is not None]
        vols_b = [v for v in svc_b.volumes if v.type == "named" and v.source is not None]
        # Map source -> representative volume (first occurrence) for target info
        src_to_vol_a: Dict[str, Volume] = {v.source: v for v in vols_a if v.source is not None}  # type: ignore[dict-item]
        src_to_vol_b: Dict[str, Volume] = {v.source: v for v in vols_b if v.source is not None}  # type: ignore[dict-item]
        shared_sources = set(src_to_vol_a.keys()) & set(src_to_vol_b.keys())
        for src in sorted(shared_sources):
            va = src_to_vol_a[src]
            vb = src_to_vol_b[src]
            # resource is the named volume source; value is None for volumes
            resource = src
            evidence = (
                f"both services mount named volume {src} "
                f"({a}:{va.target!r} {va.type}, {b}:{vb.target!r} {vb.type}); shared volume"
            )
            # If targets differ, note it (still a coupling via same volume)
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
                )
            )

    # Deterministic ordering
    candidates.sort(key=lambda c: (c.service_a, c.service_b, c.resource_type, c.resource))
    return candidates
