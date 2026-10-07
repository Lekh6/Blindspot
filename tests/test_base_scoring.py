"""BASE tests — deterministic scoring (no LLM, no network)."""

from blindspot.aggregation import aggregate_evidence_packages
from blindspot.context_judge import validate_signals
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.parser import parse_compose_string
from blindspot.scoring import SCORING_VERSION, WEIGHTS, score_group, verdict_from_scoring


def _grouped(yaml=None):
    yaml = yaml or """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert groups
    return groups[0]


def _sig(answers):
    items = []
    for qid, ans in answers.items():
        items.append({"id": qid, "answer": ans, "evidence": "e", "confidence": 0.8, "uncertainty": 0.2})
    # fill missing with failsafe via validate
    base = {"Q1_SHARED_USE": "unclear", "Q2_COINCIDENCE": "unclear", "Q3_TABLE": "none",
            "Q4_LIMIT": "missing"}
    base.update(answers)
    return validate_signals([{"id": k, "answer": v, "evidence": "e", "confidence": 0.8, "uncertainty": 0.2}
                             for k, v in base.items()])


def test_deterministic_replay():
    g = _grouped()
    s = _sig({"Q1_SHARED_USE": "yes", "Q2_COINCIDENCE": "no"})
    assert score_group(g, s).score == score_group(g, s).score
    assert score_group(g, s).classification == score_group(g, s).classification


def test_weight_change_moves_band(monkeypatch):
    import blindspot.scoring as sc
    g = _grouped()
    s = _sig({"Q1_SHARED_USE": "yes", "Q2_COINCIDENCE": "no"})
    before = sc.score_group(g, s).score
    monkeypatch.setitem(sc.WEIGHTS, "q1_yes", sc.WEIGHTS["q1_yes"] + 5.0)
    after = sc.score_group(g, s).score
    assert after > before


def test_uncertainty_propagation():
    g = _grouped()
    low = validate_signals([
        {"id": "Q1_SHARED_USE", "answer": "yes", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1},
        {"id": "Q2_COINCIDENCE", "answer": "no", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1},
        {"id": "Q3_TABLE", "answer": "none", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1},
        {"id": "Q4_LIMIT", "answer": "x", "evidence": "e", "confidence": 0.9, "uncertainty": 0.1},
    ])
    high = validate_signals([
        {"id": "Q1_SHARED_USE", "answer": "yes", "evidence": "e", "confidence": 0.9, "uncertainty": 0.9},
        {"id": "Q2_COINCIDENCE", "answer": "no", "evidence": "e", "confidence": 0.9, "uncertainty": 0.9},
        {"id": "Q3_TABLE", "answer": "none", "evidence": "e", "confidence": 0.9, "uncertainty": 0.9},
        {"id": "Q4_LIMIT", "answer": "x", "evidence": "e", "confidence": 0.9, "uncertainty": 0.9},
    ])
    assert score_group(g, high).uncertainty >= score_group(g, low).uncertainty


def test_bands_and_verdict_mapping():
    g = _grouped()
    strong = _sig({"Q1_SHARED_USE": "yes", "Q2_COINCIDENCE": "no", "Q3_TABLE": "yes"})
    sc = score_group(g, strong)
    assert sc.classification in ("strong", "likely")
    v, c, r = verdict_from_scoring(sc, strong)
    assert v == "meaningful" and 0.3 <= c <= 0.92 and r.strip()
    coinc = _sig({"Q1_SHARED_USE": "no", "Q2_COINCIDENCE": "yes"})
    sc2 = score_group(g, coinc)
    v2, _, _ = verdict_from_scoring(sc2, coinc)
    assert v2 in ("coincidental", "uncertain")
    empty = validate_signals([])
    sc3 = score_group(g, empty)
    v3, _, r3 = verdict_from_scoring(sc3, empty)
    assert v3 == "uncertain" and r3.strip()


def test_unresolved_penalty_and_version():
    g1 = _grouped()
    g2_yaml = """
services:
  a: { environment: { DATABASE_URL: "postgresql://${HOST}/${DB}" } }
  b: { environment: { DATABASE_URL: "postgresql://${HOST}/${DB}" } }
"""
    g2 = _grouped(g2_yaml)
    s = _sig({"Q1_SHARED_USE": "yes", "Q2_COINCIDENCE": "no"})
    assert score_group(g2, s).score <= score_group(g1, s).score
    assert SCORING_VERSION.startswith("base-score-")
    assert isinstance(WEIGHTS, dict) and "q1_yes" in WEIGHTS
