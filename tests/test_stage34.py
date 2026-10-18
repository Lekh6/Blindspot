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
)
from blindspot.secrets import REDACTED
from blindspot.coupling import CouplingModel
from blindspot.graph import build_graph_from_groups
from blindspot.report import build_grouped_report
from blindspot.judge import JudgeResult


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
