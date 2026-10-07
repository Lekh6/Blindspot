"""BlindSpot BASE — Contextual LLM investigation (replaceable).

One prompt per resource group. Fixed stable question IDs. JSON-array response.
No whole-repo send. Validates per item, fails safe. Caches on material evidence.
Provider hidden from user-facing model (kept in cache/log only).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .judge import JudgeResult, FAILSAFE_MODEL, validate_judge_result

PROMPT_VERSION = "base-ctx-v1"

QUESTIONS: List[Dict[str, str]] = [
    {"id": "Q1_SHARED_USE",
     "text": "Do the involved services plausibly use the SAME underlying resource (not just same name)? Answer yes/no/unclear."},
    {"id": "Q2_COINCIDENCE",
     "text": "Is this overlap likely coincidental/generic (e.g. generic var, unrelated values)? Answer yes/no/unclear."},
    {"id": "Q3_TABLE",
     "text": "Is there evidence of a SHARED TABLE/datastore object (L2) beyond shared config? Answer yes/none/unclear; name the table in evidence if yes."},
    {"id": "Q4_LIMIT",
     "text": "What is missing / what would disprove coupling? State the key uncertainty in evidence."},
]

QUESTION_IDS = [q["id"] for q in QUESTIONS]

_ALLOWED = {"Q1_SHARED_USE": {"yes", "no", "unclear"},
            "Q2_COINCIDENCE": {"yes", "no", "unclear"},
            "Q3_TABLE": {"yes", "none", "unclear"},
            "Q4_LIMIT": None}  # free text, must be non-empty


@dataclass(frozen=True)
class MicroSignal:
    qid: str
    answer: str
    evidence: str
    confidence: float
    uncertainty: float

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.qid, "answer": self.answer, "evidence": self.evidence,
                "confidence": self.confidence, "uncertainty": self.uncertainty}


def _failsafe_signal(qid: str, note: str = "malformed") -> MicroSignal:
    default_answer = "unclear" if qid != "Q3_TABLE" else "none"
    if qid == "Q4_LIMIT":
        default_answer = "insufficient evidence"
    return MicroSignal(qid=qid, answer=default_answer,
                       evidence=f"Failsafe ({note}) — no reliable signal.",
                       confidence=0.0, uncertainty=1.0)


def validate_signals(items: List[Dict[str, Any]]) -> List[MicroSignal]:
    """Validate raw list into MicroSignals. Per-item failsafe, never raises on shape."""
    out: List[MicroSignal] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        qid = str(it.get("id", "")).strip()
        if qid in QUESTION_IDS and qid not in by_id:
            by_id[qid] = it
    for qid in QUESTION_IDS:
        raw = by_id.get(qid)
        if raw is None:
            out.append(_failsafe_signal(qid, "missing"))
            continue
        try:
            answer = str(raw.get("answer", "")).strip().lower()
            evidence = str(raw.get("evidence", "")).strip()
            conf = float(raw.get("confidence", 0.0))
            unc = float(raw.get("uncertainty", 1.0))
            if not answer:
                raise ValueError("empty answer")
            allowed = _ALLOWED[qid]
            if allowed is not None and answer not in allowed:
                raise ValueError(f"bad answer {answer!r}")
            if not evidence:
                evidence = "(no evidence stated)"
            conf = max(0.0, min(1.0, conf))
            unc = max(0.0, min(1.0, unc))
            out.append(MicroSignal(qid=qid, answer=answer, evidence=evidence[:500],
                                   confidence=conf, uncertainty=unc))
        except Exception as e:
            out.append(_failsafe_signal(qid, f"invalid: {type(e).__name__}"))
    return out


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    raw = text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return [d for d in v if isinstance(d, dict)]
    except Exception:
        pass
    # balanced-bracket fallback for arrays
    try:
        start = raw.find("[")
        if start >= 0:
            depth = 0
            in_str = False
            esc = False
            for j in range(start, len(raw)):
                c = raw[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == "[":
                        depth += 1
                    elif c == "]":
                        depth -= 1
                        if depth == 0:
                            data = json.loads(raw[start:j + 1])
                            if isinstance(data, list):
                                return [d for d in data if isinstance(d, dict)]
                            break
    except Exception:
        return None
    return None


def parse_or_failsafe(text: str) -> List[MicroSignal]:
    items = _extract_json_array(text)
    if not items:
        return [_failsafe_signal(q, "malformed-response") for q in QUESTION_IDS]
    return validate_signals(items)


def build_contextual_prompt(grouped: Any, bundle: Any) -> str:
    services = ", ".join(sorted(getattr(grouped, "services", []) or []))
    identity = getattr(grouped, "resource_identity", "") or "(unknown)"
    proto = getattr(grouped, "resource_protocol", None) or "unknown"
    status = getattr(grouped, "resolution_status", "unknown")
    strength = getattr(grouped, "identity_strength", "unknown")
    config_ev = dict(getattr(bundle, "configuration_evidence", None) or getattr(grouped, "configuration_evidence", {}) or {})
    lines = []
    for svc in sorted(config_ev.keys()):
        lines.append(f"  {svc}: {', '.join(sorted(config_ev[svc]))}")
    config_str = "\n".join(lines) if lines else "  (none)"
    comp = dict(getattr(bundle, "compose_slice", {}) or {})
    comp_lines = []
    for svc in sorted(comp.keys()):
        info = comp[svc] if isinstance(comp[svc], dict) else {}
        comp_lines.append(f"  {svc}: image={info.get('image') or 'unknown'}, vars={info.get('vars') or {}}")
    comp_str = "\n".join(comp_lines) if comp_lines else "  (none)"
    facts = dict(getattr(bundle, "deterministic_facts", {}) or {})
    facts_str = json.dumps(facts, sort_keys=True)[:800]
    tree = list(getattr(bundle, "file_tree", []) or [])[:30]
    tree_str = "\n".join(f"  - {t}" for t in tree) if tree else "  (none)"
    snips = list(getattr(bundle, "snippets", []) or [])[:3]
    if snips:
        parts = []
        for s in snips:
            if isinstance(s, dict):
                parts.append(f"  [{s.get('file')}:{s.get('line')}] token={s.get('token')}\n{(s.get('text') or '')[:600]}")
        snip_str = "\n".join(parts)[:2000]
    else:
        snip_str = "  (none — no cheap source match; do not guess beyond config)"
    chain = list(getattr(grouped, "representative_chain", []) or [])[:3]
    chain_str = "; ".join(f"{s.get('variable')}->{s.get('to_value')!r}" for s in chain if isinstance(s, dict)) or "(none)"
    q_block = "\n".join(f'{q["id"]}: {q["text"]}' for q in QUESTIONS)
    return f"""You investigate ONE shared resource group for potential hidden coupling. Do NOT rediscover facts; judge the bounded evidence.

SHARED RESOURCE
{identity} (protocol: {proto}, type: {getattr(grouped, 'resource_type', '?')}, resolution: {status}, strength: {strength})
Services ({getattr(grouped, 'service_count', len(getattr(grouped, 'services', [])))}): {services}

RELEVANT COMPOSE (bounded slice)
{comp_str}

CONFIGURATION EVIDENCE BY SERVICE
{config_str}

RESOLVED CONFIG / DETERMINISTIC FACTS
{facts_str}
Representative chain: {chain_str}

BOUNDED FILE TREE (top levels only)
{tree_str}

BOUNDED SOURCE CONTEXT (cheap heuristic, may be empty)
{snip_str}

QUESTIONS (answer each with its stable ID)
{q_block}

Return JSON ARRAY ONLY, one object per question ID:
[{{"id": "Q1_SHARED_USE", "answer": "yes|no|unclear", "evidence": "<short>", "confidence": 0.0-1.0, "uncertainty": 0.0-1.0}}, ...]
Rules: echo every ID exactly once; Q3 answer in yes|none|unclear; Q4 answer free text (what is missing); confidence/uncertainty mandatory 0-1.
"""


def _cache_key(grouped: Any, bundle: Any) -> str:
    try:
        g = grouped.cache_key_dict()
    except Exception:
        g = {"grouping_key": getattr(grouped, "grouping_key", "")}
    try:
        b = bundle.cache_key_dict() if hasattr(bundle, "cache_key_dict") else {}
    except Exception:
        b = {}
    payload = {"v": PROMPT_VERSION, "group": g, "ctx": b}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "ctx:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_cache(path: Union[Path, str, None]):
    from .judge import _load_cache as _lc
    return _lc(path)


def _save_cache(path: Union[Path, str, None], cache) -> None:
    from .judge import _save_cache as _sc
    return _sc(path, cache)


def _call_llm_text(client: Any, prompt: str) -> Tuple[str, str]:
    """Return (text, model_name). Supports Gemini/OpenRouter real clients."""
    name = client.__class__.__name__
    if name == "GeminiJudgeClient":
        api_key = client._resolve_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
        g = genai.Client(api_key=api_key)
        try:
            cfg = types.GenerateContentConfig(temperature=getattr(client, "temperature", 0.2),
                                              response_mime_type="application/json",
                                              thinking_config=types.ThinkingConfig(
                                                  thinking_budget=client._thinking_budget()))
            resp = g.models.generate_content(model=client.model, contents=prompt, config=cfg)
        except Exception:
            resp = g.models.generate_content(model=client.model, contents=prompt)
        text = getattr(resp, "text", "") or str(resp)
        return text, client.model
    if name == "OpenRouterJudgeClient":
        api_key = client._resolve_api_key()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        from openai import OpenAI  # type: ignore
        oai = OpenAI(api_key=api_key, base_url=client.base_url)
        resp = oai.chat.completions.create(
            model=client.model, temperature=getattr(client, "temperature", 0.2),
            max_tokens=client._max_tokens(),
            messages=[{"role": "system", "content": "Return JSON array only, one object per question ID."},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return text, client.model
    raise RuntimeError(f"unsupported client {name}")


def judge_contextual_package(grouped: Any, bundle: Any, client: Any,
                             cache_path: Optional[Union[Path, str]] = None,
                             use_cache: bool = True) -> Tuple[List[MicroSignal], str]:
    """Returns (signals, model_name). Cache-aware. Never raises on malformed LLM."""
    key = _cache_key(grouped, bundle)
    if use_cache and cache_path is not None:
        try:
            cache = _load_cache(cache_path)
            if key in cache:
                entry = cache[key]
                return validate_signals(entry.get("signals", [])), str(entry.get("model", "cache"))
        except Exception:
            pass
    prompt = build_contextual_prompt(grouped, bundle)
    signals: List[MicroSignal]
    model_name = "unknown"
    try:
        if hasattr(client, "judge_context"):
            raw = client.judge_context(prompt, bundle)  # test stubs
            if isinstance(raw, list):
                signals = validate_signals(raw)
                model_name = getattr(client, "model", "stub")
            elif isinstance(raw, str):
                signals = parse_or_failsafe(raw)
                model_name = getattr(client, "model", "stub")
            else:
                signals = [_failsafe_signal(q, "bad-stub") for q in QUESTION_IDS]
                model_name = getattr(client, "model", "stub")
        else:
            text, model_name = _call_llm_text(client, prompt)
            signals = parse_or_failsafe(text)
    except Exception as e:
        signals = [_failsafe_signal(q, f"error:{type(e).__name__}") for q in QUESTION_IDS]
        model_name = f"{FAILSAFE_MODEL}-failsafe-ctx"
    validate_signals([s.to_dict() for s in signals])  # sanity, raises nothing
    if use_cache and cache_path is not None:
        try:
            cache = _load_cache(cache_path)
            cache[key] = {"signals": [s.to_dict() for s in signals], "model": model_name,
                          "prompt_version": PROMPT_VERSION}
            _save_cache(cache_path, cache)
        except Exception:
            pass
    return signals, model_name


def judge_contextual_packages(groups: List[Any], bundles: Dict[str, Any], client: Any,
                              cache_path: Optional[Union[Path, str]] = None,
                              use_cache: bool = True) -> List[Tuple[Any, List[MicroSignal], str]]:
    out = []
    for g in sorted(groups, key=lambda x: getattr(x, "grouping_key", "")):
        b = bundles.get(getattr(g, "grouping_key", "")) if isinstance(bundles, dict) else None
        if b is None:
            from .context import build_context_bundle
            b = build_context_bundle(g)
        signals, model = judge_contextual_package(g, b, client, cache_path, use_cache)
        out.append((g, signals, model))
    return out


def signals_to_judge_result(signals: List[MicroSignal], model: str,
                            fallback_confidence: float = 0.5) -> JudgeResult:
    """Deterministic mapping signals -> legacy JudgeResult (for CouplingModel compat).

    The LLM never sets verdict directly; this mapping is fixed code.
    """
    by = {s.qid: s for s in signals}
    q1 = by.get("Q1_SHARED_USE")
    q2 = by.get("Q2_COINCIDENCE")
    if q1 is None or q2 is None:
        r = JudgeResult(verdict="uncertain", confidence=0.3,
                        reason="Contextual signals incomplete — insufficient evidence.", model=model)
        validate_judge_result(r)
        return r
    if q1.answer == "yes" and q2.answer == "no":
        conf = round(0.6 + 0.3 * min(q1.confidence, 1.0 - q2.uncertainty), 2)
        r = JudgeResult(verdict="meaningful", confidence=conf,
                        reason=f"Services plausibly share the same resource ({q1.evidence[:160]}).", model=model)
    elif q2.answer == "yes":
        conf = round(0.5 + 0.3 * q2.confidence, 2)
        r = JudgeResult(verdict="coincidental", confidence=min(conf, 0.95),
                        reason=f"Overlap looks coincidental ({q2.evidence[:160]}).", model=model)
    else:
        r = JudgeResult(verdict="uncertain", confidence=round(fallback_confidence, 2),
                        reason=f"Insufficient evidence ({by.get('Q4_LIMIT').evidence[:160] if by.get('Q4_LIMIT') else 'missing context'}).",
                        model=model)
    validate_judge_result(r)
    return r
