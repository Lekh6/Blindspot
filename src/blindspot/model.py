"""
BlindSpot Stage 5: Dependency Model — Service-to-Resource Persistence

Pipeline position: Stage 4 LLM Judge → **Stage 5 Dependency Model** → Stage 6 Graph → Stage 7 Report

Stage 5 does not discover or judge. It stores what Stage 4 decided so Stage 6/7 can render it.

What enters Stage 5:
  List[Tuple[EvidencePackage, JudgeResult]] from judge_evidence_packages().
  - EvidencePackage (Stage 3 bounded, resolved service/image/is_internal/related_config/signals)
  - JudgeResult (Stage 4 verdict/confidence/reason + internal model)

What leaves Stage 5:
  DependencyModel containing Dependency records — service-to-resource (not service→service)
  with evidence + verdict/confidence/reason. `model` is kept privately for logging
  (cache.json / logging system) and omitted from external to_dict() per project rule.

Why downstream needs it:
  - Stage 6 Graph needs Service ↔ Resource bipartite (resource node is the mechanism)
  - Stage 7 Report needs evidence + verdict/confidence/reason to explain why + how confident
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Iterable

from .filtering import EvidencePackage
from .judge import JudgeResult, VALID_VERDICTS, validate_judge_result

logger = logging.getLogger("blindspot.model")

Verdict = str  # reuse VALID_VERDICTS from judge


@dataclass(frozen=True)
class Dependency:
    """One service-to-resource coupling with provenance.

    External view (to_dict) omits _model — user never sees which LLM produced the verdict.
    Internal view (to_log_dict) includes _model + cache_key for audit/logging.
    """

    service_a: str
    service_b: str
    resource: str
    resource_type: str  # env_var | named_volume
    value: Optional[str]
    evidence: EvidencePackage
    verdict: str  # meaningful | coincidental | uncertain
    confidence: float  # 0.0-1.0 mandatory
    reason: str
    # Internal-only: which model produced the verdict (never in external to_dict)
    _model: str = field(default="unknown", repr=False, compare=False)
    # Deterministic cache key for this dependency (candidate+evidence+verdict context)
    cache_key: str = field(default="", compare=False)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), compare=False)

    def __post_init__(self) -> None:
        # Validate confidence/verdict eagerly so downstream never receives broken data
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(f"verdict {self.verdict!r} must be one of {VALID_VERDICTS}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"confidence {self.confidence} out of range [0,1]")
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")
        # EvidencePackage is already validated by filtering stage

    @classmethod
    def from_evidence_judgment(
        cls,
        package: EvidencePackage,
        result: JudgeResult,
    ) -> "Dependency":
        """Build one Dependency from Stage 4's (EvidencePackage, JudgeResult) tuple.

        - This is Stage 5's entry point for a single pair.
        - Validates JudgeResult before storing.
        - Computes deterministic cache_key from package.cache_key_dict().
        - Keeps result.model privately as _model for logging.
        """
        validate_judge_result(result)
        # Deterministic cache key — same as judge stage, so logging correlates
        payload = package.cache_key_dict()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        dep = cls(
            service_a=package.service_a,
            service_b=package.service_b,
            resource=package.resource,
            resource_type=package.resource_type,
            value=package.value,
            evidence=package,
            verdict=result.verdict,
            confidence=float(result.confidence),
            reason=result.reason.strip(),
            _model=result.model,
            cache_key=cache_key,
        )
        # Log internally (never exposed externally) — model audit trail
        logger.debug(
            "dependency %s<->%s %s (%s) -> %s %.2f [%s]",
            dep.service_a,
            dep.service_b,
            dep.resource,
            dep.resource_type,
            dep.verdict,
            dep.confidence,
            dep._model,
        )
        return dep

    def to_dict(self) -> Dict[str, Any]:
        """External serialization — what Stage 6 Graph and Stage 7 Report consume.

        Omits _model and internal logging fields. Preserves terminology
        from AGENTS.md §5: service_a/b, resource, resource_type, evidence, verdict, confidence, reason.
        """
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "evidence": self.evidence.to_dict(),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
        }

    def to_log_dict(self) -> Dict[str, Any]:
        """Internal logging serialization — includes _model + cache_key + created_at.

        Written to cache.json/logging system, never to user-facing Graph/Report.
        """
        d = self.to_dict()
        d["_log"] = {
            "model": self._model,
            "cache_key": self.cache_key,
            "created_at": self.created_at,
        }
        return d

    @property
    def model(self) -> str:
        """Read-only accessor for internal use (logging). Not in to_dict()."""
        return self._model


# ---------------------------------------------------------------------------
# DependencyModel — collection wrapper
# ---------------------------------------------------------------------------

@dataclass
class DependencyModel:
    """Ordered collection of Dependency records.

    What enters: List[Dependency] (already built via from_evidence_judgment)
    What leaves: filtered meaningful subset, JSON for persistence, iterator for Graph/Report.
    Deterministically sorted by (service_a, service_b, resource_type, resource) to match
    discovery/filtering/judge ordering.
    """

    dependencies: List[Dependency] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Deterministic ordering — same key as discovery/filtering/judge
        self.dependencies.sort(key=lambda d: (d.service_a, d.service_b, d.resource_type, d.resource))

    def __len__(self) -> int:
        return len(self.dependencies)

    def __iter__(self) -> Iterable[Dependency]:
        return iter(self.dependencies)

    def meaningful_only(self) -> "DependencyModel":
        """Return new model with only verdict == meaningful (Graph typically uses this)."""
        return DependencyModel([d for d in self.dependencies if d.verdict == "meaningful"])

    def to_list(self) -> List[Dict[str, Any]]:
        """External list — each entry is Dependency.to_dict() (no model)."""
        return [d.to_dict() for d in self.dependencies]

    def to_log_list(self) -> List[Dict[str, Any]]:
        """Internal log list — each entry includes _model."""
        return [d.to_log_dict() for d in self.dependencies]

    def to_json(self, indent: int = 2) -> str:
        """External JSON string (no model)."""
        return json.dumps(self.to_list(), indent=indent, sort_keys=False, ensure_ascii=False)

    def save(self, path: str | Path, include_log: bool = False) -> Path:
        """Persist to file. include_log=True writes internal view (for audit), False writes external."""
        p = Path(path)
        data = self.to_log_list() if include_log else self.to_list()
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    @classmethod
    def from_judgments(
        cls,
        pairs: List[Tuple[EvidencePackage, JudgeResult]],
    ) -> "DependencyModel":
        """Build model from Stage 4 output — the main Stage 5 entry point.

        What enters: pairs from judge_evidence_packages (EvidencePackage, JudgeResult)
        What leaves: DependencyModel sorted deterministically
        """
        deps = [Dependency.from_evidence_judgment(pkg, res) for pkg, res in pairs]
        # Already sorted in __post_init__, but ensure input was sorted (judge does)
        return cls(deps)

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> "DependencyModel":
        """Rehydrate external list (without model) — model defaults to unknown."""
        deps: List[Dependency] = []
        for item in data:
            ev = item["evidence"]
            # Reconstruct EvidencePackage from its to_dict() shape
            # evidence dict has filtering_signals + evidence fields; we need to map back
            pkg = EvidencePackage(
                service_a=item["service_a"],
                service_b=item["service_b"],
                resource=item["resource"],
                resource_type=item["resource_type"],
                value=item.get("value"),
                evidence=ev.get("evidence", ""),
                resolved_service=ev.get("resolved_service"),
                resolved_image=ev.get("resolved_image"),
                is_internal=ev.get("is_internal"),
                reference_type=ev.get("reference_type", "unknown"),
                related_config=ev.get("related_config", {}),
                generic_variable=ev.get("filtering_signals", {}).get("generic_variable", False),
                same_value=ev.get("filtering_signals", {}).get("same_value", False),
                different_values=ev.get("filtering_signals", {}).get("different_values", False),
                volume_targets=ev.get("volume_targets"),
            )
            deps.append(
                Dependency(
                    service_a=item["service_a"],
                    service_b=item["service_b"],
                    resource=item["resource"],
                    resource_type=item["resource_type"],
                    value=item.get("value"),
                    evidence=pkg,
                    verdict=item["verdict"],
                    confidence=float(item["confidence"]),
                    reason=item["reason"],
                    _model=item.get("_log", {}).get("model", "unknown") if "_log" in item else "unknown",
                )
            )
        return cls(deps)


# Convenience function — mirrors filter_and_judge pattern
def build_dependency_model(
    pairs: List[Tuple[EvidencePackage, JudgeResult]],
) -> DependencyModel:
    """Stage 5 convenience: pairs → DependencyModel."""
    return DependencyModel.from_judgments(pairs)
