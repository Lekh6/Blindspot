"""
BlindSpot Stage 4: LLM Judge — Semantic Judgment (One Call Per Surviving Candidate)

Per AGENTS.md §4:

- Judges pre-extracted bounded EvidencePackage from Stage 3, not whole repo.
- Normal cost: 0 LLM calls for obvious noise + 1 LLM call per interesting candidate.
- No multiple LLM prompts per evidence item; one package → one call.
- Structured output: verdict ∈ {meaningful, coincidental, uncertain}, confidence 0-1 mandatory, reason.
- Verdicts cached in cache.json with candidate+evidence-aware key (EvidencePackage.cache_key_dict).
- Provider-agnostic: prompt is model-agnostic; clients are pluggable (Gemini via google-genai, Nemotron/OpenRouter via openai SDK).
  Thinking budget low/medium dynamically adjustable via THINKING_BUDGETS.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal, Protocol, Tuple, Union

from .filtering import EvidencePackage

Verdict = Literal["meaningful", "coincidental", "uncertain"]

VALID_VERDICTS = {"meaningful", "coincidental", "uncertain"}

# Provider-agnostic defaults
# Gemini (via google-genai) — legacy primary/failsafe, still supported
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"
GEMINI_FAILSAFE_MODEL = "gemini-3.1-flash-lite"
# OpenRouter (via openai SDK) — Nemotron 3 Ultra is current default (was Lightning free)
OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Generic alias — change this to switch default provider without touching call sites
DEFAULT_MODEL = OPENROUTER_DEFAULT_MODEL
FAILSAFE_MODEL = GEMINI_FAILSAFE_MODEL
THINKING_BUDGETS: Dict[str, int] = {
    "none": 0,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
}
# OpenRouter thinking -> max_tokens mapping (low/medium keeps testing cheap)
OPENROUTER_MAX_TOKENS: Dict[str, int] = {
    "none": 256,
    "low": 512,
    "medium": 1024,
    "high": 2048,
}


@dataclass(frozen=True)
class JudgeResult:
    verdict: Verdict
    confidence: float  # 0.0–1.0 mandatory
    reason: str
    model: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "JudgeResult":
        return cls(
            verdict=d["verdict"],
            confidence=float(d["confidence"]),
            reason=str(d["reason"]),
            model=str(d.get("model", "unknown")),
        )


def validate_judge_result(result: JudgeResult) -> None:
    if result.verdict not in VALID_VERDICTS:
        raise ValueError(f"Invalid verdict {result.verdict!r}, must be one of {VALID_VERDICTS}")
    if not isinstance(result.confidence, (int, float)):
        raise ValueError(f"confidence must be number, got {type(result.confidence)}")
    if not 0.0 <= float(result.confidence) <= 1.0:
        raise ValueError(f"confidence {result.confidence} out of range [0,1]")
    if not isinstance(result.reason, str) or not result.reason.strip():
        raise ValueError("reason must be non-empty string")


# ---------------------------------------------------------------------------
# Prompt building (narrow, per §5 of mod spec)
# ---------------------------------------------------------------------------

def build_judge_prompt(package: EvidencePackage) -> str:
    """Build narrow classification prompt for a single EvidencePackage.

    Contains: SERVICE A/B, SHARED CONFIGURATION, VALUES, RESOLUTION,
    RELATED CONFIGURATION (bounded), DETERMINISTIC FILTERING signals.
    LLM must return verdict/confidence/reason only.
    """
    # Related config formatted per service
    related_lines = []
    if package.related_config:
        for svc, cfg in sorted(package.related_config.items()):
            if cfg:
                kv = ", ".join(f"{k}={v!r}" for k, v in sorted(cfg.items()))
                related_lines.append(f"  {svc}: {kv}")
            else:
                related_lines.append(f"  {svc}: (none relevant)")
        related_str = "\n".join(related_lines)
    else:
        related_str = "  (none — no directly relevant surrounding config)"

    # Resolution line
    if package.reference_type == "compose_service":
        resolution = f"{package.value!r} -> Compose service \"{package.resolved_service}\" (image: {package.resolved_image or 'unknown'}) -- internal coupling"
    elif package.reference_type == "named_volume":
        vol_str = ""
        if package.volume_targets:
            vol_str = ", ".join(f"{svc}:{t!r}" for svc, t in sorted(package.volume_targets.items()))
            vol_str = f" targets {vol_str}"
        resolution = f"named volume \"{package.resource}\"{vol_str} -- shared filesystem (internal)"
    elif package.reference_type == "external":
        resolution = f"{package.value!r} does not resolve to a Compose service -- external/unknown (may be cloud/host outside compose)"
    else:
        resolution = "unresolved / not host-like -- insufficient evidence to resolve"

    # Values display
    if package.resource_type == "named_volume":
        values_str = f"shared volume \"{package.resource}\" mounted by both services"
    elif package.value is not None:
        values_str = f"{package.service_a} -> {package.value!r}\n{package.service_b} -> {package.value!r}  (same_value: true)"
    else:
        values_str = f"{package.service_a} / {package.service_b} values differ or absent (same_value: false)"

    return f"""You are evaluating one candidate for implicit cross-service coupling.

SERVICE A
{package.service_a}

SERVICE B
{package.service_b}

SHARED CONFIGURATION
{package.resource}  (type: {package.resource_type})

VALUES
{values_str}

RESOLUTION
{resolution}

RELATED CONFIGURATION (bounded, only directly relevant)
{related_str}

DETERMINISTIC FILTERING
generic_variable: {str(package.generic_variable).lower()}
same_value: {str(package.same_value).lower()}
resolved_reference: {package.reference_type}

TASK
Determine whether the evidence indicates:
1. meaningful coupling — shared resource implies services are implicitly coupled (e.g. shared DB host/volume)
2. coincidental overlap — same name/value by chance, no real coupling (e.g. generic PORT, unrelated strings)
3. insufficient evidence — cannot decide from given facts

Return JSON with:
- verdict: "meaningful" | "coincidental" | "uncertain"
- confidence: 0.0-1.0 (mandatory, how confident you are)
- reason: short explanation (1-2 sentences)
"""


# ---------------------------------------------------------------------------
# Cache handling (§7)
# ---------------------------------------------------------------------------

def _cache_key_for_package(package: EvidencePackage) -> str:
    """Deterministic cache key = hash(candidate + relevant evidence).

    Uses EvidencePackage.cache_key_dict() which includes service A/B, resource,
    resource_type, value, resolved_service/image, is_internal, reference_type,
    related_config, generic_variable/same_value.
    If evidence changes materially, key changes.
    """
    payload = package.cache_key_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_cache(cache_path: Union[Path, str, None]) -> Dict[str, Any]:
    if cache_path is None:
        return {}
    p = Path(cache_path)
    if not p.exists() or not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Support both flat {key: result} and wrapped {"entries": {...}} formats
            if "entries" in data and isinstance(data["entries"], dict):
                return data["entries"]
            return data
        return {}
    except Exception:
        return {}


def _save_cache(cache_path: Union[Path, str, None], cache: Dict[str, Any]) -> None:
    if cache_path is None:
        return
    p = Path(cache_path)
    # Wrap with metadata for readability
    wrapped = {
        "version": 1,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": cache,
    }
    p.write_text(json.dumps(wrapped, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Client protocol
# ---------------------------------------------------------------------------

class JudgeClient(Protocol):
    """Protocol for LLM judgment — one call per package."""

    def judge(self, package: EvidencePackage) -> JudgeResult: ...

    @property
    def model_name(self) -> str: ...


# ---------------------------------------------------------------------------
# Failsafe + placeholder for future extension
# ---------------------------------------------------------------------------

def failsafe_result(package: EvidencePackage, reason: str, model: str = FAILSAFE_MODEL) -> JudgeResult:
    """Deterministic failsafe when LLM call fails — returns uncertain, low confidence.

    Provider-agnostic: model defaults to FAILSAFE_MODEL (gemini-3.1-flash-lite) so failures are
    explicitly attributed. Pipeline never crashes on API error.
    """
    msg = reason.strip()[:300] if reason.strip() else "LLM call failed"
    return JudgeResult(
        verdict="uncertain",
        confidence=0.5,
        reason=f"Failsafe ({FAILSAFE_MODEL}): {msg} — evidence was {package.resource} ({package.resource_type})",
        model=model,
    )


def placeholder_future_judge(package: EvidencePackage) -> JudgeResult:
    """Placeholder for a future custom rule/heuristic you can devise later.

    Currently raises NotImplementedError — wire it into GeminiJudgeClient or
    use as alternative JudgeClient once designed.
    Replace the body with your own deterministic/heuristic logic.
    """
    raise NotImplementedError(
        "placeholder_future_judge is a stub — implement your custom logic here "
        f"(package={package.service_a}/{package.service_b} {package.resource})"
    )


# ---------------------------------------------------------------------------
# Gemini Flash client
# ---------------------------------------------------------------------------

@dataclass
class GeminiJudgeClient:
    """Google Gemini Flash judge — one LLM call per EvidencePackage.

    - model: primary Gemini model id, default gemini-3.7-flash
    - fallback_model: used for failsafe attribution (gemini-3.1-flash-lite) if primary fails
    - thinking_level: low|medium|high|none — maps to thinkingBudget (dynamically adjustable via set_thinking_level)
    - api_key: if None, reads GEMINI_API_KEY or GOOGLE_API_KEY env var
    - Use thinking low/medium during testing to keep latency/cost down.

    Requires `google-genai` package and GEMINI_API_KEY env var.
    """

    model: str = GEMINI_DEFAULT_MODEL
    fallback_model: str = GEMINI_FAILSAFE_MODEL
    thinking_level: str = "low"
    api_key: Optional[str] = None
    max_retries: int = 1  # retries on malformed JSON
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if self.thinking_level not in THINKING_BUDGETS:
            raise ValueError(f"thinking_level must be one of {list(THINKING_BUDGETS)}, got {self.thinking_level!r}")

    @property
    def model_name(self) -> str:
        return self.model

    def set_thinking_level(self, level: str) -> None:
        """Dynamically adjust thinking effort (low/medium/high/none)."""
        if level not in THINKING_BUDGETS:
            raise ValueError(f"level must be one of {list(THINKING_BUDGETS)}, got {level!r}")
        self.thinking_level = level

    def _resolve_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        # Support both GEMINI_API_KEY and GOOGLE_API_KEY (and legacy)
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            v = os.getenv(k)
            if v:
                return v
        return None

    def _thinking_budget(self) -> int:
        return THINKING_BUDGETS[self.thinking_level]

    def judge(self, package: EvidencePackage) -> JudgeResult:
        prompt = build_judge_prompt(package)
        api_key = self._resolve_api_key()
        if not api_key:
            return failsafe_result(package, "GEMINI_API_KEY not set — set env var GEMINI_API_KEY", model=f"{self.fallback_model}-failsafe-no-key")

        # Lazy import so module remains importable without SDK (tests) — provider-agnostic
        try:
            from google import genai  # type: ignore[import-untyped]
            from google.genai import types  # type: ignore[import-untyped]
        except ImportError as e:
            return failsafe_result(package, f"google-genai not installed: {e}", model=f"{self.fallback_model}-failsafe-no-sdk")

        budget = self._thinking_budget()
        # Configure Gemini for JSON output + thinking budget
        # For gemini-3.x flash, thinkingConfig controls reasoning effort.
        generate_config: Dict[str, Any] = {
            "temperature": self.temperature,
            "response_mime_type": "application/json",
        }
        # Only set thinking budget for models that support it (3.x / 2.5 series)
        if any(v in self.model for v in ("3.7", "3.1", "2.5")) and budget is not None:
            # google-genai uses GenerateContentConfig with thinking_config
            try:
                # New SDK path
                config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=budget),
                )
                # Use config object directly
                return self._call_with_config(genai, config, prompt, package, api_key)
            except Exception:
                # Fallback to dict config if ThinkingConfig unavailable
                pass

        # Fallback path: dict-based config (covers flash-lite and older SDK)
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=generate_config,
            )
            text = self._extract_text(response)
            return self._parse_or_failsafe(text, package, retries=self.max_retries)
        except Exception as e:
            # Attempt fallback to flash-lite if primary fails (e.g. model not found / quota)
            if self.fallback_model != self.model:
                try:
                    client2 = genai.Client(api_key=api_key)
                    resp2 = client2.models.generate_content(
                        model=self.fallback_model,
                        contents=prompt,
                        config={"temperature": self.temperature, "response_mime_type": "application/json"},
                    )
                    text2 = self._extract_text(resp2)
                    res = self._parse_or_failsafe(text2, package, retries=self.max_retries)
                    # Attribute to fallback model
                    return JudgeResult(verdict=res.verdict, confidence=res.confidence, reason=res.reason, model=self.fallback_model)
                except Exception:
                    pass
            return failsafe_result(package, f"Gemini API error: {type(e).__name__}: {e}", model=f"{self.fallback_model}-failsafe-api-error")

    def _call_with_config(self, genai: Any, config: Any, prompt: str, package: EvidencePackage, api_key: str) -> JudgeResult:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            text = self._extract_text(response)
            return self._parse_or_failsafe(text, package, retries=self.max_retries)
        except Exception as e:
            if self.fallback_model != self.model:
                try:
                    client2 = genai.Client(api_key=api_key)
                    resp2 = client2.models.generate_content(
                        model=self.fallback_model,
                        contents=prompt,
                        config={"temperature": self.temperature, "response_mime_type": "application/json"},
                    )
                    text2 = self._extract_text(resp2)
                    res = self._parse_or_failsafe(text2, package, retries=self.max_retries)
                    return JudgeResult(verdict=res.verdict, confidence=res.confidence, reason=res.reason, model=self.fallback_model)
                except Exception:
                    pass
            return failsafe_result(package, f"Gemini API error: {type(e).__name__}: {e}", model=f"{self.fallback_model}-failsafe-api-error")

    @staticmethod
    def _extract_text(response: Any) -> str:
        # google-genai response.text is the aggregated text
        if hasattr(response, "text") and response.text:
            return response.text
        # Fallback: iterate candidates
        try:
            parts = response.candidates[0].content.parts  # type: ignore
            return "".join(p.text or "" for p in parts if hasattr(p, "text"))
        except Exception:
            return str(response)

    def _parse_or_failsafe(self, text: str, package: EvidencePackage, retries: int = 1) -> JudgeResult:
        last_err: Optional[str] = None
        raw = text.strip()
        for _ in range(retries + 1):
            try:
                # Handle markdown code fence wrapping
                if raw.startswith("```"):
                    # strip ```json ... ```
                    lines = raw.split("\n")
                    # remove first and last fence lines
                    inner = "\n".join(l for l in lines if not l.strip().startswith("```"))
                    raw = inner.strip()
                data = json.loads(raw)
                # Support both direct object and wrapped
                if isinstance(data, dict) and "verdict" not in data:
                    # Sometimes model wraps in {"result": {...}}
                    for v in data.values():
                        if isinstance(v, dict) and "verdict" in v:
                            data = v
                            break
                result = JudgeResult(
                    verdict=str(data["verdict"]).strip().lower(),  # type: ignore
                    confidence=float(data["confidence"]),
                    reason=str(data["reason"]).strip(),
                    model=self.model,
                )
                validate_judge_result(result)
                return result
            except Exception as e:
                last_err = f"{type(e).__name__}: {e} (raw: {raw[:400]!r})"
                # One retry with explicit JSON-fix prompt is handled by caller via max_retries;
                # here we just fail to failsafe if still bad
                break
        return failsafe_result(package, f"Malformed LLM JSON: {last_err}", model=f"{self.fallback_model}-failsafe-parse-error")


# ---------------------------------------------------------------------------
# OpenRouter client (Nemotron 3.5 Lightning :free and any OpenRouter model)
# ---------------------------------------------------------------------------

@dataclass
class OpenRouterJudgeClient:
    """OpenRouter judge — one LLM call per EvidencePackage, provider-agnostic.

    - model: OpenRouter model id, default nvidia/nemotron-3.5-lightning:free
    - thinking_level: low|medium|high|none — maps to max_tokens via OPENROUTER_MAX_TOKENS (cheap testing)
    - api_key: if None, reads OPENROUTER_API_KEY env var
    - base_url: OpenRouter API base (https://openrouter.ai/api/v1)

    Prompt is identical to Gemini client (model-agnostic). Uses OpenAI SDK with
    response_format json_object for structured verdict/confidence/reason.
    """

    model: str = OPENROUTER_DEFAULT_MODEL
    thinking_level: str = "low"
    api_key: Optional[str] = None
    base_url: str = OPENROUTER_BASE_URL
    max_retries: int = 1
    temperature: float = 0.0
    # Optional site headers for OpenRouter ranking (no effect on judgment)
    site_url: Optional[str] = None
    app_name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.thinking_level not in THINKING_BUDGETS:
            raise ValueError(f"thinking_level must be one of {list(THINKING_BUDGETS)}, got {self.thinking_level!r}")

    @property
    def model_name(self) -> str:
        return self.model

    def set_thinking_level(self, level: str) -> None:
        if level not in THINKING_BUDGETS:
            raise ValueError(f"level must be one of {list(THINKING_BUDGETS)}, got {level!r}")
        self.thinking_level = level

    def _resolve_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        for k in ("OPENROUTER_API_KEY", "OR_API_KEY"):
            v = os.getenv(k)
            if v:
                return v
        return None

    def _max_tokens(self) -> int:
        return OPENROUTER_MAX_TOKENS.get(self.thinking_level, 512)

    def judge(self, package: EvidencePackage) -> JudgeResult:
        prompt = build_judge_prompt(package)
        api_key = self._resolve_api_key()
        if not api_key:
            return failsafe_result(package, "OPENROUTER_API_KEY not set — set env var OPENROUTER_API_KEY", model=f"{FAILSAFE_MODEL}-failsafe-no-key")
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as e:
            return failsafe_result(package, f"openai not installed: {e}", model=f"{FAILSAFE_MODEL}-failsafe-no-sdk")
        try:
            client = OpenAI(api_key=api_key, base_url=self.base_url)
            extra_headers: Dict[str, str] = {}
            if self.site_url:
                extra_headers["HTTP-Referer"] = self.site_url
            if self.app_name:
                extra_headers["X-Title"] = self.app_name
            # Nemotron respects max_tokens for thinking budget; use low/medium to keep cheap
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self._max_tokens(),
                "messages": [
                    {"role": "system", "content": "You are a precise architecture judge. Return JSON only with verdict (meaningful|coincidental|uncertain), confidence 0-1, reason (1-2 sentences)."},
                    {"role": "user", "content": prompt},
                ],
            }
            # Enforce JSON where supported
            try:
                kwargs["response_format"] = {"type": "json_object"}
            except Exception:
                pass
            if extra_headers:
                kwargs["extra_headers"] = extra_headers  # type: ignore
            resp = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
            text = resp.choices[0].message.content or ""
            return self._parse_or_failsafe(text, package)
        except Exception as e:
            return failsafe_result(package, f"OpenRouter API error: {type(e).__name__}: {e}", model=f"{FAILSAFE_MODEL}-failsafe-api-error")

    def _parse_or_failsafe(self, text: str, package: EvidencePackage) -> JudgeResult:
        import re
        raw = text.strip()
        last_err: Optional[str] = None
        for _ in range(self.max_retries + 1):
            try:
                # Strip markdown fences if present
                if "```" in raw:
                    # extract content between fences
                    m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
                    if m:
                        raw = m.group(1).strip()
                # Nemotron often prefixes with reasoning "Here's a thinking process:..." — extract last JSON object containing verdict
                candidate_text = raw
                # If not pure JSON, search for JSON substring with verdict
                if not candidate_text.lstrip().startswith("{"):
                    # Find all {...} blocks and pick last that contains verdict
                    matches = re.findall(r"\{[^{}]*\"verdict\"[^{}]*\}", candidate_text, re.DOTALL)
                    if matches:
                        candidate_text = matches[-1]
                    else:
                        # Broader: find outermost JSON object greedily
                        m2 = re.search(r"\{.*\"verdict\".*\}", candidate_text, re.DOTALL)
                        if m2:
                            candidate_text = m2.group(0)
                data = json.loads(candidate_text)
                if isinstance(data, dict) and "verdict" not in data:
                    for v in data.values():
                        if isinstance(v, dict) and "verdict" in v:
                            data = v
                            break
                result = JudgeResult(
                    verdict=str(data["verdict"]).strip().lower(),  # type: ignore
                    confidence=float(data["confidence"]),
                    reason=str(data["reason"]).strip(),
                    model=self.model,
                )
                validate_judge_result(result)
                return result
            except Exception as e:
                last_err = f"{type(e).__name__}: {e} (raw: {raw[:600]!r})"
                break
        return failsafe_result(package, f"Malformed LLM JSON: {last_err}", model=f"{FAILSAFE_MODEL}-failsafe-parse-error")


# ---------------------------------------------------------------------------
# Main judging entry points
# ---------------------------------------------------------------------------

def judge_evidence_package(
    package: EvidencePackage,
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
) -> JudgeResult:
    """Judge a single EvidencePackage with caching.

    Before LLM call: Candidate+Evidence → deterministic cache key → cache.json → hit? reuse : LLM → store
    """
    cache_key = _cache_key_for_package(package)

    cache: Dict[str, Any] = {}
    if use_cache and cache_path is not None:
        cache = _load_cache(cache_path)
        if cache_key in cache:
            entry = cache[cache_key]
            # Rehydrate JudgeResult from cache
            try:
                result = JudgeResult.from_dict(entry)
                return result
            except Exception:
                pass  # fall through to fresh judgment

    # Cache miss — call LLM/client (one call per package)
    # Client may accept EvidencePackage or prompt string; we pass package
    result: JudgeResult
    if hasattr(client, "judge"):
        result = client.judge(package)  # type: ignore[attr-defined]
    elif callable(client):
        result = client(package)  # type: ignore[call-arg,assignment]
    else:
        raise ValueError(f"Client {client!r} has no judge() method")

    validate_judge_result(result)

    # Store with model/version and package key for debugging
    if use_cache and cache_path is not None:
        # Reload to avoid race with concurrent writes (simple merge)
        cache = _load_cache(cache_path)
        cache[cache_key] = {
            "verdict": result.verdict,
            "confidence": result.confidence,
            "reason": result.reason,
            "model": result.model,
            "cache_key_dict": package.cache_key_dict(),
        }
        _save_cache(cache_path, cache)

    return result


def judge_evidence_packages(
    packages: List[EvidencePackage],
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
) -> List[Tuple[EvidencePackage, JudgeResult]]:
    """Judge a list of EvidencePackages, one LLM call per package (with caching).

    Returns list of (package, result) sorted deterministically.
    Normal cost: 0 for obvious noise (already filtered) + 1 per interesting candidate (cached reuse if unchanged).
    """
    results: List[Tuple[EvidencePackage, JudgeResult]] = []
    for pkg in sorted(packages, key=lambda p: (p.service_a, p.service_b, p.resource_type, p.resource)):
        result = judge_evidence_package(pkg, client, cache_path=cache_path, use_cache=use_cache)
        results.append((pkg, result))
    return results


# Convenience alias for direct Candidate filtering + judging pipeline
def filter_and_judge(
    project: Any,
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
) -> List[Tuple[EvidencePackage, JudgeResult]]:
    """Full Stage 3+4 helper: discovery already done externally, this does filtering + evidence + judging.

    Caller should: candidates = discover_candidates(project)
                   packages = build_evidence_packages(candidates, project)
                   results = judge_evidence_packages(packages, client, cache_path)
    This helper combines the last two steps for convenience when project is available.
    """
    from .filtering import build_evidence_packages
    from .discovery import discover_candidates

    candidates = discover_candidates(project)
    packages = build_evidence_packages(candidates, project)
    return judge_evidence_packages(packages, client, cache_path=cache_path, use_cache=use_cache)
