"""BlindSpot BASE — Deterministic scoring (isolated, replaceable).

LLM provides signals; this module decides the band. No LLM here.
Weights are explicit + versioned. Final classification reproducible from evidence.
Not a probability — a strength band.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

SCORING_VERSION = "base-score-v1"

# Explicit weights — reasonable defaults, easy to retune. Document changes here.
WEIGHTS: Dict[str, float] = {
    "exact": 2.0,            # identity_strength exact
    "config": 1.0,            # identity_strength config
    "internal": 1.0,          # resolution internal
    "external_confirmed": 1.0,
    "partial": 0.0,
    "unresolved_status": -1.0,
    "named_volume_bonus": 1.0,
    "unresolved_var_penalty": -0.5,  # each, capped
    "max_unresolved_penalty": -1.5,
    "evidence_count_bonus": 0.5,     # when >=3 observations
    "q1_yes": 3.0,
    "q1_no": -2.0,
    "q2_is_coincidence": -2.0,  # Q2 yes
    "q2_not_coincidence": 1.0,  # Q2 no
    "q3_table_yes": 2.0,
}

# Bands (tunable thresholds)
STRONG_AT = 4.5
LIKELY_AT = 2.0
POSSIBLE_AT = 0.0


@dataclass(frozen=True)
class ScoringResult:
    score: float
    classification: str  # strong | likely | possible | uncertain
    breakdown: Dict[str, float]
    uncertainty: float
    scoring_version: str = SCORING_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {"score": self.score, "classification": self.classification,
                "breakdown": dict(self.breakdown), "uncertainty": self.uncertainty,
                "scoring_version": self.scoring_version}


def _qid(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("id", ""))
    return str(getattr(s, "qid", ""))


def _ans(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("answer", ""))
    return str(getattr(s, "answer", ""))


def _conf(s: Any) -> float:
    try:
        if isinstance(s, dict):
            return float(s.get("confidence", 0.0))
        return float(getattr(s, "confidence", 0.0))
    except Exception:
        return 0.0


def _unc(s: Any) -> float:
    try:
        if isinstance(s, dict):
            return float(s.get("uncertainty", 1.0))
        return float(getattr(s, "uncertainty", 1.0))
    except Exception:
        return 1.0


def _ev(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("evidence", ""))
    return str(getattr(s, "evidence", ""))


def score_group(grouped: Any, signals: List[Any]) -> ScoringResult:
    b: Dict[str, float] = {}
    strength = getattr(grouped, "identity_strength", "unknown")
    status = getattr(grouped, "resolution_status", "unresolved")
    rtype = getattr(grouped, "resource_type", "")
    unresolved = list(getattr(grouped, "unresolved_vars", []) or [])
    ev_count = int(getattr(grouped, "evidence_count", 0) or 0)

    if strength == "exact":
        b["identity_exact"] = WEIGHTS["exact"]
    elif strength == "config":
        b["identity_config"] = WEIGHTS["config"]
    else:
        b["identity_unknown"] = 0.0
    if status == "internal":
        b["status_internal"] = WEIGHTS["internal"]
    elif status == "external_confirmed":
        b["status_external"] = WEIGHTS["external_confirmed"]
    elif status == "partial":
        b["status_partial"] = WEIGHTS["partial"]
    else:
        b["status_unresolved"] = WEIGHTS["unresolved_status"]
    if rtype == "named_volume":
        b["named_volume"] = WEIGHTS["named_volume_bonus"]
    if unresolved:
        pen = max(WEIGHTS["max_unresolved_penalty"],
                  WEIGHTS["unresolved_var_penalty"] * len(unresolved))
        b["unresolved_vars"] = round(pen, 2)
    if ev_count >= 3:
        b["evidence_count"] = WEIGHTS["evidence_count_bonus"]

    by = {_qid(s): s for s in signals}

    def _get(qid: str):
        return by.get(qid)
    q1 = _get("Q1_SHARED_USE")
    if q1 is not None:
        a = _ans(q1)
        c = _conf(q1)
        if a == "yes":
            b["q1_shared_yes"] = round(WEIGHTS["q1_yes"] * max(0.0, min(1.0, c)), 2)
        elif a == "no":
            b["q1_shared_no"] = round(WEIGHTS["q1_no"] * max(0.0, min(1.0, c)), 2)
    q2 = _get("Q2_COINCIDENCE")
    if q2 is not None:
        a = _ans(q2)
        c = _conf(q2)
        if a == "yes":
            b["q2_coincidence"] = round(WEIGHTS["q2_is_coincidence"] * max(0.0, min(1.0, c)), 2)
        elif a == "no":
            b["q2_not_coincidence"] = round(WEIGHTS["q2_not_coincidence"] * max(0.0, min(1.0, c)), 2)
    q3 = _get("Q3_TABLE")
    if q3 is not None:
        a = _ans(q3)
        c = _conf(q3)
        if a == "yes":
            b["q3_table"] = round(WEIGHTS["q3_table_yes"] * max(0.0, min(1.0, c)), 2)

    total = round(sum(b.values()), 2)
    if total >= STRONG_AT:
        band = "strong"
    elif total >= LIKELY_AT:
        band = "likely"
    elif total >= POSSIBLE_AT:
        band = "possible"
    else:
        band = "uncertain"

    # Uncertainty: max signal uncertainty + structural penalties, capped 0-1
    uncs: List[float] = []
    for s in signals:
        uncs.append(max(0.0, min(1.0, _unc(s))))
    u_max = max(uncs) if uncs else 1.0
    if unresolved:
        u_max = min(1.0, u_max + 0.1 * min(len(unresolved), 3))
    if not getattr(grouped, "resource_protocol", None):
        u_max = min(1.0, u_max + 0.1)
    # Coincidence-yes forces at least possible->uncertain? No — band already reflects; uncertainty stays honest
    return ScoringResult(score=total, classification=band, breakdown=b,
                         uncertainty=round(min(1.0, max(0.0, u_max)), 2))


def verdict_from_scoring(scoring: ScoringResult, signals: List[Any]) -> tuple:
    """Deterministic (verdict, confidence, reason) from scoring + signals.

    LLM never sets these directly. Reproducible from evidence.
    """
    by = {}
    for s in signals:
        by[_qid(s)] = s
    q2 = by.get("Q2_COINCIDENCE")
    q2_yes = False
    q2_ev = ""
    if q2 is not None:
        q2_yes = (_ans(q2) == "yes")
        q2_ev = _ev(q2)[:160]
    q1 = by.get("Q1_SHARED_USE")
    q1_yes = (_ans(q1) == "yes") if q1 is not None else False
    if scoring.classification in ("strong", "likely") and q1_yes:
        verdict = "meaningful"
    elif q2_yes:
        verdict = "coincidental"
    else:
        verdict = "uncertain"
    conf = 0.55 + 0.07 * float(scoring.score) - 0.20 * float(scoring.uncertainty)
    conf = round(min(0.92, max(0.30, conf)), 2)
    q1 = by.get("Q1_SHARED_USE")
    q1_ev = ""
    if q1 is not None:
        q1_ev = _ev(q1)[:160]
    if verdict == "meaningful":
        reason = f"BASE contextual: shared use plausible ({q1_ev or 'config convergence'}). Score {scoring.score:+.1f} [{scoring.classification}]. Potential coupling, not proven runtime."
    elif verdict == "coincidental":
        reason = f"BASE contextual: overlap looks coincidental ({q2_ev or 'generic signals'}). Score {scoring.score:+.1f}. Not a coupling finding."
    else:
        q4 = by.get("Q4_LIMIT")
        q4_ev = ""
        if q4 is not None:
            q4_ev = _ev(q4)[:160]
        reason = f"BASE contextual: insufficient evidence ({q4_ev or 'missing context'}). Score {scoring.score:+.1f} [{scoring.classification}]. Preserving uncertainty."
    return verdict, conf, reason
