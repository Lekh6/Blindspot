"""Tests for Stage 5: Deterministic Dependency Decision Engine."""

from typing import Optional

from blindspot.context_judge import CandidateJudgment, JudgmentFailure
from blindspot.decision import (
    DECISION_SCHEMA_VERSION,
    POLICY_VERSION,
    Decision,
    DecisionModel,
    DecisionRecord,
    ProcessingStatus,
    build_decision_model,
)
from blindspot.filtering import EvidencePackage


def _mock_judgment(
    candidate_id: str,
    verdict: str = "meaningful",
    confidence: float = 0.9,
    reason: str = "test reason",
) -> CandidateJudgment:
    return CandidateJudgment(
        candidate_id=candidate_id,
        verdict=verdict,
        confidence=confidence,
        reason=reason,
        supporting_evidence=(f"candidate:{candidate_id}",),
        missing_information=(),
        model="mock",
    )


def _mock_evidence(
    service_a: str = "svc_a",
    service_b: str = "svc_b",
    resource: str = "DB_HOST",
    resource_type: str = "env_var",
    value: str = "postgres",
    normalized_identity: str = "postgresql|postgres|5432|db",
    resolution_status: str = "internal",
    identity_strength: str = "exact",
    generic_variable: bool = False,
    candidate_id: Optional[str] = None,
) -> EvidencePackage:
    return EvidencePackage(
        service_a=service_a,
        service_b=service_b,
        resource=resource,
        resource_type=resource_type,
        value=value,
        evidence=f"test evidence for {resource}",
        candidate_id=candidate_id or f"{service_a}/{service_b}/{resource}",
        normalized_identity=normalized_identity,
        resolution_status=resolution_status,
        identity_strength=identity_strength,
        resource_protocol="postgresql",
        generic_variable=generic_variable,
        same_value=True,
        different_values=False,
    )


# ---- DecisionRecord creation ----

def test_decision_record_from_candidate_judgment_strong():
    """Test DecisionRecord creation for strong positive case (exact + meaningful)."""
    judgment = _mock_judgment("cid-1", verdict="meaningful", confidence=0.95)
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.POTENTIAL_DEPENDENCY
    assert rec.score is not None and rec.score >= 0.85
    assert "accept-exact-meaningful-high-confidence" in rec.policy_rules_applied
    assert rec.processing_status == ProcessingStatus.OK
    assert rec.stage4_verdict == "meaningful"
    assert rec.stage4_confidence == 0.95


def test_decision_record_from_candidate_judgment_coincidental():
    """Test DecisionRecord for coincidental verdict -> INSUFFICIENT_EVIDENCE."""
    judgment = _mock_judgment("cid-2", verdict="coincidental", confidence=0.3)
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-2",
        service_a="svc_a",
        service_b="svc_b",
        resource="PORT",
        resource_type="env_var",
        resource_identity=None,
        resolution_status="unresolved",
        identity_strength="unknown",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.INSUFFICIENT_EVIDENCE
    assert rec.score is None
    assert "reject-coincidental" in rec.policy_rules_applied
    assert "stage4_verdict:coincidental" in rec.counter_evidence_references


def test_decision_record_from_candidate_judgment_uncertain():
    """Test DecisionRecord for uncertain verdict -> REVIEW."""
    judgment = _mock_judgment("cid-3", verdict="uncertain", confidence=0.4)
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-3",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.REVIEW
    assert "review-uncertain-verdict" in rec.policy_rules_applied
    assert "stage4_verdict:uncertain" in rec.missing_information


def test_decision_record_from_candidate_judgment_generic():
    """Test DecisionRecord for generic variable -> INSUFFICIENT_EVIDENCE."""
    judgment = _mock_judgment("cid-4", verdict="meaningful", confidence=0.8)
    evidence = _mock_evidence(resource="PORT", value="8000", generic_variable=True)

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-4",
        service_a="svc_a",
        service_b="svc_b",
        resource="PORT",
        resource_type="env_var",
        resource_identity=None,
        resolution_status="unresolved",
        identity_strength="unknown",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.INSUFFICIENT_EVIDENCE
    assert "reject-generic-unresolved" in rec.policy_rules_applied
    assert "resolved_resource_identity" in rec.missing_information


def test_decision_record_from_candidate_judgment_named_volume():
    """Test DecisionRecord for named volume -> POTENTIAL_DEPENDENCY."""
    judgment = _mock_judgment("cid-5", verdict="meaningful", confidence=0.9)
    evidence = _mock_evidence(
        resource="shared-data",
        resource_type="named_volume",
        value=None,
        normalized_identity="named_volume|shared-data",
        resolution_status="internal",
        identity_strength="exact",
    )

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-5",
        service_a="svc_a",
        service_b="svc_b",
        resource="shared-data",
        resource_type="named_volume",
        resource_identity="named_volume|shared-data",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.POTENTIAL_DEPENDENCY
    assert "accept-named-volume-meaningful" in rec.policy_rules_applied


def test_decision_record_from_candidate_judgment_meaningful_low_confidence_unresolved():
    """Test meaningful verdict but unresolved with low confidence -> REVIEW."""
    judgment = _mock_judgment("cid-6", verdict="meaningful", confidence=0.5)
    evidence = _mock_evidence(
        resolution_status="partial",
        identity_strength="config",
    )

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-6",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|${HOST}||${DB}",
        resolution_status="partial",
        identity_strength="config",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.REVIEW
    assert "review-meaningful-low-confidence-unresolved" in rec.policy_rules_applied
    assert "resolution_status:partial" in rec.missing_information
    assert "low_confidence" in rec.missing_information


def test_decision_record_from_candidate_judgment_conflicting_evidence():
    """Test conflicting evidence -> REVIEW."""
    judgment = _mock_judgment("cid-7", verdict="meaningful", confidence=0.85)
    evidence = _mock_evidence()
    conflicting = ("different logical databases: 'db1' vs 'db2'",)

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-7",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db1",
        resolution_status="external_confirmed",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
        conflicting_evidence=conflicting,
    )

    assert rec.decision == Decision.REVIEW
    assert "review-conflicting-evidence" in rec.policy_rules_applied
    assert "different logical databases" in rec.counter_evidence_references[0]


def test_decision_record_from_failure():
    """Test DecisionRecord from JudgmentFailure."""
    failure = JudgmentFailure(
        candidate_id="cid-8",
        error_type="provider_error",
        message="API timeout",
    )
    evidence = _mock_evidence()

    rec = DecisionRecord.from_failure(
        candidate_id="cid-8",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        failure=failure,
        evidence_package=evidence,
    )

    assert rec.decision == Decision.INSUFFICIENT_EVIDENCE
    assert rec.processing_status == ProcessingStatus.OPERATIONAL_FAILURE
    assert rec.stage4_verdict == ""
    assert rec.stage4_confidence == 0.0
    assert "API timeout" in rec.stage4_reason
    assert "failure-handling" in rec.policy_rules_applied


def test_decision_record_schema_version():
    """Test that DecisionRecord includes schema and policy versions."""
    judgment = _mock_judgment("cid-1")
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    assert rec.decision_schema_version == DECISION_SCHEMA_VERSION
    assert rec.policy_version == POLICY_VERSION

    d = rec.to_dict()
    assert d["decision_schema_version"] == DECISION_SCHEMA_VERSION
    assert d["policy_version"] == POLICY_VERSION

    # Model should not be in external dict
    assert "model" not in d
    assert "_log" not in d

    # But should be in log dict
    log_d = rec.to_log_dict()
    assert "_log" in log_d
    assert "cache_key" in log_d["_log"]
    assert "created_at" in log_d["_log"]


def test_decision_record_cache_key_deterministic():
    """Test that cache key is deterministic for identical inputs."""
    judgment1 = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    judgment2 = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    evidence1 = _mock_evidence()
    evidence2 = _mock_evidence()

    rec1 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment1,
        evidence_package=evidence1,
    )

    rec2 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment2,
        evidence_package=evidence2,
    )

    assert rec1._cache_key == rec2._cache_key


# ---- DecisionModel ----

def test_decision_model_potential_dependencies_only():
    """Test DecisionModel.potential_dependencies_only()."""
    judgment1 = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    judgment2 = _mock_judgment("cid-2", verdict="coincidental", confidence=0.3)
    judgment3 = _mock_judgment("cid-3", verdict="uncertain", confidence=0.4)
    evidence = _mock_evidence()

    rec1 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1", service_a="a", service_b="b", resource="DB",
        resource_type="env_var", resource_identity="postgresql|host|5432|db",
        resolution_status="internal", identity_strength="exact",
        judgment=judgment1, evidence_package=evidence
    )
    rec2 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-2", service_a="a", service_b="c", resource="PORT",
        resource_type="env_var", resource_identity=None,
        resolution_status="unresolved", identity_strength="unknown",
        judgment=judgment2, evidence_package=evidence
    )
    rec3 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-3", service_a="b", service_b="c", resource="DB",
        resource_type="env_var", resource_identity="postgresql|host|5432|db",
        resolution_status="internal", identity_strength="exact",
        judgment=judgment3, evidence_package=evidence
    )

    model = DecisionModel(decisions=[rec1, rec2, rec3])
    potential = model.potential_dependencies_only()

    assert len(potential.decisions) == 1
    assert potential.decisions[0].candidate_id == "cid-1"


def test_decision_model_deterministic_ordering():
    """Test DecisionModel ordering is deterministic."""
    judgment = _mock_judgment("cid", verdict="meaningful", confidence=0.9)
    evidence = _mock_evidence()

    rec1 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1", service_a="a", service_b="b", resource="DB",
        resource_type="env_var", resource_identity="postgresql|host|5432|db",
        resolution_status="internal", identity_strength="exact",
        judgment=judgment, evidence_package=evidence
    )
    rec2 = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-2", service_a="a", service_b="c", resource="DB",
        resource_type="env_var", resource_identity="postgresql|host|5432|db",
        resolution_status="internal", identity_strength="exact",
        judgment=judgment, evidence_package=evidence
    )

    model1 = DecisionModel(decisions=[rec2, rec1])
    model2 = DecisionModel(decisions=[rec1, rec2])

    # Both should be sorted the same way
    assert [d.candidate_id for d in model1.decisions] == ["cid-1", "cid-2"]
    assert [d.candidate_id for d in model2.decisions] == ["cid-1", "cid-2"]


# ---- build_decision_model ----

def test_build_decision_model_strong_and_coincidental():
    """Test build_decision_model with mixed judgments."""
    from blindspot.aggregation import GroupedEvidencePackage

    judgment1 = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    judgment2 = _mock_judgment("cid-2", verdict="coincidental", confidence=0.3)

    evidence1 = _mock_evidence(
        service_a="svc_a", service_b="svc_b", resource="DB_HOST",
        candidate_id="cid-1",
        normalized_identity="postgresql|postgres|5432|db",
        resolution_status="internal", identity_strength="exact"
    )
    evidence2 = _mock_evidence(
        service_a="svc_a", service_b="svc_c", resource="PORT",
        candidate_id="cid-2",
        normalized_identity=None,
        resolution_status="unresolved", identity_strength="unknown",
        generic_variable=True
    )

    grouped = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|postgres|5432|db",
        resource_identity="postgresql|postgres|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="internal",
        identity_strength="exact",
        services=("svc_a", "svc_b", "svc_c"),
        observations=(evidence1, evidence2),
        configuration_evidence={"svc_a": ("DB_HOST",), "svc_b": ("DB_HOST",), "svc_c": ("PORT",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=2,
        service_count=3,
        observation_resources=("DB_HOST", "PORT"),
    )

    contextual_results = [(grouped, [judgment1, judgment2], [])]
    model = build_decision_model(contextual_results)

    assert len(model.decisions) == 2
    # First should be POTENTIAL_DEPENDENCY
    d1 = next(d for d in model.decisions if d.candidate_id == "cid-1")
    assert d1.decision == Decision.POTENTIAL_DEPENDENCY
    # Second should be INSUFFICIENT_EVIDENCE
    d2 = next(d for d in model.decisions if d.candidate_id == "cid-2")
    assert d2.decision == Decision.INSUFFICIENT_EVIDENCE


def test_build_decision_model_missing_judgment():
    """Test build_decision_model handles missing judgment."""
    from blindspot.aggregation import GroupedEvidencePackage

    evidence = _mock_evidence(
        service_a="svc_a", service_b="svc_b", resource="DB_HOST",
        candidate_id="cid-1",
    )

    grouped = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|host|5432|db",
        resource_identity="postgresql|host|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="internal",
        identity_strength="exact",
        services=("svc_a", "svc_b"),
        observations=(evidence,),
        configuration_evidence={"svc_a": ("DB_HOST",), "svc_b": ("DB_HOST",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=1,
        service_count=2,
        observation_resources=("DB_HOST",),
    )

    # No judgments, no failures
    contextual_results = [(grouped, [], [])]
    model = build_decision_model(contextual_results)

    assert len(model.decisions) == 1
    rec = model.decisions[0]
    assert rec.decision == Decision.INSUFFICIENT_EVIDENCE
    assert rec.processing_status == ProcessingStatus.MISSING_JUDGMENT
    assert "no_judgment_returned" in rec.missing_information


def test_build_decision_model_failure():
    """Test build_decision_model handles JudgmentFailure."""
    from blindspot.aggregation import GroupedEvidencePackage

    failure = JudgmentFailure(
        candidate_id="cid-1",
        error_type="timeout",
        message="LLM timeout",
    )
    evidence = _mock_evidence(
        service_a="svc_a", service_b="svc_b", resource="DB_HOST",
        candidate_id="cid-1",
    )

    grouped = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|host|5432|db",
        resource_identity="postgresql|host|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="internal",
        identity_strength="exact",
        services=("svc_a", "svc_b"),
        observations=(evidence,),
        configuration_evidence={"svc_a": ("DB_HOST",), "svc_b": ("DB_HOST",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=1,
        service_count=2,
        observation_resources=("DB_HOST",),
    )

    contextual_results = [(grouped, [], [failure])]
    model = build_decision_model(contextual_results)

    assert len(model.decisions) == 1
    rec = model.decisions[0]
    assert rec.decision == Decision.INSUFFICIENT_EVIDENCE
    assert rec.processing_status == ProcessingStatus.OPERATIONAL_FAILURE


def test_build_decision_model_invalid_judgment():
    """Test build_decision_model handles policy evaluation errors gracefully."""
    from blindspot.aggregation import GroupedEvidencePackage
    from blindspot.context_judge import CandidateJudgment

    # Create a judgment that will cause an error in policy evaluation
    # Missing confidence attribute will cause AttributeError
    class BadJudgment:
        candidate_id = "cid-1"
        verdict = "meaningful"
        # confidence missing - will cause AttributeError
        reason = "test"
        supporting_evidence = ("candidate:cid-1",)
        missing_information = ()
        model = "mock"

    evidence = _mock_evidence(
        service_a="svc_a", service_b="svc_b", resource="DB_HOST",
        candidate_id="cid-1",
    )

    from blindspot.aggregation import GroupedEvidencePackage
    grouped = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|host|5432|db",
        resource_identity="postgresql|host|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="internal",
        identity_strength="exact",
        services=("svc_a", "svc_b"),
        observations=(evidence,),
        configuration_evidence={"svc_a": ("DB_HOST",), "svc_b": ("DB_HOST",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=1,
        service_count=2,
        observation_resources=("DB_HOST",),
    )

    contextual_results = [(grouped, [BadJudgment()], [])]
    model = build_decision_model(contextual_results)

    assert len(model.decisions) == 1
    rec = model.decisions[0]
    # Should handle attribute errors gracefully
    assert rec.processing_status == ProcessingStatus.INVALID_JUDGMENT
    assert "policy_evaluation_error" in rec.missing_information[0]


def test_decision_model_json_serialization():
    """Test DecisionModel JSON serialization."""
    judgment = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    model = DecisionModel(decisions=[rec])
    json_str = model.to_json()
    assert "cid-1" in json_str
    assert "potential_dependency" in json_str
    assert "internal" in json_str


def test_decision_model_log_list():
    """Test DecisionModel log list includes internal fields."""
    judgment = _mock_judgment("cid-1", verdict="meaningful", confidence=0.9)
    evidence = _mock_evidence()

    rec = DecisionRecord.from_candidate_judgment(
        candidate_id="cid-1",
        service_a="svc_a",
        service_b="svc_b",
        resource="DB_HOST",
        resource_type="env_var",
        resource_identity="postgresql|postgres|5432|db",
        resolution_status="internal",
        identity_strength="exact",
        judgment=judgment,
        evidence_package=evidence,
    )

    model = DecisionModel(decisions=[rec])
    log_list = model.to_log_list()
    assert len(log_list) == 1
    assert "_log" in log_list[0]
    assert "cache_key" in log_list[0]["_log"]
    assert "created_at" in log_list[0]["_log"]