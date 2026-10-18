"""
BlindSpot Stage 5: Deterministic Dependency Decision Engine

Pipeline position: Stage 4 Contextual Judgment → **Stage 5 Decision Engine** → Stage 6 Graph → Stage 7 Report

Stage 5 does not discover or judge. It evaluates verified static evidence from Stages 1-3
and validated LLM judgments from Stage 4 to produce a traceable decision for each candidate.

Decision semantics (per AGENTS.md):
- YES (potential_dependency) — Sufficient evidence to flag as potential hidden dependency
- NO (insufficient_evidence) — Does not meet minimum evidence requirements
- REVIEW (uncertain) — Evidence is conflicting, insufficiently resolved, or ambiguous

Stage 4 verdict (meaningful/coincidental/uncertain) is kept distinct from Stage 5 decision.
Operational failures (missing judgment, invalid output, API errors) are represented
as explicit processing states, never silently converted to NO.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .context_judge import CandidateJudgment, JudgmentFailure
from .filtering import EvidencePackage
from .judge import VALID_VERDICTS

logger = logging.getLogger("blindspot.decision")

DECISION_SCHEMA_VERSION = "1"
POLICY_VERSION = "stage5-v1"


class Decision(str, Enum):
    """Stage 5 decision outcome."""
    POTENTIAL_DEPENDENCY = "potential_dependency"  # YES
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # NO
    REVIEW = "review"  # UNCERTAIN / needs human review


class ProcessingStatus(str, Enum):
    """Processing state for candidates that could not be decided."""
    OK = "ok"
    MISSING_JUDGMENT = "missing_judgment"
    INVALID_JUDGMENT = "invalid_judgment"
    OPERATIONAL_FAILURE = "operational_failure"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


@dataclass(frozen=True)
class DecisionRecord:
    """
    Versioned, structured decision record for one candidate.

    External view (to_dict) omits internal logging fields.
    Internal view (to_log_dict) includes policy_version, cache_key for audit.
    """

    candidate_id: str
    service_a: str
    service_b: str
    resource: str
    resource_type: str
    resource_identity: Optional[str]
    resolution_status: str
    identity_strength: str
    # Stage 4 input
    stage4_verdict: str  # meaningful | coincidental | uncertain
    stage4_confidence: float
    stage4_reason: str
    stage4_model: str
    # Stage 5 output
    decision: Decision
    processing_status: ProcessingStatus
    score: Optional[float]  # 0.0-1.0, optional numerical score
    evidence_references: Tuple[str, ...]  # stable refs supporting the decision
    counter_evidence_references: Tuple[str, ...]  # refs weakening the decision
    missing_information: Tuple[str, ...]
    policy_rules_applied: Tuple[str, ...]  # machine-readable rule IDs
    rationale: str  # human-readable explanation
    # Versioning
    decision_schema_version: str = DECISION_SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    # Internal (never in external to_dict)
    _cache_key: str = field(default="", compare=False, repr=False)
    _created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.decision not in Decision:
            raise ValueError(f"decision {self.decision!r} must be one of {[d.value for d in Decision]}")
        if self.processing_status not in ProcessingStatus:
            raise ValueError(f"processing_status {self.processing_status!r} must be one of {[s.value for s in ProcessingStatus]}")
        if self.score is not None and not 0.0 <= float(self.score) <= 1.0:
            raise ValueError(f"score {self.score} out of range [0,1]")
        if not self.rationale.strip():
            raise ValueError("rationale must be non-empty")

    @classmethod
    def from_candidate_judgment(
        cls,
        candidate_id: str,
        service_a: str,
        service_b: str,
        resource: str,
        resource_type: str,
        resource_identity: Optional[str],
        resolution_status: str,
        identity_strength: str,
        judgment: CandidateJudgment,
        evidence_package: EvidencePackage,
        conflicting_evidence: Tuple[str, ...] = (),
        policy_version: str = POLICY_VERSION,
    ) -> "DecisionRecord":
        """Build decision record from validated Stage 4 judgment and evidence."""
        # Apply deterministic decision policy
        decision, score, rules, rationale, missing, counter_refs = cls._apply_policy(
            judgment=judgment,
            evidence=evidence_package,
            resource_identity=resource_identity,
            resolution_status=resolution_status,
            identity_strength=identity_strength,
            conflicting_evidence=conflicting_evidence,
        )

        # Build cache key from all material inputs
        payload = {
            "candidate_id": candidate_id,
            "stage4_verdict": judgment.verdict,
            "stage4_confidence": judgment.confidence,
            "decision": decision.value,
            "score": score,
            "policy_version": policy_version,
            "resource_identity": resource_identity,
            "resolution_status": resolution_status,
            "identity_strength": identity_strength,
            "conflicting_evidence": list(conflicting_evidence),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return cls(
            candidate_id=candidate_id,
            service_a=service_a,
            service_b=service_b,
            resource=resource,
            resource_type=resource_type,
            resource_identity=resource_identity,
            resolution_status=resolution_status,
            identity_strength=identity_strength,
            stage4_verdict=judgment.verdict,
            stage4_confidence=judgment.confidence,
            stage4_reason=judgment.reason,
            stage4_model=judgment.model,
            decision=decision,
            processing_status=ProcessingStatus.OK,
            score=score,
            evidence_references=judgment.supporting_evidence,
            counter_evidence_references=counter_refs,
            missing_information=missing,
            policy_rules_applied=rules,
            rationale=rationale,
            _cache_key=cache_key,
        )

    @classmethod
    def from_failure(
        cls,
        candidate_id: str,
        service_a: str,
        service_b: str,
        resource: str,
        resource_type: str,
        resource_identity: Optional[str],
        resolution_status: str,
        identity_strength: str,
        failure: JudgmentFailure,
        evidence_package: Optional[EvidencePackage] = None,
        policy_version: str = POLICY_VERSION,
    ) -> "DecisionRecord":
        """Build decision record for a candidate with failed/invalid Stage 4 judgment."""
        status_map = {
            "missing": ProcessingStatus.MISSING_JUDGMENT,
            "duplicate": ProcessingStatus.INVALID_JUDGMENT,
            "unknown_candidate": ProcessingStatus.INVALID_JUDGMENT,
            "malformed": ProcessingStatus.INVALID_JUDGMENT,
            "invalid_verdict": ProcessingStatus.INVALID_JUDGMENT,
            "invalid_confidence": ProcessingStatus.INVALID_JUDGMENT,
            "invalid_evidence_ref": ProcessingStatus.INVALID_JUDGMENT,
            "provider_error": ProcessingStatus.OPERATIONAL_FAILURE,
            "timeout": ProcessingStatus.OPERATIONAL_FAILURE,
            "context_too_large": ProcessingStatus.OPERATIONAL_FAILURE,
        }
        proc_status = status_map.get(failure.error_type, ProcessingStatus.OPERATIONAL_FAILURE)

        # Deterministic fallback: NO decision for failures, with explicit rationale
        rationale = f"Stage 4 judgment unavailable: {failure.error_type} — {failure.message}. Cannot determine dependency without valid semantic judgment."

        payload = {
            "candidate_id": candidate_id,
            "decision": Decision.INSUFFICIENT_EVIDENCE.value,
            "processing_status": proc_status.value,
            "policy_version": policy_version,
            "failure_type": failure.error_type,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return cls(
            candidate_id=candidate_id,
            service_a=service_a,
            service_b=service_b,
            resource=resource,
            resource_type=resource_type,
            resource_identity=resource_identity,
            resolution_status=resolution_status,
            identity_strength=identity_strength,
            stage4_verdict="",
            stage4_confidence=0.0,
            stage4_reason=failure.message,
            stage4_model="failure",
            decision=Decision.INSUFFICIENT_EVIDENCE,
            processing_status=proc_status,
            score=None,
            evidence_references=(),
            counter_evidence_references=(),
            missing_information=(failure.message,),
            policy_rules_applied=("failure-handling",),
            rationale=rationale,
            _cache_key=cache_key,
        )

    @staticmethod
    def _apply_policy(
        judgment: CandidateJudgment,
        evidence: EvidencePackage,
        resource_identity: Optional[str],
        resolution_status: str,
        identity_strength: str,
        conflicting_evidence: Tuple[str, ...],
    ) -> Tuple[Decision, Optional[float], Tuple[str, ...], str, Tuple[str, ...], Tuple[str, ...]]:
        """
        Deterministic decision policy.

        Returns: (decision, score, rules_applied, rationale, missing_info, counter_evidence_refs)
        """
        rules: List[str] = []
        missing: List[str] = []
        counter_refs: List[str] = []

        # Rule 0: Hard filter — generic variable with no resolved identity
        if evidence.generic_variable and not resource_identity:
            rules.append("reject-generic-unresolved")
            return (
                Decision.INSUFFICIENT_EVIDENCE,
                None,
                tuple(rules),
                "Shared generic variable (e.g., PORT, DEBUG) with no resolved resource identity. Insufficient evidence for dependency.",
                ("resolved_resource_identity",),
                (),
            )

        # Rule 1: Named volume — always potential dependency if meaningful
        if (evidence.resource_type == "named_volume"
                and judgment.verdict == "meaningful"):
            rules.append("accept-named-volume-meaningful")
            return (
                Decision.POTENTIAL_DEPENDENCY,
                0.85,
                tuple(rules),
                f"Shared named volume ({evidence.resource}) with meaningful verdict.",
                (),
                (),
            )

        # Rule 2: Conflicting evidence present → review
        if conflicting_evidence:
            rules.append("review-conflicting-evidence")
            counter_refs.extend(conflicting_evidence)
            return (
                Decision.REVIEW,
                judgment.confidence,
                tuple(rules),
                f"Conflicting evidence detected: {', '.join(conflicting_evidence[:3])}. Stage 4: {judgment.verdict} ({judgment.confidence:.2f}).",
                (),
                tuple(counter_refs),
            )

        # Rule 3: Strong positive — resolved internal/external with exact identity + meaningful verdict
        if (resolution_status in ("internal", "external_confirmed")
                and identity_strength == "exact"
                and judgment.verdict == "meaningful"
                and judgment.confidence >= 0.85):
            rules.append("accept-exact-meaningful-high-confidence")
            return (
                Decision.POTENTIAL_DEPENDENCY,
                0.9,
                tuple(rules),
                f"Resolved {resolution_status} resource with exact identity ({resource_identity}). Stage 4 verdict: meaningful ({judgment.confidence:.2f}).",
                (),
                (),
            )

        # Rule 4: Strong positive — config identity with meaningful verdict + high confidence
        if (resolution_status in ("internal", "external_confirmed", "partial")
                and identity_strength == "config"
                and judgment.verdict == "meaningful"
                and judgment.confidence >= 0.8):
            rules.append("accept-config-meaningful-high-confidence")
            return (
                Decision.POTENTIAL_DEPENDENCY,
                0.8,
                tuple(rules),
                f"Shared configuration template ({resource_identity}) with meaningful verdict ({judgment.confidence:.2f}). Identity strength: config.",
                (),
                (),
            )

        # Rule 5: Coincidental verdict → insufficient evidence
        if judgment.verdict == "coincidental":
            rules.append("reject-coincidental")
            return (
                Decision.INSUFFICIENT_EVIDENCE,
                None,
                tuple(rules),
                f"Stage 4 verdict: coincidental. {judgment.reason}",
                (),
                (f"stage4_verdict:coincidental",),
            )

        # Rule 6: Uncertain verdict with low confidence → review
        if judgment.verdict == "uncertain":
            rules.append("review-uncertain-verdict")
            missing.append("stage4_verdict:uncertain")
            if judgment.confidence < 0.6:
                missing.append("low_confidence")
            return (
                Decision.REVIEW,
                judgment.confidence if judgment.confidence > 0 else None,
                tuple(rules),
                f"Stage 4 verdict: uncertain ({judgment.confidence:.2f}). {judgment.reason}",
                tuple(missing),
                (),
            )

        # Rule 7: Meaningful but unresolved/partial with low confidence → review
        if (judgment.verdict == "meaningful"
                and resolution_status in ("unresolved", "partial")
                and judgment.confidence < 0.7):
            rules.append("review-meaningful-low-confidence-unresolved")
            missing.append(f"resolution_status:{resolution_status}")
            missing.append("low_confidence")
            return (
                Decision.REVIEW,
                judgment.confidence,
                tuple(rules),
                f"Stage 4 verdict: meaningful but {resolution_status} with low confidence ({judgment.confidence:.2f}).",
                tuple(missing),
                (),
            )

        # Rule 8: Default — meaningful with moderate confidence but no exact identity
        if judgment.verdict == "meaningful":
            rules.append("review-meaningful-moderate")
            return (
                Decision.REVIEW,
                judgment.confidence,
                tuple(rules),
                f"Stage 4 verdict: meaningful ({judgment.confidence:.2f}) but insufficient resolution for automatic acceptance.",
                ("exact_identity_not_confirmed",),
                (),
            )

        # Fallback: review for any unhandled case
        rules.append("review-unhandled")
        return (
            Decision.REVIEW,
            None,
            tuple(rules),
            f"Policy did not match a definitive rule. Stage 4: {judgment.verdict} ({judgment.confidence:.2f}).",
            ("policy_no_match",),
            (),
        )

    def to_dict(self) -> Dict[str, Any]:
        """External serialization — what Stage 6/7 consume. Omits internal logging fields."""
        return {
            "candidate_id": self.candidate_id,
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "resource_identity": self.resource_identity,
            "resolution_status": self.resolution_status,
            "identity_strength": self.identity_strength,
            "stage4_verdict": self.stage4_verdict,
            "stage4_confidence": self.stage4_confidence,
            "stage4_reason": self.stage4_reason,
            "stage4_model": self.stage4_model,
            "decision": self.decision.value,
            "processing_status": self.processing_status.value,
            "score": self.score,
            "evidence_references": list(self.evidence_references),
            "counter_evidence_references": list(self.counter_evidence_references),
            "missing_information": list(self.missing_information),
            "policy_rules_applied": list(self.policy_rules_applied),
            "rationale": self.rationale,
            "decision_schema_version": self.decision_schema_version,
            "policy_version": self.policy_version,
        }

    def to_log_dict(self) -> Dict[str, Any]:
        """Internal logging serialization — includes cache_key and timestamps."""
        d = self.to_dict()
        d["_log"] = {
            "cache_key": self._cache_key,
            "created_at": self._created_at,
        }
        return d


@dataclass
class DecisionModel:
    """Ordered collection of DecisionRecord."""

    decisions: List[DecisionRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Deterministic ordering
        self.decisions.sort(key=lambda d: (d.service_a, d.service_b, d.resource_type, d.resource))

    def __len__(self) -> int:
        return len(self.decisions)

    def __iter__(self):
        return iter(self.decisions)

    def potential_dependencies_only(self) -> "DecisionModel":
        return DecisionModel([d for d in self.decisions if d.decision == Decision.POTENTIAL_DEPENDENCY])

    def to_list(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self.decisions]

    def to_log_list(self) -> List[Dict[str, Any]]:
        return [d.to_log_dict() for d in self.decisions]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_list(), indent=indent, sort_keys=False, ensure_ascii=False)


def build_decision_model(
    contextual_results: List[Tuple[Any, List[CandidateJudgment], List[JudgmentFailure]]],
) -> DecisionModel:
    """
    Stage 5 entry point: build DecisionModel from contextual judgment results.

    Input: List of (GroupedEvidencePackage, List[CandidateJudgment], List[JudgmentFailure])
    from judge_contextual().

    For each grouped package, iterate its observations and match to candidate judgments
    by candidate_id. Build one DecisionRecord per candidate.
    """
    decisions: List[DecisionRecord] = []

    for grouped_pkg, judgments, failures in contextual_results:
        if grouped_pkg is None:
            continue

        # Build lookup maps
        judgment_by_id = {j.candidate_id: j for j in judgments}
        failure_by_id = {f.candidate_id: f for f in failures}

        # For each observation (pairwise candidate) in the grouped package
        for obs in grouped_pkg.observations:
            cid = obs.candidate_id or f"{obs.service_a}/{obs.service_b}/{obs.resource}"

            # Extract conflicting evidence relevant to this candidate
            candidate_conflicts = tuple(
                _conflict_description(obs, c) for c in grouped_pkg.observations
                if c != obs and _candidates_conflict(obs, c)
            )

            if cid in judgment_by_id:
                j = judgment_by_id[cid]
                try:
                    rec = DecisionRecord.from_candidate_judgment(
                        candidate_id=cid,
                        service_a=obs.service_a,
                        service_b=obs.service_b,
                        resource=obs.resource,
                        resource_type=obs.resource_type,
                        resource_identity=obs.normalized_identity,
                        resolution_status=obs.resolution_status,
                        identity_strength=obs.identity_strength,
                        judgment=j,
                        evidence_package=obs,
                        conflicting_evidence=candidate_conflicts,
                    )
                except Exception as e:
                    # Policy evaluation failure → explicit processing failure
                    logger.warning(f"Policy evaluation failed for {cid}: {e}")
                    rec = DecisionRecord(
                        candidate_id=cid,
                        service_a=obs.service_a,
                        service_b=obs.service_b,
                        resource=obs.resource,
                        resource_type=obs.resource_type,
                        resource_identity=obs.normalized_identity,
                        resolution_status=obs.resolution_status,
                        identity_strength=obs.identity_strength,
                        stage4_verdict=getattr(j, "verdict", ""),
                        stage4_confidence=getattr(j, "confidence", 0.0),
                        stage4_reason=getattr(j, "reason", f"policy_evaluation_error: {e}"),
                        stage4_model=getattr(j, "model", "unknown"),
                        decision=Decision.INSUFFICIENT_EVIDENCE,
                        processing_status=ProcessingStatus.INVALID_JUDGMENT,
                        score=None,
                        evidence_references=(),
                        counter_evidence_references=(),
                        missing_information=(f"policy_evaluation_error: {e}",),
                        policy_rules_applied=("policy-error",),
                        rationale=f"Policy evaluation error: {e}",
                    )
                decisions.append(rec)

            elif cid in failure_by_id:
                f = failure_by_id[cid]
                rec = DecisionRecord.from_failure(
                    candidate_id=cid,
                    service_a=obs.service_a,
                    service_b=obs.service_b,
                    resource=obs.resource,
                    resource_type=obs.resource_type,
                    resource_identity=obs.normalized_identity,
                    resolution_status=obs.resolution_status,
                    identity_strength=obs.identity_strength,
                    failure=f,
                    evidence_package=obs,
                )
                decisions.append(rec)

            else:
                # No judgment and no failure — missing
                rec = DecisionRecord(
                    candidate_id=cid,
                    service_a=obs.service_a,
                    service_b=obs.service_b,
                    resource=obs.resource,
                    resource_type=obs.resource_type,
                    resource_identity=obs.normalized_identity,
                    resolution_status=obs.resolution_status,
                    identity_strength=obs.identity_strength,
                    stage4_verdict="",
                    stage4_confidence=0.0,
                    stage4_reason="No judgment returned for this candidate",
                    stage4_model="missing",
                    decision=Decision.INSUFFICIENT_EVIDENCE,
                    processing_status=ProcessingStatus.MISSING_JUDGMENT,
                    score=None,
                    evidence_references=(),
                    counter_evidence_references=(),
                    missing_information=("no_judgment_returned",),
                    policy_rules_applied=("missing-judgment",),
                    rationale="No Stage 4 judgment was returned for this candidate.",
                )
                decisions.append(rec)

    return DecisionModel(decisions)


def _candidates_conflict(pkg1: EvidencePackage, pkg2: EvidencePackage) -> bool:
    """Check if two evidence packages represent conflicting resource identities."""
    # Different normalized identities for same resource type
    if (pkg1.resource_type == pkg2.resource_type
            and pkg1.normalized_identity
            and pkg2.normalized_identity
            and pkg1.normalized_identity != pkg2.normalized_identity):
        return True
    # Different volumes
    if (pkg1.resource_type == "named_volume"
            and pkg2.resource_type == "named_volume"
            and pkg1.resource != pkg2.resource):
        return True
    return False


def _conflict_description(pkg1: EvidencePackage, pkg2: EvidencePackage) -> str:
    """Generate a human-readable description of the conflict between two evidence packages."""
    if (pkg1.resource_type == pkg2.resource_type
            and pkg1.normalized_identity
            and pkg2.normalized_identity
            and pkg1.normalized_identity != pkg2.normalized_identity):
        return f"different resource identities: {pkg1.normalized_identity} vs {pkg2.normalized_identity}"
    if (pkg1.resource_type == "named_volume"
            and pkg2.resource_type == "named_volume"
            and pkg1.resource != pkg2.resource):
        return f"different named volumes: {pkg1.resource} vs {pkg2.resource}"
    return f"conflicting evidence between {pkg1.resource} and {pkg2.resource}"