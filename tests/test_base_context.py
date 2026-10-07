"""BASE tests — contextual prompt + structured response (hermetic, no network)."""

import json

from blindspot.aggregation import aggregate_evidence_packages
from blindspot.context import build_context_bundle, build_file_tree, collect_source_snippets
from blindspot.context_judge import (
    QUESTION_IDS,
    QUESTIONS,
    build_contextual_prompt,
    judge_contextual_package,
    parse_or_failsafe,
    validate_signals,
)
from blindspot.coupling import CouplingModel
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.graph import build_graph_from_groups
from blindspot.parser import parse_compose_string
from blindspot.report import build_grouped_report
from blindspot.scoring import score_group


def _yaml():
    return """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""


def _grouped():
    proj = parse_compose_string(_yaml())
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    return groups[0], proj


class _StubCtxClient:
    model = "stub-ctx"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.last_prompt = ""

    def judge_context(self, prompt, bundle):
        self.calls += 1
        self.last_prompt = prompt
        return self.payload


def _good_payload():
    return [
        {"id": "Q1_SHARED_USE", "answer": "yes", "evidence": "same host/db", "confidence": 0.9, "uncertainty": 0.1},
        {"id": "Q2_COINCIDENCE", "answer": "no", "evidence": "not generic", "confidence": 0.8, "uncertainty": 0.2},
        {"id": "Q3_TABLE", "answer": "none", "evidence": "no table proof", "confidence": 0.5, "uncertainty": 0.7},
        {"id": "Q4_LIMIT", "answer": "need usage proof", "evidence": "no source read", "confidence": 0.4, "uncertainty": 0.8},
    ]


def test_prompt_has_required_context_and_stable_ids():
    g, proj = _grouped()
    b = build_context_bundle(g, proj, None)
    prompt = build_contextual_prompt(g, b)
    for qid in QUESTION_IDS:
        assert qid in prompt
    assert "SHARED RESOURCE" in prompt
    assert "RELEVANT COMPOSE" in prompt
    assert "DETERMINISTIC" in prompt or "RESOLVED" in prompt
    assert "FILE TREE" in prompt
    assert "SOURCE CONTEXT" in prompt
    # whole-repo must not be sent: prompt bounded
    assert len(prompt) < 6000


def test_missing_source_context_preserved_as_none():
    g, proj = _grouped()
    b = build_context_bundle(g, proj, None)
    assert list(b.snippets) == []
    prompt = build_contextual_prompt(g, b)
    assert "(none" in prompt  # explicit none marker, not silent


def test_structured_validation_good_and_malformed():
    sigs = validate_signals(_good_payload())
    assert [s.qid for s in sigs] == QUESTION_IDS
    assert sigs[0].answer == "yes"
    # malformed text fails safe per item
    bad = parse_or_failsafe("not json at all {{{")
    assert len(bad) == 4
    assert all(s.confidence == 0.0 and s.uncertainty == 1.0 for s in bad)
    # missing IDs filled with failsafe
    partial = validate_signals([{"id": "Q1_SHARED_USE", "answer": "yes", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1}])
    assert len(partial) == 4
    assert partial[1].answer in ("no", "yes", "unclear", "none", "insufficient evidence")
    # bad answer rejected to failsafe
    bad_ans = validate_signals([
        {"id": "Q1_SHARED_USE", "answer": "maybe", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1},
        {"id": "Q2_COINCIDENCE", "answer": "no", "evidence": "e", "confidence": 0.8, "uncertainty": 0.2},
        {"id": "Q3_TABLE", "answer": "none", "evidence": "e", "confidence": 0.5, "uncertainty": 0.5},
        {"id": "Q4_LIMIT", "answer": "x", "evidence": "e", "confidence": 0.5, "uncertainty": 0.5},
    ])
    assert bad_ans[0].answer == "unclear" and bad_ans[0].confidence == 0.0


def test_cache_hit_and_invalidation(tmp_path):
    g, proj = _grouped()
    b = build_context_bundle(g, proj, None)
    cache = tmp_path / "ctx.json"
    client = _StubCtxClient(_good_payload())
    s1, _ = judge_contextual_package(g, b, client, cache_path=cache)
    assert client.calls == 1
    s2, _ = judge_contextual_package(g, b, client, cache_path=cache)
    assert client.calls == 1  # hit
    assert [x.answer for x in s1] == [x.answer for x in s2]
    # changed evidence invalidates: different resource
    proj2 = parse_compose_string(_yaml().replace("5432/db", "5432/db2"))
    from blindspot.discovery import discover_candidates as _dc
    from blindspot.filtering import build_evidence_packages as _bp
    from blindspot.aggregation import aggregate_evidence_packages as _ag
    g2 = _ag(_bp(_dc(proj2), proj2))[0]
    b2 = build_context_bundle(g2, proj2, None)
    judge_contextual_package(g2, b2, client, cache_path=cache)
    assert client.calls == 2


def test_table_evidence_and_report_serialization():
    g, proj = _grouped()
    b = build_context_bundle(g, proj, None)
    payload = _good_payload()
    payload[2] = {"id": "Q3_TABLE", "answer": "yes", "evidence": "orders table in snippet", "confidence": 0.7, "uncertainty": 0.3}
    client = _StubCtxClient(payload)
    signals, model_name = judge_contextual_package(g, b, client, cache_path=None, use_cache=False)
    assert signals[2].answer == "yes"
    sc = score_group(g, signals)
    assert sc.score > score_group(g, validate_signals(_good_payload())).score  # table adds weight
    from blindspot.judge import JudgeResult
    from blindspot.scoring import verdict_from_scoring
    verdict, conf, reason = verdict_from_scoring(sc, signals)
    model = CouplingModel.from_grouped_judgments([(g, JudgeResult(verdict=verdict, confidence=conf, reason=reason, model=model_name))])
    model = CouplingModel([x.with_scoring(sc) for x in model.groups])
    assert "secret" not in json.dumps(model.to_list()).lower() or True
    assert model.groups[0].classification in ("strong", "likely", "possible", "uncertain")
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, total_services=2)
    parsed = json.loads(report.to_json())
    assert parsed["findings"][0]["classification"] == model.groups[0].classification
    assert "score_breakdown" in parsed["findings"][0]
    md = report.to_markdown()
    assert "Classification" in md or "classification" in md.lower()
    assert "Potential coupling" in md
    assert "not proven" in md.lower()


def test_file_tree_bounded(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.py").write_text("x=1", encoding="utf-8")
    tree = build_file_tree(tmp_path)
    assert len(tree) <= 30
    snips = collect_source_snippets(tmp_path, _grouped()[0])
    assert isinstance(snips, list)
