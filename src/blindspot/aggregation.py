"""
BlindSpot — Resource-Centric Aggregation (Prompt 2)

Pipeline position: Filtering+Resolution -> Resource Identity -> AGGREGATION -> Grouped Evidence -> LLM

Groups pairwise EvidencePackage observations by deterministic normalized resource identity.
"""

from __future__ import annotations

from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set, Any, Optional

from .filtering import EvidencePackage


def _grouping_key(pkg: EvidencePackage) -> str:
    """
    Deterministic grouping key per spec §2.

    Primary: normalized_identity when available (includes protocol/host/port/db, credentials stripped).
    Preserves type/protocol distinctions via normalized content itself (e.g. postgresql|host|port|db vs named_volume|...).
    For partial/config with same template, same placeholder normalized groups together.
    Fallback for unknown (normalized is None): raw resource_type + resource + final_value/value to avoid over-merging.
    """
    if pkg.normalized_identity is not None:
        # Include resource_type prefix to keep env_var vs named_volume distinct if same string collision
        # normalized already contains protocol for env_var, but be explicit
        return f"{pkg.resource_type}:{pkg.normalized_identity}"
    # Unknown — do not broadly merge. Use raw identity.
    raw_val = pkg.final_value if pkg.final_value is not None else pkg.value
    # Include resource name to keep DB_HOST vs DB_NAME separate when both unresolved
    return f"raw:{pkg.resource_type}:{pkg.resource}:{raw_val}"


@dataclass(frozen=True)
class GroupedEvidencePackage:
    """
    One bounded grouped evidence package per shared resource identity.

    Represents: a set of services independently configured to access the same underlying
    resource or resource configuration (not a pairwise edge).
    """

    grouping_key: str
    resource_identity: Optional[str]  # normalized_identity or fallback raw identity
    resource_protocol: Optional[str]
    resource_type: str  # env_var | named_volume | mixed? we store primary type
    resolution_status: str  # internal / external_confirmed / partial / unresolved
    identity_strength: str  # exact / config / unknown
    services: Tuple[str, ...]  # sorted tuple of involved services
    observations: Tuple[EvidencePackage, ...]  # sorted bounded observations
    configuration_evidence: Dict[str, Tuple[str, ...]]  # service -> sorted tuple of variable names
    unresolved_vars: Tuple[str, ...]
    representative_chain: Tuple[Dict[str, Any], ...]
    evidence_count: int
    service_count: int
    # For bounded summary
    observation_resources: Tuple[str, ...]  # sorted distinct variable names across group

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grouping_key": self.grouping_key,
            "resource_identity": self.resource_identity,
            "resource_protocol": self.resource_protocol,
            "resource_type": self.resource_type,
            "resolution_status": self.resolution_status,
            "identity_strength": self.identity_strength,
            "services": list(self.services),
            "observations": [o.to_dict() for o in self.observations],
            "configuration_evidence": {k: list(v) for k, v in self.configuration_evidence.items()},
            "unresolved_vars": list(self.unresolved_vars),
            "representative_chain": list(self.representative_chain),
            "evidence_count": self.evidence_count,
            "service_count": self.service_count,
            "observation_resources": list(self.observation_resources),
        }

    def cache_key_dict(self) -> Dict[str, Any]:
        """Deterministic cache key for grouped LLM judgment."""
        return {
            "grouping_key": self.grouping_key,
            "resource_identity": self.resource_identity,
            "resource_protocol": self.resource_protocol,
            "resource_type": self.resource_type,
            "resolution_status": self.resolution_status,
            "identity_strength": self.identity_strength,
            "services": list(self.services),
            "configuration_evidence": {k: sorted(v) for k, v in sorted(self.configuration_evidence.items())},
            "unresolved_vars": sorted(self.unresolved_vars),
            "evidence_count": self.evidence_count,
        }


def aggregate_evidence_packages(packages: List[EvidencePackage]) -> List[GroupedEvidencePackage]:
    """
    Resource-centric aggregation before LLM.

    Input: pairwise EvidencePackage list (already filtered, bounded).
    Output: list of GroupedEvidencePackage, one per shared resource identity, deterministic sorted.

    Grouping policy (§21):
      EXACT: group by normalized_identity
      CONFIG: group only when deterministic configuration identity equivalent (same normalized or same raw template)
      UNKNOWN: do not broadly merge — fallback to raw resource+value
    """
    if not packages:
        return []

    # Deterministic ordering of input
    packages_sorted = sorted(packages, key=lambda p: (p.service_a, p.service_b, p.resource_type, p.resource, str(p.value or "")))

    groups: Dict[str, List[EvidencePackage]] = defaultdict(list)
    for pkg in packages_sorted:
        key = _grouping_key(pkg)
        groups[key].append(pkg)

    # Build grouped packages deterministically sorted by key
    result: List[GroupedEvidencePackage] = []
    for key in sorted(groups.keys()):
        obs_list = sorted(groups[key], key=lambda p: (p.service_a, p.service_b, p.resource))
        # Services involved: union of service_a/b across observations
        services_set: Set[str] = set()
        config_by_service: Dict[str, Set[str]] = defaultdict(set)
        unresolved_union: Set[str] = set()
        protocols: List[Optional[str]] = []
        resource_types: List[str] = []
        statuses: List[str] = []
        strengths: List[str] = []
        for pkg in obs_list:
            services_set.add(pkg.service_a)
            services_set.add(pkg.service_b)
            # configuration evidence: each service gets the variable name
            config_by_service[pkg.service_a].add(pkg.resource)
            config_by_service[pkg.service_b].add(pkg.resource)
            unresolved_union.update(pkg.unresolved_vars)
            protocols.append(pkg.resource_protocol)
            resource_types.append(pkg.resource_type)
            statuses.append(pkg.resolution_status)
            strengths.append(pkg.identity_strength)

        services_sorted = tuple(sorted(services_set))
        # Deterministic config evidence
        config_evidence: Dict[str, Tuple[str, ...]] = {
            svc: tuple(sorted(vars_set))
            for svc, vars_set in sorted(config_by_service.items())
        }
        # Observation resources distinct
        obs_resources = tuple(sorted({pkg.resource for pkg in obs_list}))

        # Choose representative resource_type/protocol/status/strength deterministically
        # Most common, tie broken by sorted
        def most_common_or_first(items: List[str]) -> str:
            if not items:
                return "unknown"
            cnt = Counter(items)
            max_c = max(cnt.values())
            candidates = sorted([k for k, v in cnt.items() if v == max_c])
            return candidates[0]

        # For protocol, prefer non-None
        proto_candidates = [p for p in protocols if p is not None]
        representative_protocol = most_common_or_first(proto_candidates) if proto_candidates else None
        # resource_type: if mixed, pick most common (should be consistent within group)
        representative_type = most_common_or_first(resource_types)
        representative_status = most_common_or_first(statuses)
        representative_strength = most_common_or_first(strengths)

        # Resource identity: use the group's key's normalized part or fallback
        # For grouped key with prefix, strip prefix for identity
        if obs_list[0].normalized_identity is not None:
            resource_identity = obs_list[0].normalized_identity
        else:
            # fallback raw identity: use grouping key's raw part
            # Reconstruct from first obs
            raw_val = obs_list[0].final_value if obs_list[0].final_value is not None else obs_list[0].value
            resource_identity = f"{obs_list[0].resource}={raw_val}" if raw_val else obs_list[0].resource

        # Representative chain: choose the longest chain? Or first with chain? Keep first sorted obs with non-empty chain
        rep_chain: Tuple[Dict[str, Any], ...] = ()
        for pkg in sorted(obs_list, key=lambda p: len(p.resolution_chain), reverse=True):
            if pkg.resolution_chain:
                rep_chain = pkg.resolution_chain
                break
        else:
            rep_chain = obs_list[0].resolution_chain if obs_list else ()

        # Bounded: cap observations stored? Already bounded via filtering; but ensure we don't exceed large counts
        # Keep all observations but they are already bounded (max candidates pairwise). For Cal.com 6 obs, fine.
        # For safety, cap at 20, deterministic sorted
        if len(obs_list) > 20:
            obs_list = obs_list[:20]

        grouped = GroupedEvidencePackage(
            grouping_key=key,
            resource_identity=resource_identity,
            resource_protocol=representative_protocol,
            resource_type=representative_type,
            resolution_status=representative_status,
            identity_strength=representative_strength,
            services=services_sorted,
            observations=tuple(obs_list),
            configuration_evidence=config_evidence,
            unresolved_vars=tuple(sorted(unresolved_union)),
            representative_chain=rep_chain,
            evidence_count=len(obs_list),
            service_count=len(services_sorted),
            observation_resources=obs_resources,
        )
        result.append(grouped)

    # Deterministic final sort by grouping_key
    result.sort(key=lambda g: g.grouping_key)
    return result
