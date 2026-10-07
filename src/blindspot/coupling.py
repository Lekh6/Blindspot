"""
BlindSpot — Resource-Centric Coupling Model (Prompt 2)

One CouplingGroup per shared resource identity (not per pair).
Consumed by Graph and Report.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

from .aggregation import GroupedEvidencePackage
from .judge import JudgeResult, VALID_VERDICTS, validate_judge_result

logger = logging.getLogger("blindspot.coupling")


@dataclass(frozen=True)
class CouplingGroup:
    """One resource-centric coupling finding (group-level)."""

    grouping_key: str
    resource_identity: Optional[str]  # normalized_identity or fallback
    resource_protocol: Optional[str]
    resource_type: str
    resolution_status: str
    identity_strength: str
    services: Tuple[str, ...]  # sorted
    configuration_evidence: Dict[str, Tuple[str, ...]]  # service -> vars
    unresolved_vars: Tuple[str, ...]
    representative_chain: Tuple[Dict[str, Any], ...]
    evidence_count: int
    service_count: int
    observation_resources: Tuple[str, ...]
    # LLM judgment (group-level)
    verdict: str  # meaningful | coincidental | uncertain
    confidence: float
    reason: str
    # BASE enrichment (deterministic scoring from structured signals; defaults = not scored)
    classification: str = "uncertain"  # strong | likely | possible | uncertain
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    uncertainty: float = 1.0
    scoring_version: str = ""
    _model: str = field(default="unknown", repr=False, compare=False)
    cache_key: str = field(default="", compare=False)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), compare=False)
    # Keep full grouped package for evidence
    grouped_package: Optional[GroupedEvidencePackage] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(f"verdict {self.verdict!r} must be one of {VALID_VERDICTS}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"confidence {self.confidence} out of range")
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")

    @classmethod
    def from_grouped_judgment(
        cls,
        grouped: GroupedEvidencePackage,
        result: JudgeResult,
    ) -> "CouplingGroup":
        validate_judge_result(result)
        payload = grouped.cache_key_dict()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        dep = cls(
            grouping_key=grouped.grouping_key,
            resource_identity=grouped.resource_identity,
            resource_protocol=grouped.resource_protocol,
            resource_type=grouped.resource_type,
            resolution_status=grouped.resolution_status,
            identity_strength=grouped.identity_strength,
            services=grouped.services,
            configuration_evidence=dict(grouped.configuration_evidence),
            unresolved_vars=grouped.unresolved_vars,
            representative_chain=grouped.representative_chain,
            evidence_count=grouped.evidence_count,
            service_count=grouped.service_count,
            observation_resources=grouped.observation_resources,
            verdict=result.verdict,
            confidence=float(result.confidence),
            reason=result.reason.strip(),
            _model=result.model,
            cache_key=cache_key,
            grouped_package=grouped,
        )
        logger.debug(
            "coupling group %s %s services=%s -> %s %.2f [%s]",
            dep.resource_identity,
            dep.resource_type,
            ",".join(dep.services),
            dep.verdict,
            dep.confidence,
            dep._model,
        )
        return dep

    def to_dict(self) -> Dict[str, Any]:
        """External serialization — no model."""
        return {
            "grouping_key": self.grouping_key,
            "resource_identity": self.resource_identity,
            "resource_protocol": self.resource_protocol,
            "resource_type": self.resource_type,
            "resolution_status": self.resolution_status,
            "identity_strength": self.identity_strength,
            "services": list(self.services),
            "configuration_evidence": {k: list(v) for k, v in self.configuration_evidence.items()},
            "unresolved_vars": list(self.unresolved_vars),
            "representative_chain": list(self.representative_chain),
            "evidence_count": self.evidence_count,
            "service_count": self.service_count,
            "observation_resources": list(self.observation_resources),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
            "classification": self.classification,
            "score": self.score,
            "score_breakdown": dict(self.score_breakdown),
            "uncertainty": self.uncertainty,
            "scoring_version": self.scoring_version,
        }

    def to_log_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        d["_log"] = {"model": self._model, "cache_key": self.cache_key, "created_at": self.created_at}
        return d

    @property
    def model(self) -> str:
        return self._model

    def with_scoring(self, scoring: Any) -> "CouplingGroup":
        """Return a copy enriched with deterministic scoring (BASE)."""
        from dataclasses import replace
        return replace(self, classification=scoring.classification, score=float(scoring.score),
                       score_breakdown=dict(scoring.breakdown), uncertainty=float(scoring.uncertainty),
                       scoring_version=getattr(scoring, "scoring_version", ""))


@dataclass
class CouplingModel:
    """Ordered collection of CouplingGroup."""

    groups: List[CouplingGroup] = field(default_factory=list)

    def __post_init__(self):
        self.groups.sort(key=lambda g: g.grouping_key)

    def __len__(self):
        return len(self.groups)

    def __iter__(self):
        return iter(self.groups)

    def meaningful_only(self) -> "CouplingModel":
        return CouplingModel([g for g in self.groups if g.verdict == "meaningful"])

    def to_list(self) -> List[Dict[str, Any]]:
        return [g.to_dict() for g in self.groups]

    def to_log_list(self) -> List[Dict[str, Any]]:
        return [g.to_log_dict() for g in self.groups]

    @classmethod
    def from_grouped_judgments(
        cls,
        pairs: List[Tuple[GroupedEvidencePackage, JudgeResult]],
    ) -> "CouplingModel":
        groups = [CouplingGroup.from_grouped_judgment(g, r) for g, r in pairs]
        return cls(groups)

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> "CouplingModel":
        groups: List[CouplingGroup] = []
        for item in data:
            groups.append(
                CouplingGroup(
                    grouping_key=item["grouping_key"],
                    resource_identity=item.get("resource_identity"),
                    resource_protocol=item.get("resource_protocol"),
                    resource_type=item.get("resource_type", "env_var"),
                    resolution_status=item.get("resolution_status", "unresolved"),
                    identity_strength=item.get("identity_strength", "unknown"),
                    services=tuple(item.get("services", [])),
                    configuration_evidence={k: tuple(v) for k, v in item.get("configuration_evidence", {}).items()},
                    unresolved_vars=tuple(item.get("unresolved_vars", [])),
                    representative_chain=tuple(item.get("representative_chain", [])),
                    evidence_count=item.get("evidence_count", 0),
                    service_count=item.get("service_count", 0),
                    observation_resources=tuple(item.get("observation_resources", [])),
                    verdict=item["verdict"],
                    confidence=float(item["confidence"]),
                    reason=item["reason"],
                    classification=item.get("classification", "uncertain"),
                    score=float(item.get("score", 0.0)),
                    score_breakdown=dict(item.get("score_breakdown", {})),
                    uncertainty=float(item.get("uncertainty", 1.0)),
                    scoring_version=str(item.get("scoring_version", "")),
                    _model=item.get("_log", {}).get("model", "unknown") if "_log" in item else "unknown",
                    cache_key=item.get("_log", {}).get("cache_key", ""),
                )
            )
        return cls(groups)


def build_coupling_model(
    pairs: List[Tuple[GroupedEvidencePackage, JudgeResult]],
) -> CouplingModel:
    return CouplingModel.from_grouped_judgments(pairs)
