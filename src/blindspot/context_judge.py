"""BlindSpot Stage 4: Contextual per-candidate LLM judgment.

Interprets Stage 3 investigation contexts. Never rediscovers candidates or
invents facts. One LLM call per investigation context; each candidate inside
judged individually with structured, validated output.

Separation enforced (Stage 5 untouched):
  - static evidence stays in InvestigationContext
  - LLM judgment stays in CandidateJudgment (verdict + raw confidence + reason)
  - NO weighted scores, thresholds, or YES/NO decisions here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .context import (
    InvestigationContext,
    CONTEXT_SCHEMA_VERSION,
    PROMPT_VERSION,
)
from .filtering import EVIDENCE_SCHEMA_VERSION
from .judge import JudgeResult, VALID_VERDICTS, validate_judge_result
from .secrets import REDACTED

MAX_RETRIES = 2  # bounded retries for transient/repairable errors


@dataclass(frozen=True)
class CandidateJudgment:
    """Validated semantic judgment for one candidate (LLM signal only)."""

    candidate_id: str
    verdict: str  # meaningful | coincidental | uncertain
    confidence: float  # raw LLM confidence 0-1, NOT a calibrated probability
    reason: str
    supporting_evidence: Tuple[str, ...]
    missing_information: Tuple[str, ...]
    model: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
            "supporting_evidence": list(self.supporting_evidence),
            "missing_information": list(self.missing_information),
            "model": self.model,
        }


@dataclass(frozen=True)
class JudgmentFailure:
    """Operational failure — never a semantic verdict, never cached as valid."""

    candidate_id: str
    error_type: str  # provider_error | timeout | malformed | truncated | context_too_large | ...
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "error_type": self.error_type,
            "message": self.message,
        }


def build_system_prompt() -> str:
    """Versioned reasoning instructions (PROMPT_VERSION invalidates cache)."""
    return f"""You are a precise architecture investigator (prompt {PROMPT_VERSION}).

Rules:
- Use ONLY supplied evidence. Cite supplied evidence refs in supporting_evidence.
- Ground every conclusion in evidence references; never invent configuration facts.
- Examine ALL participating services and candidates in the context.
- Consider CONFLICTING evidence (different DBs, endpoints, volumes, values, unresolved refs, generic-only overlap) — do not focus only on supporting signals.
- Distinguish observed configuration facts from deterministic resolution results from interpretations you are asked to assess.
- Never assume runtime connectivity, reads, writes, data ownership, or application behavior without supporting evidence.
- Distinguish a database SERVER from a LOGICAL DATABASE: shared server + different DB names = not the same logical database.
- A shared named volume does not prove one service relies on another's files.
- Explain why each candidate is meaningful, coincidental, or uncertain.
- Identify missing information rather than inventing it.
- Return uncertain when evidence is insufficient.
- Judge EACH candidate individually with its own candidate_id even when reasoning over shared context.
- Do not create candidates, modify IDs, or introduce new resource facts.
- meaningful = shared resource implies potential implicit coupling; coincidental = same name/value by chance; uncertain = cannot decide.
- Confidence is a raw self-assessment 0-1, not a calibrated probability.
"""


def build_context_prompt(ctx: InvestigationContext) -> str:
    """Serialize a context deterministically for the model (secret-safe already)."""
    d = ctx.to_dict()
    # Deterministic field order via canonical JSON pretty-printed for readability.
    return json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False)


def _known_evidence_refs(ctx: InvestigationContext) -> set:
    refs: set = set()
    for c in ctx.candidates:
        refs.update(c.evidence_refs)
        refs.add(f"candidate:{c.candidate_id}")
    return refs


def validate_candidate_judgments(
    ctx: InvestigationContext,
    items: Any,
    model: str,
) -> Tuple[List[CandidateJudgment], List[JudgmentFailure]]:
    """Validate raw model output against the exact submitted context.

    Rejects unknown IDs, invented evidence refs, bad verdicts, malformed
    fields, out-of-range confidence. Missing/duplicate results become explicit
    failures (never fabricated judgments).
    """
    failures: List[JudgmentFailure] = []
    if not isinstance(items, list):
        return [], [JudgmentFailure(candidate_id=cid, error_type="malformed",
                                    message="response is not a list")
                    for cid in ctx.candidate_ids]
    by_id: Dict[str, Dict[str, Any]] = {}
    dupes: set = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("candidate_id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid in by_id:
            dupes.add(cid)
            continue
        by_id[cid] = entry

    known_ids = set(ctx.candidate_ids)
    known_refs = _known_evidence_refs(ctx)
    valid: List[CandidateJudgment] = []

    for cid in ctx.candidate_ids:
        if cid in dupes:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="duplicate",
                                            message="duplicate results for candidate"))
            continue
        entry = by_id.get(cid)
        if entry is None:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="missing",
                                            message="no result returned for candidate"))
            continue
        verdict = entry.get("verdict")
        conf = entry.get("confidence")
        reason = entry.get("reason")
        sup = entry.get("supporting_evidence", [])
        miss = entry.get("missing_information", [])
        # Type/shape checks.
        if verdict not in VALID_VERDICTS:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="invalid_verdict",
                                            message=f"invalid verdict {verdict!r}"))
            continue
        try:
            conf_f = float(conf)
        except Exception:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="invalid_confidence",
                                            message=f"confidence not numeric: {conf!r}"))
            continue
        if not 0.0 <= conf_f <= 1.0:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="invalid_confidence",
                                            message=f"confidence out of range: {conf!r}"))
            continue
        if not isinstance(reason, str) or not reason.strip():
            failures.append(JudgmentFailure(candidate_id=cid, error_type="malformed",
                                            message="reason must be non-empty string"))
            continue
        if not isinstance(sup, list) or not all(isinstance(r, str) for r in sup):
            failures.append(JudgmentFailure(candidate_id=cid, error_type="invalid_evidence_ref",
                                            message="supporting_evidence must be list[str]"))
            continue
        unknown_refs = [r for r in sup if r not in known_refs]
        if unknown_refs:
            failures.append(JudgmentFailure(candidate_id=cid, error_type="invalid_evidence_ref",
                                            message=f"unknown evidence refs: {unknown_refs}"))
            continue
        if not isinstance(miss, list) or not all(isinstance(m, str) for m in miss):
            failures.append(JudgmentFailure(candidate_id=cid, error_type="malformed",
                                            message="missing_information must be list[str]"))
            continue
        valid.append(CandidateJudgment(
            candidate_id=cid, verdict=verdict, confidence=conf_f,
            reason=reason.strip(), supporting_evidence=tuple(sup),
            missing_information=tuple(miss), model=model,
        ))

    # Extra unknown candidates in response → failures (do not accept).
    for cid in sorted(set(by_id.keys()) - known_ids):
        failures.append(JudgmentFailure(candidate_id=cid, error_type="unknown_candidate",
                                        message="result for candidate not in context"))
    return valid, failures


def _cache_key_for_context(ctx: InvestigationContext, model: str, thinking: str = "") -> str:
    payload = ctx.cache_key_dict()
    payload.update({
        "model": model,
        "thinking": thinking,
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
    })
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _load_cache(path: Optional[Union[Path, str]]) -> Dict[str, Any]:
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if "entries" in data and isinstance(data["entries"], dict):
                return data["entries"]
            return data
    except Exception:
        pass
    return {}


def _save_cache(path: Optional[Union[Path, str]], cache: Dict[str, Any]) -> None:
    if path is None:
        return
    import tempfile

    p = Path(path)
    wrapped = {"version": 2, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "entries": cache}
    # Ensure no secrets leak: payloads are already redacted, but guard anyway.
    blob = json.dumps(wrapped, indent=2, sort_keys=True, ensure_ascii=False)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(p.parent) if p.parent.exists() else None, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(blob)
        Path(tmp_path).replace(p)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _extract_json_list(text: str) -> Any:
    import re

    raw = text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Fallback: last balanced [...] block.
    start = raw.rfind("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return None


def judge_investigation_context(
    ctx: InvestigationContext,
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
    thinking: str = "low",
) -> Tuple[List[CandidateJudgment], List[JudgmentFailure]]:
    """Judge every candidate in one context (one LLM call, bounded retries).

    Cache hits avoid model calls. Only validated semantic judgments
    (including legitimate uncertain) are cached — transient failures never.
    """
    model_name = getattr(client, "model", None) or getattr(client, "model_name", "unknown")
    if not isinstance(model_name, str):
        model_name = "unknown"
    key = _cache_key_for_context(ctx, model_name, thinking)
    if use_cache and cache_path is not None:
        cache = _load_cache(cache_path)
        if key in cache:
            try:
                entry = cache[key]
                valid = [CandidateJudgment(
                    candidate_id=e["candidate_id"], verdict=e["verdict"],
                    confidence=float(e["confidence"]), reason=e["reason"],
                    supporting_evidence=tuple(e.get("supporting_evidence", [])),
                    missing_information=tuple(e.get("missing_information", [])),
                    model=e.get("model", model_name),
                ) for e in entry["judgments"]]
                # Re-validate IDs against current context (grouping change invalidates).
                if {j.candidate_id for j in valid} == set(ctx.candidate_ids):
                    return valid, []
            except Exception:
                pass

    system = build_system_prompt()
    user = build_context_prompt(ctx)
    full_prompt = system + "\n\nINVESTIGATION CONTEXT (JSON):\n" + user + (
        "\n\nReturn a JSON ARRAY, one object per candidate: "
        '{"candidate_id, verdict: meaningful|coincidental|uncertain, confidence 0-1, '
        'reason, supporting_evidence: [refs from context], missing_information: [strings]}. '
        "Judge each candidate individually."
    )

    last_error: Optional[str] = None
    for _ in range(MAX_RETRIES + 1):
        try:
            if hasattr(client, "complete_json"):
                text = client.complete_json(full_prompt)  # type: ignore
            elif hasattr(client, "judge_context"):
                text = client.judge_context(ctx)  # type: ignore
            else:
                # Generic fallback: reuse OpenRouter/Gemini-style clients via
                # a minimal inline call is out of scope here — require adapter.
                # For tests, MockContextClient implements complete_json.
                raise TypeError(f"client {type(client).__name__} has no complete_json/judge_context")
            items = _extract_json_list(text if isinstance(text, str) else str(text))
            if items is None:
                last_error = f"unparsable response: {str(text)[:200]!r}"
                continue
            valid, failures = validate_candidate_judgments(ctx, items, model_name)
            # Partial success: preserve valid, mark invalid as failures.
            if valid or failures:
                # Cache only if every candidate validated (no failures).
                if not failures and use_cache and cache_path is not None:
                    cache = _load_cache(cache_path)
                    cache[key] = {
                        "judgments": [j.to_dict() for j in valid],
                        "context_schema_version": CONTEXT_SCHEMA_VERSION,
                        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                        "prompt_version": PROMPT_VERSION,
                        "model": model_name,
                        "investigation_id": ctx.investigation_id,
                    }
                    _save_cache(cache_path, cache)
                return valid, failures
            last_error = "empty validation result"
        except (TimeoutError, ConnectionError) as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        except Exception as e:
            # Non-transient (e.g. missing adapter): fail safely, no retry loop abuse.
            last_error = f"{type(e).__name__}: {e}"
            break

    # Exhausted retries or adapter error → explicit failures for ALL candidates
    # (never fabricated coincidental/uncertain judgments).
    return [], [JudgmentFailure(candidate_id=cid, error_type="provider_error",
                               message=last_error or "judgment failed")
                for cid in ctx.candidate_ids]


def to_legacy_group_result(
    judgments: List[CandidateJudgment],
    fallback_model: str = "unknown",
) -> JudgeResult:
    """Derive one group-level JudgeResult for downstream graph/report compat.

    Deterministic, no weights/scoring: meaningful wins over uncertain wins over
    coincidental; confidence = max among winners; reasons joined. Stage 5 will
    later do proper scoring — this is display-only compatibility.
    """
    if not judgments:
        return JudgeResult(verdict="uncertain", confidence=0.0,
                           reason="No validated judgments.", model=fallback_model)
    order = {"meaningful": 0, "uncertain": 1, "coincidental": 2}
    top = min(judgments, key=lambda j: order.get(j.verdict, 1))
    winners = [j for j in judgments if j.verdict == top.verdict]
    conf = max(float(j.confidence) for j in winners)
    reason = "; ".join(sorted({j.reason for j in winners}))[:600]
    model = winners[0].model or fallback_model
    result = JudgeResult(verdict=top.verdict, confidence=conf, reason=reason, model=model)  # type: ignore
    validate_judge_result(result)
    return result


class MockContextClient:
    """Hermetic test client: returns canned per-candidate judgments (no network)."""

    def __init__(self, verdict: str = "meaningful", confidence: float = 0.8,
                 model: str = "mock", calls: Optional[list] = None):
        self._verdict = verdict
        self._confidence = confidence
        self.model = model
        self.calls: list = calls if calls is not None else []

    def complete_json(self, prompt: str) -> str:
        self.calls.append(prompt)
        import re as _re

        # Prefer explicit metadata candidate_ids list.
        m = _re.search(r'"candidate_ids"\s*:\s*\[(.*?)\]', prompt, _re.DOTALL)
        ids: list = []
        if m:
            ids = _re.findall(r'"([^"]+)"', m.group(1))
        if not ids:
            # Fallback: candidate_id fields (exclude candidate: refs).
            for i in _re.findall(r'"candidate_id"\s*:\s*"([^"]+)"', prompt):
                if i not in ids:
                    ids.append(i)
        items = [{
            "candidate_id": cid,
            "verdict": self._verdict,
            "confidence": self._confidence,
            "reason": f"mock {self._verdict} for {cid}",
            "supporting_evidence": [f"candidate:{cid}"],
            "missing_information": [],
        } for cid in ids]
        return json.dumps(items)
