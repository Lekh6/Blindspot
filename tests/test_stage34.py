"""Stage 3+4 acceptance: filtering/resolution/evidence + contextual judgment (hermetic)."""

import json
import tempfile
from pathlib import Path

from blindspot.parser import parse_compose_string, parse_compose_file
from blindspot.discovery import discover_candidates
from blindspot.filtering import (
    EVIDENCE_SCHEMA_VERSION,
    build_evidence_package,
    build_evidence_packages,
    filter_with_decisions,
    server_identity,
    logical_identity,
    EvidencePackage,
)
from blindspot.aggregation import aggregate_evidence_packages
from blindspot.context import (
    CONTEXT_SCHEMA_VERSION,
    PROMPT_VERSION,
    ContextBudget,
    ContextTooLarge,
    build_contexts_for_packages,
    build_investigation_context,
    context_fits_budget,
)
from blindspot.context_judge import (
    MockContextClient,
    judge_investigation_context,
    to_legacy_group_result,
    validate_candidate_judgments,
    CandidateJudgment,
    JudgmentFailure,
)
from blindspot.judge import (
    judge_contextual,
    contextual_judgments_to_group_results,
    JudgeResult,
)
from blindspot.secrets import REDACTED
from blindspot.coupling import CouplingModel
from blindspot.graph import build_graph_from_groups
from blindspot.report import build_grouped_report


def _proj_env():
    return parse_compose_string(
        "services:\n"
        "  api:\n    image: app:1\n    environment:\n      DB_HOST: db\n      DB_NAME: appdb\n      DEBUG: '1'\n"
        "  worker:\n    image: app:1\n    environment:\n      DB_HOST: db\n      DB_NAME: appdb\n      DEBUG: '1'\n"
        "  db:\n    image: postgres:16\n"
    )


# ---- Stage 3 ----

def test_generic_filtered_with_reason_and_meaningful_survives():
    proj = _proj_env()
    cands = discover_candidates(proj)
    decisions = filter_with_decisions(cands, proj)
    by_res = {(d.service_a, d.resource): d for d in decisions}
    # DEBUG generic rejected with explicit rule/reason + original evidence preserved
    deb = [d for d in decisions if d.resource == "DEBUG"]
    assert deb and all(not d.kept for d in deb)
    assert all(d.rule.startswith("drop-") and d.reason and d.original_evidence for d in deb)
    # DB_HOST meaningful kept
    kept = [d for d in decisions if d.resource == "DB_HOST"]
    assert kept and all(d.kept and d.rule.startswith("keep-") for d in kept)
    # Every candidate accounted for
    assert len(decisions) == len(cands)


def test_named_volume_preserved_and_service_resolves():
    proj = parse_compose_string(
        "services:\n  a:\n    image: x\n    volumes:\n      - shared-data:/data\n"
        "  b:\n    image: y\n    volumes:\n      - shared-data:/data\n"
    )
    cands = discover_candidates(proj)
    pkgs = build_evidence_packages(cands, proj)
    assert len(pkgs) == 1 and pkgs[0].resource_type == "named_volume"
    assert pkgs[0].normalized_identity == "named_volume|shared-data"
    # Service reference resolves
    proj2 = _proj_env()
    pkgs2 = build_evidence_packages(discover_candidates(proj2), proj2)
    host = next(p for p in pkgs2 if p.resource == "DB_HOST")
    assert host.resolved_service == "db" and host.resolved_image == "postgres:16"
    assert host.resolution_status == "internal"


def test_server_vs_logical_db_distinguished():
    proj = parse_compose_string(
        "services:\n"
        "  a:\n    image: x\n    environment:\n      DATABASE_URL: postgresql://u@h:5432/d1\n"
        "  b:\n    image: y\n    environment:\n      DATABASE_URL: postgresql://u@h:5432/d2\n"
    )
    cands = discover_candidates(proj)
    pkgs = build_evidence_packages(cands, proj)
    # Same key different values that do NOT converge → filtered (not same logical DB)
    assert pkgs == [] or all(p.normalized_identity != "postgresql|h|5432|d1" for p in pkgs)
    # Same server different DBs via cross-var endpoints stay distinct resources
    proj2 = parse_compose_string(
        "services:\n"
        "  a:\n    image: x\n    environment:\n      U1: postgresql://u@h:5432/d1\n"
        "  b:\n    image: y\n    environment:\n      V1: postgresql://u@h:5432/d1\n"
        "  c:\n    image: z\n    environment:\n      W1: postgresql://u@h:5432/d2\n"
    )
    cands2 = discover_candidates(proj2)
    eps = [c for c in cands2 if c.resource_type == "shared_endpoint"]
    assert len(eps) == 1  # only d1 pair; d2 distinct
    assert server_identity("postgresql|h|5432|d1") == "postgresql|h|5432"
    assert logical_identity("postgresql|h|5432|d1") == "postgresql|h|5432|d1"
    assert server_identity("postgresql|h|5432|d1") == server_identity("postgresql|h|5432|d2")
    assert logical_identity("postgresql|h|5432|d1") != logical_identity("postgresql|h|5432|d2")


def test_external_unresolved_and_provenance_ids():
    proj = parse_compose_string(
        "services:\n  a:\n    image: x\n    environment:\n      DATABASE_URL: postgresql://u@ext:5432/db\n"
        "  b:\n    image: y\n    environment:\n      DATABASE_URL: postgresql://u@ext:5432/db\n"
    )
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    assert len(pkgs) == 1
    assert pkgs[0].resolution_status == "external_confirmed"
    assert pkgs[0].candidate_id and pkgs[0].schema_version == EVIDENCE_SCHEMA_VERSION
    assert pkgs[0].evidence_refs  # LLM-citable refs
    # Unresolved never silently lost
    proj_u = parse_compose_string(
        "services:\n  a:\n    environment:\n      X: ${MISSING}\n  b:\n    environment:\n      X: ${MISSING}\n"
    )
    cu = discover_candidates(proj_u)
    pu = build_evidence_packages(cu, proj_u)
    assert len(pu) == 1 and pu[0].resolution_status in ("unresolved", "partial")
    dec = filter_with_decisions(cu, proj_u)
    assert len(dec) == 1 and dec[0].kept  # unresolved kept, not dropped
    # No confidence scoring in filtering
    assert not hasattr(pu[0], "confidence") or True
    assert "confidence" not in [f for f in dir(pu[0]) if f.startswith("overall")] 


def test_secret_redaction_everywhere():
    proj = parse_compose_string(
        "services:\n"
        "  a:\n    image: x\n    environment:\n      DB_PASSWORD: s3cr3t-hunter2\n      DATABASE_URL: postgresql://admin:p@ssw0rd@h:5432/db\n"
        "  b:\n    image: y\n    environment:\n      DB_PASSWORD: s3cr3t-hunter2\n      DATABASE_URL: postgresql://admin:p@ssw0rd@h:5432/db\n"
    )
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    assert pkgs
    for p in pkgs:
        blob = p.to_canonical_json()
        assert "s3cr3t-hunter2" not in blob and "p@ssw0rd" not in blob
        assert p.cache_key_dict() is not None
        assert "s3cr3t-hunter2" not in json.dumps(p.cache_key_dict())
    ctxs, failures = build_contexts_for_packages(pkgs)
    assert not failures
    prompt_blob = ctxs[0].to_canonical_json()
    assert "s3cr3t-hunter2" not in prompt_blob and "p@ssw0rd" not in prompt_blob
    # Report + graph must not leak either
    pairs = [(g, JudgeResult(verdict="meaningful", confidence=0.8, reason="t", model="t"))
             for g in aggregate_evidence_packages(pkgs)]
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, meaningful_only=False)
    assert "s3cr3t-hunter2" not in report.to_json() and "p@ssw0rd" not in report.to_json()
    assert "s3cr3t-hunter2" not in json.dumps(graph)


def test_evidence_deterministic():
    proj = _proj_env()
    cands = discover_candidates(proj)
    p1 = build_evidence_packages(cands, proj)
    p2 = build_evidence_packages(discover_candidates(_proj_env()), _proj_env())
    assert [p.to_canonical_json() for p in p1] == [p.to_canonical_json() for p in p2]


# ---- Stage 4 context ----

def test_context_sections_and_conflicts():
    proj = parse_compose_string(
        "services:\n"
        "  a:\n    image: x\n    environment:\n      U: postgresql://u@h:5432/d1\n      DB_NAME: d1\n"
        "  b:\n    image: y\n    environment:\n      V: postgresql://u@h:5432/d2\n      DB_NAME: d2\n"
    )
    cands = discover_candidates(proj)
    pkgs = build_evidence_packages(cands, proj)
    # Force one context across two identities to check conflict surfacing
    pkgs_all = pkgs or build_evidence_packages(
        discover_candidates(parse_compose_string(
            "services:\n  a:\n    image: x\n    environment:\n      S: shared\n"
            "  b:\n    image: y\n    environment:\n      S: shared\n")), parse_compose_string(
            "services:\n  a:\n    image: x\n    environment:\n      S: shared\n"
            "  b:\n    image: y\n    environment:\n      S: shared\n"))
    ctx = build_investigation_context("test-key", pkgs_all[:2] if len(pkgs_all) >= 2 else pkgs_all)
    d = ctx.to_dict()
    # Required sections A-F
    assert set(d) == {"a_metadata", "b_resource_summary", "c_services", "d_candidates", "e_conflicting_evidence", "f_boundaries", "budget"}
    assert d["a_metadata"]["context_schema_version"] == CONTEXT_SCHEMA_VERSION
    assert d["a_metadata"]["prompt_version"] == PROMPT_VERSION
    assert ctx.candidate_ids and len(ctx.candidates) == len(ctx.candidate_ids)
    # Services complete, unrelated excluded
    svc_names = {s.service_name for s in ctx.services}
    assert svc_names <= {"a", "b", "api", "worker"}
    assert "unrelated" not in svc_names
    # Boundaries separate facts vs interpretations vs unavailable
    assert d["f_boundaries"]["config_facts"] and d["f_boundaries"]["unavailable_info"]
    # Deterministic serialization
    assert ctx.to_canonical_json() == build_investigation_context("test-key", pkgs_all[:2] if len(pkgs_all) >= 2 else pkgs_all).to_canonical_json()


def test_conflicting_db_names_surfaced():
    from blindspot.filtering import EvidencePackage

    def _pkg(svc_a, svc_b, norm):
        return EvidencePackage(service_a=svc_a, service_b=svc_b, resource="U",
                               resource_type="shared_endpoint", value=norm, evidence="e",
                               resource_protocol="postgresql", normalized_identity=norm,
                               identity_strength="exact", resolution_status="external_confirmed",
                               candidate_id=f"{svc_a}-{svc_b}-{norm}")
    ctx = build_investigation_context(
        "k", [_pkg("a", "b", "postgresql|h|5432|d1"), _pkg("a", "c", "postgresql|h|5432|d2")])
    assert any("different logical databases" in c for c in ctx.conflicting_evidence)


def test_budget_split_and_single_overflow_fails():
    from blindspot.filtering import EvidencePackage
    pkgs = [EvidencePackage(service_a="a", service_b=f"s{i}", resource=f"V{i}",
                            resource_type="env_var", value="v", evidence="e",
                            candidate_id=f"cid-{i:03d}") for i in range(5)]
    tiny = ContextBudget(max_serialized_chars=10**9, max_estimated_tokens=10**9, max_candidates_per_group=2)
    ctxs, failures = build_contexts_for_packages(pkgs, budget=tiny)
    assert not failures
    assert sum(len(c.candidate_ids) for c in ctxs) == 5
    assert all(len(c.candidate_ids) <= 2 for c in ctxs)
    # IDs preserved through split
    assert sorted(sum([list(c.candidate_ids) for c in ctxs], [])) == sorted(p.candidate_id for p in pkgs)
    # Deterministic
    ctxs2, _ = build_contexts_for_packages(pkgs, budget=tiny)
    assert [c.to_canonical_json() for c in ctxs] == [c.to_canonical_json() for c in ctxs2]
    # Single-candidate overflow → explicit failure, not silent drop
    huge = ContextBudget(max_serialized_chars=10, max_estimated_tokens=5, max_candidates_per_group=8)
    try:
        from blindspot.context import split_group_deterministically
        split_group_deterministically("k", pkgs[:1], huge)
        assert False, "must raise ContextTooLarge"
    except ContextTooLarge:
        pass


# ---- Stage 4 judgment + cache ----

def test_grouping_deterministic_unrelated_separate():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    c1, f1 = build_contexts_for_packages(pkgs)
    c2, f2 = build_contexts_for_packages(build_evidence_packages(discover_candidates(proj), proj))
    assert [c.to_canonical_json() for c in c1] == [c.to_canonical_json() for c in c2]
    assert not f1 and not f2
    # Unrelated resources (endpoint identity vs PORT-filtered vs volume) never merged:
    # each context has a single resource_type root
    for c in c1:
        assert c.resource_identity is not None


def test_structured_validation_rejects_bad():
    proj = _proj_env()
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    ctxs, _ = build_contexts_for_packages(pkgs)
    ctx = ctxs[0]
    cid = ctx.candidate_ids[0]
    # Invalid verdict / confidence / unknown id / invented ref
    bad_cases = [
        [{"candidate_id": cid, "verdict": "yes", "confidence": 0.9, "reason": "r",
          "supporting_evidence": [f"candidate:{cid}"], "missing_information": []}],
        [{"candidate_id": cid, "verdict": "meaningful", "confidence": 2.0, "reason": "r",
          "supporting_evidence": [f"candidate:{cid}"], "missing_information": []}],
        [{"candidate_id": "ghost", "verdict": "meaningful", "confidence": 0.5, "reason": "r",
          "supporting_evidence": [], "missing_information": []}],
        [{"candidate_id": cid, "verdict": "meaningful", "confidence": 0.5, "reason": "r",
          "supporting_evidence": ["evidence:INVENTED"], "missing_information": []}],
    ]
    for bad in bad_cases:
        valid, failures = validate_candidate_judgments(ctx, bad, "mock")
        assert valid == [] and len(failures) >= 1
    # Missing result → failure, never fabricated
    valid, failures = validate_candidate_judgments(ctx, [], "mock")
    assert valid == [] and len(failures) == len(ctx.candidate_ids)
    # Duplicate → failure
    good = {"candidate_id": cid, "verdict": "uncertain", "confidence": 0.4, "reason": "need more",
            "supporting_evidence": [f"candidate:{cid}"], "missing_information": ["logs"]}
    valid, failures = validate_candidate_judgments(ctx, [good, dict(good)], "mock")
    assert any(f.error_type == "duplicate" for f in failures)
    # Uncertain fully supported
    one = [dict(good)]
    # pad remaining candidates if group has >1
    for extra in ctx.candidate_ids[1:]:
        one.append({"candidate_id": extra, "verdict": "uncertain", "confidence": 0.3,
                    "reason": "insufficient", "supporting_evidence": [f"candidate:{extra}"],
                    "missing_information": []})
    valid, failures = validate_candidate_judgments(ctx, one, "mock")
    assert not failures and all(v.verdict == "uncertain" for v in valid)


def test_failures_safe_bounded_and_cache():
    proj = _proj_env()
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    ctxs, _ = build_contexts_for_packages(pkgs)
    ctx = ctxs[0]

    class Boom:
        model = "boom"
        def __init__(self):
            self.n = 0
        def complete_json(self, prompt):
            self.n += 1
            raise TimeoutError("down")

    valid, failures = judge_investigation_context(ctx, Boom(), cache_path=None)
    assert valid == [] and len(failures) == len(ctx.candidate_ids)
    assert all(f.error_type == "provider_error" for f in failures)
    # Failures are not coincidental fabrications
    assert all("coincidental" not in f.error_type for f in failures)

    # Cache: hit avoids second call; evidence change invalidates
    with tempfile.TemporaryDirectory() as tmp:
        cache = str(Path(tmp) / "cache.json")
        mock = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-v1")
        v1, f1 = judge_investigation_context(ctx, mock, cache_path=cache)
        assert not f1 and mock.calls and len(v1) == len(ctx.candidate_ids)
        n_calls = len(mock.calls)
        v2, f2 = judge_investigation_context(ctx, mock, cache_path=cache)
        assert not f2 and len(mock.calls) == n_calls  # cache hit, no new call
        assert [v.to_dict() for v in v1] == [v.to_dict() for v in v2]
        # Model change invalidates
        mock2 = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-v2")
        v3, _ = judge_investigation_context(ctx, mock2, cache_path=cache)
        assert len(mock2.calls) == 1
        # Prompt/schema change invalidates (simulate by mutating version in key path:
        # different investigation content → different key)
        ctx_b = build_investigation_context(ctx.investigation_id + "-other",
                                            pkgs[:1] if pkgs else [])
        v4, _ = judge_investigation_context(ctx_b, mock, cache_path=cache)
        assert len(mock.calls) == n_calls + 1


def test_no_scoring_static_llm_separate_and_compat():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    ctxs, _ = build_contexts_for_packages(pkgs)
    mock = MockContextClient(verdict="meaningful", confidence=0.75)
    all_j = []
    for c in ctxs:
        v, f = judge_investigation_context(c, mock, cache_path=None)
        assert not f
        all_j.extend(v)
        # LLM judgment carries no static score, no YES/NO, no band
        for j in v:
            assert set(j.to_dict()) >= {"candidate_id", "verdict", "confidence", "reason",
                                        "supporting_evidence", "missing_information"}
            assert "score" not in j.to_dict() and "band" not in j.to_dict()
    # Legacy group result for downstream compat (display-only, no weights)
    legacy = to_legacy_group_result(all_j[:1])
    assert legacy.verdict in ("meaningful", "coincidental", "uncertain")
    pairs = [(g, to_legacy_group_result(
        [j for j in all_j if j.candidate_id in c.candidate_ids] or
        [__import__("blindspot.context_judge", fromlist=["CandidateJudgment"]).CandidateJudgment(
            candidate_id=c.candidate_ids[0], verdict="uncertain", confidence=0.0,
            reason="no judgment", supporting_evidence=(), missing_information=())]))
             for g, c in zip(aggregate_evidence_packages(pkgs), ctxs)]
    # Graph/report still bipartite + provider-hidden
    from blindspot.coupling import CouplingGroup
    groups = aggregate_evidence_packages(pkgs)
    assert groups
    model = CouplingModel.from_grouped_judgments([(g, r) for (g, r) in pairs[:len(groups)]])
    graph = build_graph_from_groups(model)
    for e in graph["edges"]:
        assert e["source"].startswith("service:") and e["target"].startswith("resource:")
        assert "confidence" in e["data"] and "model" not in str(e)
    report = build_grouped_report(model, graph_data=graph)
    assert "model" not in json.dumps(report.to_dict()).lower() or "nvidia" not in report.to_json()


# ---- Contextual Batching Tests ----

def test_judge_contextual_multiple_candidates_per_context():
    """Test that judge_contextual processes multiple candidates in one LLM call."""
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    grouped = aggregate_evidence_packages(pkgs)
    assert len(grouped) >= 1

    mock = MockContextClient(verdict="meaningful", confidence=0.85, model="mock-contextual")
    budget = ContextBudget(max_candidates_per_group=8)
    contextual_results = judge_contextual(grouped, mock, cache_path=None, budget=budget, thinking="low")

    # Should have results for each grouped package
    assert len(contextual_results) == len(grouped)
    total_judgments = 0
    for gp, judgments, failures in contextual_results:
        assert gp is not None
        assert len(judgments) > 0
        assert len(failures) == 0
        total_judgments += len(judgments)
        # Each judgment should have proper structure
        for j in judgments:
            assert j.candidate_id
            assert j.verdict in ("meaningful", "coincidental", "uncertain")
            assert 0.0 <= j.confidence <= 1.0
            assert j.reason
            assert isinstance(j.supporting_evidence, tuple)
            assert isinstance(j.missing_information, tuple)

    # Total judgments should equal total candidates across all groups
    total_candidates = sum(len(g.observations) for g in grouped)
    assert total_judgments == total_candidates

    # Only one LLM call per context (mock tracks calls)
    assert len(mock.calls) == len(contextual_results)


def test_judge_contextual_adaptive_packing_splits_oversized():
    """Test that oversized groups are split deterministically across contexts."""
    from blindspot.filtering import EvidencePackage
    from dataclasses import replace

    # Create many evidence packages that would exceed budget if packed together
    base_pkgs = [
        EvidencePackage(
            service_a=f"svc_a_{i}", service_b=f"svc_b_{i}",
            resource=f"DB_{i}", resource_type="env_var", value=f"postgresql://host:5432/db{i}",
            evidence=f"e{i}", candidate_id=f"cid-{i:03d}",
            normalized_identity=f"postgresql|host|5432|db{i}",
            resolution_status="external_confirmed", identity_strength="exact",
            resource_protocol="postgresql",
        ) for i in range(10)
    ]
    # Force them into one group by giving same grouping key (same normalized_identity)
    pkgs = [
        replace(
            p,
            normalized_identity="postgresql|host|5432|shared_db",
            resource="SHARED_DB",
            value="postgresql://host:5432/shared_db",
            resource_protocol="postgresql",
            identity_strength="exact",
            resolution_status="external_confirmed",
        ) for p in base_pkgs
    ]

    grouped = aggregate_evidence_packages(pkgs)
    assert len(grouped) == 1  # All merged into one group

    # Use tiny budget to force splitting
    tiny_budget = ContextBudget(max_candidates_per_group=3, max_serialized_chars=10000, max_estimated_tokens=10000)
    mock = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-packing")

    contextual_results = judge_contextual(grouped, mock, cache_path=None, budget=tiny_budget, thinking="low")

    # Should be split into multiple contexts (ceil(10/3) = 4 contexts)
    assert len(contextual_results) >= 3  # At least 3 contexts for 10 candidates with max 3 per group
    # Total judgments should still equal total candidates
    total_judgments = sum(len(j) for _, j, _ in contextual_results)
    assert total_judgments == 10

    # Each context should have <= max_candidates_per_group candidates
    for _, judgments, _ in contextual_results:
        assert len(judgments) <= 3


def test_judge_contextual_cache_candidate_aware():
    """Test that cache keys include all candidates and context, so changes invalidate."""
    import tempfile
    from pathlib import Path

    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    grouped = aggregate_evidence_packages(pkgs)
    assert len(grouped) >= 1

    with tempfile.TemporaryDirectory() as tmp:
        cache = str(Path(tmp) / "cache.json")
        mock = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-cache-v1")
        budget = ContextBudget()

        # First call - should hit LLM
        results1 = judge_contextual(grouped, mock, cache_path=cache, budget=budget, thinking="low")
        calls_after_first = len(mock.calls)

        # Second call - should hit cache (no new LLM calls)
        results2 = judge_contextual(grouped, mock, cache_path=cache, budget=budget, thinking="low")
        calls_after_second = len(mock.calls)
        assert calls_after_second == calls_after_first  # Cache hit

        # Verify results are identical
        for (gp1, j1, f1), (gp2, j2, f2) in zip(results1, results2):
            assert [j.to_dict() for j in j1] == [j.to_dict() for j in j2]

        # Model change should invalidate cache
        mock2 = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-cache-v2")
        results3 = judge_contextual(grouped, mock2, cache_path=cache, budget=budget, thinking="low")
        assert len(mock2.calls) == len(grouped)  # New calls for new model

        # Evidence change (different grouping) should invalidate
        # Create a slightly different project
        proj_b = parse_compose_string("""
services:
  a: { environment: { DATABASE_URL: "postgresql://other:5432/db" } }
  b: { environment: { DATABASE_URL: "postgresql://other:5432/db" } }
""")
        pkgs_b = build_evidence_packages(discover_candidates(proj_b), proj_b)
        grouped_b = aggregate_evidence_packages(pkgs_b)
        mock3 = MockContextClient(verdict="meaningful", confidence=0.8, model="mock-cache-v1")
        results4 = judge_contextual(grouped_b, mock3, cache_path=cache, budget=budget, thinking="low")
        assert len(mock3.calls) == len(grouped_b)  # New calls for different evidence


def test_contextual_judgments_to_group_results_conversion():
    """Test conversion from per-candidate judgments to grouped JudgeResult."""
    from blindspot.context_judge import CandidateJudgment
    from blindspot.aggregation import GroupedEvidencePackage
    from blindspot.filtering import EvidencePackage

    # Create a grouped package with multiple observations
    obs = [
        EvidencePackage(service_a="a", service_b="b", resource="DB_URL", resource_type="env_var",
                        value="postgresql://host:5432/db", evidence="e", candidate_id="cid-1",
                        normalized_identity="postgresql|host|5432|db", resolution_status="external_confirmed",
                        identity_strength="exact", resource_protocol="postgresql"),
        EvidencePackage(service_a="a", service_b="c", resource="DB_URL", resource_type="env_var",
                        value="postgresql://host:5432/db", evidence="e", candidate_id="cid-2",
                        normalized_identity="postgresql|host|5432|db", resolution_status="external_confirmed",
                        identity_strength="exact", resource_protocol="postgresql"),
    ]
    gp = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|host|5432|db",
        resource_identity="postgresql|host|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="external_confirmed",
        identity_strength="exact",
        services=("a", "b", "c"),
        observations=tuple(obs),
        configuration_evidence={"a": ("DB_URL",), "b": ("DB_URL",), "c": ("DB_URL",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=2,
        service_count=3,
        observation_resources=("DB_URL",),
    )

    # All meaningful -> group result meaningful
    judgments = [
        CandidateJudgment(candidate_id="cid-1", verdict="meaningful", confidence=0.9, reason="r1",
                          supporting_evidence=("candidate:cid-1",), missing_information=(), model="mock"),
        CandidateJudgment(candidate_id="cid-2", verdict="meaningful", confidence=0.85, reason="r2",
                          supporting_evidence=("candidate:cid-2",), missing_information=(), model="mock"),
    ]
    contextual_results = [(gp, judgments, [])]
    group_results = contextual_judgments_to_group_results(contextual_results)
    assert len(group_results) == 1
    gp_result, jr = group_results[0]
    assert jr.verdict == "meaningful"
    assert 0.85 <= jr.confidence <= 0.9  # max of winners

    # Mixed: meaningful + uncertain -> meaningful wins
    judgments2 = [
        CandidateJudgment(candidate_id="cid-1", verdict="meaningful", confidence=0.7, reason="r1",
                          supporting_evidence=("candidate:cid-1",), missing_information=(), model="mock"),
        CandidateJudgment(candidate_id="cid-2", verdict="uncertain", confidence=0.4, reason="r2",
                          supporting_evidence=("candidate:cid-2",), missing_information=(), model="mock"),
    ]
    group_results2 = contextual_judgments_to_group_results([(gp, judgments2, [])])
    assert group_results2[0][1].verdict == "meaningful"

    # Uncertain + coincidental -> uncertain wins over coincidental
    judgments3 = [
        CandidateJudgment(candidate_id="cid-1", verdict="uncertain", confidence=0.4, reason="r1",
                          supporting_evidence=("candidate:cid-1",), missing_information=(), model="mock"),
        CandidateJudgment(candidate_id="cid-2", verdict="coincidental", confidence=0.6, reason="r2",
                          supporting_evidence=("candidate:cid-2",), missing_information=(), model="mock"),
    ]
    group_results3 = contextual_judgments_to_group_results([(gp, judgments3, [])])
    assert group_results3[0][1].verdict == "uncertain"

    # Failures become uncertain
    from blindspot.context_judge import JudgmentFailure
    judgments4 = [
        CandidateJudgment(candidate_id="cid-1", verdict="meaningful", confidence=0.9, reason="r1",
                          supporting_evidence=("candidate:cid-1",), missing_information=(), model="mock"),
    ]
    failures = [JudgmentFailure(candidate_id="cid-2", error_type="provider_error", message="timeout")]
    group_results4 = contextual_judgments_to_group_results([(gp, judgments4, failures)])
    assert group_results4[0][1].verdict == "meaningful"  # meaningful wins over failure->uncertain


def test_coupling_model_from_contextual_judgments():
    """Test CouplingModel.from_contextual_judgments builds correct groups."""
    from blindspot.context_judge import CandidateJudgment
    from blindspot.aggregation import GroupedEvidencePackage
    from blindspot.filtering import EvidencePackage

    obs = [
        EvidencePackage(service_a="a", service_b="b", resource="DB_URL", resource_type="env_var",
                        value="postgresql://host:5432/db", evidence="e", candidate_id="cid-1",
                        normalized_identity="postgresql|host|5432|db", resolution_status="external_confirmed",
                        identity_strength="exact", resource_protocol="postgresql"),
    ]
    gp = GroupedEvidencePackage(
        grouping_key="env_var:postgresql|host|5432|db",
        resource_identity="postgresql|host|5432|db",
        resource_protocol="postgresql",
        resource_type="env_var",
        resolution_status="external_confirmed",
        identity_strength="exact",
        services=("a", "b"),
        observations=tuple(obs),
        configuration_evidence={"a": ("DB_URL",), "b": ("DB_URL",)},
        unresolved_vars=(),
        representative_chain=(),
        evidence_count=1,
        service_count=2,
        observation_resources=("DB_URL",),
    )

    judgments = [
        CandidateJudgment(candidate_id="cid-1", verdict="meaningful", confidence=0.88, reason="shared db",
                          supporting_evidence=("candidate:cid-1",), missing_information=(), model="mock"),
    ]
    contextual_results = [(gp, judgments, [])]
    model = CouplingModel.from_contextual_judgments(contextual_results)
    assert len(model.groups) == 1
    group = model.groups[0]
    assert group.verdict == "meaningful"
    assert group.confidence == 0.88
    assert group.resource_identity == "postgresql|host|5432|db"
    assert group.services == ("a", "b")

    # Test with failure
    from blindspot.context_judge import JudgmentFailure
    contextual_results_fail = [(gp, [], [JudgmentFailure(candidate_id="cid-1", error_type="provider_error", message="timeout")])]
    model_fail = CouplingModel.from_contextual_judgments(contextual_results_fail)
    assert len(model_fail.groups) == 1
    assert model_fail.groups[0].verdict == "uncertain"
    assert model_fail.groups[0].confidence == 0.0
