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

# Grouped evidence (Prompt 2) — lazy import to avoid circular
try:
    from .aggregation import GroupedEvidencePackage  # type: ignore
except Exception:  # pragma: no cover
    GroupedEvidencePackage = Any  # type: ignore

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

    Contains: SERVICE A/B, SHARED CONFIGURATION, VALUES, RESOLUTION (with
    new distinct states and normalized identity), RELATED CONFIGURATION (bounded),
    DETERMINISTIC FILTERING + identity strength signals.
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

    # New resolution rendering with distinct states
    # Use resolution_status / protocol / normalized_identity / chain / final_value
    resolution_status = getattr(package, "resolution_status", package.reference_type)
    resource_protocol = getattr(package, "resource_protocol", None)
    normalized_identity = getattr(package, "normalized_identity", None)
    identity_strength = getattr(package, "identity_strength", "unknown")
    final_value = getattr(package, "final_value", package.value)
    unresolved_vars = getattr(package, "unresolved_vars", ())
    is_cyclic = getattr(package, "is_cyclic", False)
    chain = getattr(package, "resolution_chain", ())

    if package.resource_type == "named_volume":
        vol_str = ""
        if package.volume_targets:
            vol_str = ", ".join(f"{svc}:{t!r}" for svc, t in sorted(package.volume_targets.items()))
            vol_str = f" targets {vol_str}"
        resolution = f"named volume \"{package.resource}\"{vol_str} -- shared filesystem (internal)\n  resolution_status: internal"
        if normalized_identity:
            resolution += f"\n  normalized_identity: {normalized_identity}"
    elif resolution_status == "internal":
        resolution = f"{package.value!r} -> Compose service \"{package.resolved_service}\" (image: {package.resolved_image or 'unknown'}) -- INTERNAL coupling"
        if resource_protocol:
            resolution += f"\n  protocol: {resource_protocol}"
        if normalized_identity:
            resolution += f"\n  normalized_identity: {normalized_identity}"
        resolution += f"\n  identity_strength: {identity_strength}"
        if final_value and final_value != package.value:
            resolution += f"\n  final_value: {final_value!r}"
    elif resolution_status == "external_confirmed":
        resolution = f"{package.value!r} -> final {final_value!r} -- EXTERNAL_CONFIRMED"
        if resource_protocol:
            resolution += f"\n  protocol: {resource_protocol}"
        if normalized_identity:
            resolution += f"\n  normalized_identity: {normalized_identity} (credentials stripped, deterministic)"
        resolution += f"\n  identity_strength: {identity_strength}  -- both services point to same external resource"
        if normalized_identity and identity_strength == "exact":
            resolution += " (EXACT_RESOURCE_IDENTITY)"
    elif resolution_status == "partial":
        unresolved_str = ", ".join(unresolved_vars) if unresolved_vars else "none listed"
        resolution = f"{package.value!r} -> final {final_value!r} -- PARTIAL (some components unresolved: {unresolved_str})"
        if resource_protocol:
            resolution += f"\n  protocol: {resource_protocol} (partial)"
        if normalized_identity:
            resolution += f"\n  partial_identity: {normalized_identity}"
        resolution += f"\n  identity_strength: {identity_strength}  -- same configuration template, physical identity incomplete (CONFIGURATION_IDENTITY possible)"
        if is_cyclic:
            resolution += "\n  note: resolution involved cycle or incomplete chain"
    else:  # unresolved
        unresolved_str = ", ".join(unresolved_vars) if unresolved_vars else "unknown vars"
        resolution = f"{package.value!r} -> final {final_value!r} -- UNRESOLVED ({unresolved_str})"
        if is_cyclic:
            resolution += " [cycle detected]"
        resolution += " -- cannot determine final resource identity from deterministic evidence"
        if resource_protocol:
            resolution += f"\n  tentative_protocol: {resource_protocol} (unconfirmed)"
        if normalized_identity:
            resolution += f"\n  tentative_identity: {normalized_identity}"
        resolution += f"\n  identity_strength: {identity_strength}"

    # Append bounded chain if present (max 5 steps already bounded)
    if chain:
        chain_lines = []
        for step in chain[:5]:
            # step is dict from ResolutionStep.to_dict()
            if isinstance(step, dict):
                chain_lines.append(f"    {step.get('variable')} via {step.get('source')}: {step.get('from_value')!r} -> {step.get('to_value')!r}")
            else:
                chain_lines.append(f"    {step}")
        resolution += "\n  resolution_chain:\n" + "\n".join(chain_lines)
        if len(chain) > 5:
            resolution += f"\n    (+{len(chain)-5} more steps bounded)"

    # Values display
    if package.resource_type == "named_volume":
        values_str = f"shared volume \"{package.resource}\" mounted by both services\n  normalized: {normalized_identity or package.resource}"
    elif package.value is not None:
        if final_value is not None and final_value != package.value:
            values_str = f"{package.service_a} -> {package.value!r} => final {final_value!r}\n{package.service_b} -> {package.value!r} => final {final_value!r}  (same_value: true, unresolved: {list(unresolved_vars) if unresolved_vars else 'none'})"
        else:
            values_str = f"{package.service_a} -> {package.value!r}\n{package.service_b} -> {package.value!r}  (same_value: true, status: {resolution_status})"
            if normalized_identity:
                values_str += f"\n  normalized_identity: {normalized_identity} ({identity_strength})"
    else:
        values_str = f"{package.service_a} / {package.service_b} values differ or absent (same_value: false)"

    # Filtering signals include new fields
    filtering_block = (
        f"generic_variable: {str(package.generic_variable).lower()}\n"
        f"same_value: {str(package.same_value).lower()}\n"
        f"resolved_reference: {package.reference_type}\n"
        f"resolution_status: {resolution_status}\n"
        f"identity_strength: {identity_strength}\n"
        f"resource_protocol: {resource_protocol or 'unknown'}"
    )

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

DETERMINISTIC FILTERING AND IDENTITY
{filtering_block}

TASK
Determine whether the evidence indicates:
1. meaningful coupling — shared resource implies services are implicitly coupled (e.g. shared DB host/volume, same normalized external resource)
2. coincidental overlap — same name/value by chance, no real coupling (e.g. generic PORT, unrelated strings)
3. insufficient evidence — cannot decide from given facts

Confidence guidance (reflect evidence strength, not just wording):
- High confidence (0.85-1.0): resolution_status internal/external_confirmed + identity_strength exact + normalized_identity deterministically established
- Medium confidence (0.6-0.85): strong configuration convergence but identity_strength config / status partial (same template, some components unresolved)
- Lower confidence (0.0-0.6): ambiguous, unresolved, unknown protocol, or only suggestive config overlap

Return JSON with:
- verdict: "meaningful" | "coincidental" | "uncertain"
- confidence: 0.0-1.0 (mandatory, how confident you are — reflect strength above)
- reason: short explanation (1-2 sentences) referencing normalized identity or configuration template
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
    # Atomic write via temp file to avoid corruption on concurrent/crash
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(p.parent) if p.parent.exists() else None, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(wrapped, indent=2, sort_keys=True, ensure_ascii=False))
        Path(tmp_path).replace(p)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        # Fallback to direct write
        try:
            p.write_text(json.dumps(wrapped, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


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
                    # First try: find all balanced JSON objects containing "verdict" (handles nested braces in reason)
                    # Fallback to simple non-greedy extraction if balanced parsing fails.
                    def _extract_balanced(s: str) -> Optional[str]:
                        last: Optional[str] = None
                        i = 0
                        while i < len(s):
                            if s[i] == "{":
                                depth = 0
                                start = i
                                for j in range(i, len(s)):
                                    if s[j] == "{":
                                        depth += 1
                                    elif s[j] == "}":
                                        depth -= 1
                                        if depth == 0:
                                            block = s[start:j+1]
                                            if '"verdict"' in block:
                                                last = block
                                            i = j
                                            break
                                # end for
                            i += 1
                        return last
                    balanced = _extract_balanced(candidate_text)
                    if balanced:
                        candidate_text = balanced
                    else:
                        matches = re.findall(r"\{[^{}]*\"verdict\"[^{}]*\}", candidate_text, re.DOTALL)
                        if matches:
                            candidate_text = matches[-1]
                        else:
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


# ---------------------------------------------------------------------------
# Grouped judgment (Prompt 2 — resource-centric)
# ---------------------------------------------------------------------------

def build_grouped_judge_prompt(grouped: Any) -> str:
    """Build prompt for one GroupedEvidencePackage.

    Contains: resource identity/protocol/status/strength, services involved,
    configuration evidence grouped by service, bounded unresolved vars, representative chain.
    """
    # Configuration evidence grouped by service
    config_lines = []
    for svc in sorted(grouped.configuration_evidence.keys()):
        vars_list = grouped.configuration_evidence[svc]
        if vars_list:
            config_lines.append(f"  {svc}: {', '.join(sorted(vars_list))}")
        else:
            config_lines.append(f"  {svc}: (none)")
    config_str = "\n".join(config_lines) if config_lines else "  (none)"

    services_str = ", ".join(sorted(grouped.services))
    obs_resources_str = ", ".join(sorted(grouped.observation_resources)) if grouped.observation_resources else "(none)"

    # Resolution human readable
    status = grouped.resolution_status
    protocol = grouped.resource_protocol or "unknown"
    identity = grouped.resource_identity or "(unknown)"
    strength = grouped.identity_strength
    unresolved = ", ".join(sorted(grouped.unresolved_vars)) if grouped.unresolved_vars else "none"
    chain = grouped.representative_chain

    if status == "internal":
        res_line = f"INTERNAL — {identity} (protocol: {protocol}, strength: {strength})"
    elif status == "external_confirmed":
        res_line = f"EXTERNAL_CONFIRMED — {identity} (protocol: {protocol}, strength: {strength})"
    elif status == "partial":
        res_line = f"PARTIAL — {identity} (protocol: {protocol}, strength: {strength}, unresolved: {unresolved})"
    else:
        res_line = f"UNRESOLVED — {identity} (protocol: {protocol}, strength: {strength}, unresolved: {unresolved})"

    chain_str = ""
    if chain:
        chain_lines = []
        for step in chain[:3]:
            if isinstance(step, dict):
                chain_lines.append(f"    {step.get('variable')} via {step.get('source')}: {step.get('from_value')!r} -> {step.get('to_value')!r}")
        chain_str = "\n".join(chain_lines)
        if chain_str:
            res_line += f"\n  representative chain:\n{chain_str}"

    return f"""You are evaluating one resource group for implicit cross-service coupling.

SHARED RESOURCE
{identity}  (protocol: {protocol}, type: {grouped.resource_type})
Resolution: {res_line}
Identity strength: {strength}  (exact = proven physical, config = same configuration template, unknown = insufficient)
Services involved ({grouped.service_count}): {services_str}
Configuration observations ({grouped.evidence_count}): {obs_resources_str}

CONFIGURATION EVIDENCE BY SERVICE
{config_str}

UNRESOLVED COMPONENTS
{unresolved}

TASK
Determine whether these {grouped.service_count} services exhibit meaningful implicit coupling through this shared resource/configuration.

1. meaningful — shared resource implies services are implicitly coupled (e.g. same DB, same volume, same external service)
2. coincidental — same name/value by chance, no real coupling
3. insufficient — cannot decide from given facts

Confidence guidance:
- High (0.85-1.0): resolution internal/external_confirmed + strength exact + normalized identity deterministically established
- Medium (0.6-0.85): strong config convergence but strength config / status partial (same template, some components unresolved)
- Lower (0.0-0.6): ambiguous, unresolved, unknown protocol, only suggestive

Return JSON with:
- verdict: "meaningful" | "coincidental" | "uncertain"
- confidence: 0.0-1.0 (reflect strength above)
- reason: 1-2 sentences, must refer to the group (e.g. "All three services..." not "Both services share DATABASE_URL")
"""


def _cache_key_for_grouped(grouped: Any) -> str:
    payload = grouped.cache_key_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def failsafe_grouped_result(grouped: Any, reason: str, model: str = FAILSAFE_MODEL) -> JudgeResult:
    msg = reason.strip()[:300] if reason.strip() else "LLM call failed"
    ident = getattr(grouped, "resource_identity", "") or getattr(grouped, "grouping_key", "group")
    return JudgeResult(
        verdict="uncertain",
        confidence=0.5,
        reason=f"Failsafe ({FAILSAFE_MODEL}): {msg} — group was {ident}",
        model=model,
    )


def judge_grouped_package(
    grouped: Any,
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
) -> JudgeResult:
    cache_key = _cache_key_for_grouped(grouped)
    cache: Dict[str, Any] = {}
    if use_cache and cache_path is not None:
        cache = _load_cache(cache_path)
        if cache_key in cache:
            try:
                return JudgeResult.from_dict(cache[cache_key])
            except Exception:
                pass

    prompt = build_grouped_judge_prompt(grouped)

    # Try client grouped method first, then fallback to direct LLM call via prompt
    result: Optional[JudgeResult] = None
    # If client has judge_grouped, use it
    if hasattr(client, "judge_grouped"):
        try:
            result = client.judge_grouped(grouped)  # type: ignore
        except Exception as e:
            result = failsafe_grouped_result(grouped, f"client.judge_grouped error: {e}", model=f"{FAILSAFE_MODEL}-failsafe-grouped")
    elif hasattr(client, "judge"):
        # For backward compat, try calling judge with grouped — clients that only handle EvidencePackage will fail gracefully
        # Instead, perform direct LLM call using the grouped prompt via the client's underlying LLM logic
        # We reuse the client's _resolve_api_key and LLM call pattern by constructing a tiny wrapper
        try:
            # If client is Gemini/OpenRouter, we can call its LLM directly with prompt
            # Detect client type by presence of _resolve_api_key
            if hasattr(client, "_resolve_api_key"):
                # Use generic LLM dispatch: build JudgeResult via direct API call with grouped prompt
                # We implement a helper inline
                import os as _os
                # Gemini vs OpenRouter dispatch
                if client.__class__.__name__ == "GeminiJudgeClient":
                    api_key = client._resolve_api_key()  # type: ignore
                    if not api_key:
                        result = failsafe_grouped_result(grouped, "GEMINI_API_KEY not set", model=f"{client.fallback_model}-failsafe-no-key")  # type: ignore
                    else:
                        try:
                            from google import genai  # type: ignore
                            from google.genai import types  # type: ignore
                            g_client = genai.Client(api_key=api_key)
                            budget = client._thinking_budget()  # type: ignore
                            # Try with thinking config
                            try:
                                cfg = types.GenerateContentConfig(
                                    temperature=client.temperature,  # type: ignore
                                    response_mime_type="application/json",
                                    thinking_config=types.ThinkingConfig(thinking_budget=budget),
                                )
                                resp = g_client.models.generate_content(model=client.model, contents=prompt, config=cfg)  # type: ignore
                            except Exception:
                                resp = g_client.models.generate_content(model=client.model, contents=prompt, config={"temperature": client.temperature, "response_mime_type": "application/json"})  # type: ignore
                            text = resp.text if hasattr(resp, "text") and resp.text else str(resp)
                            # Parse
                            raw = text.strip()
                            if raw.startswith("```"):
                                raw = "\n".join(l for l in raw.split("\n") if not l.strip().startswith("```")).strip()
                            data = json.loads(raw)
                            if isinstance(data, dict) and "verdict" not in data:
                                for v in data.values():
                                    if isinstance(v, dict) and "verdict" in v:
                                        data = v
                                        break
                            result = JudgeResult(verdict=str(data["verdict"]).lower(), confidence=float(data["confidence"]), reason=str(data["reason"]).strip(), model=client.model)  # type: ignore
                            validate_judge_result(result)
                        except Exception as e:
                            result = failsafe_grouped_result(grouped, f"Gemini grouped error: {type(e).__name__}: {e}")
                elif client.__class__.__name__ == "OpenRouterJudgeClient":
                    api_key = client._resolve_api_key()  # type: ignore
                    if not api_key:
                        result = failsafe_grouped_result(grouped, "OPENROUTER_API_KEY not set", model=f"{FAILSAFE_MODEL}-failsafe-no-key")
                    else:
                        try:
                            from openai import OpenAI  # type: ignore
                            oai = OpenAI(api_key=api_key, base_url=client.base_url)  # type: ignore
                            resp = oai.chat.completions.create(
                                model=client.model,  # type: ignore
                                temperature=client.temperature,  # type: ignore
                                max_tokens=client._max_tokens(),  # type: ignore
                                messages=[
                                    {"role": "system", "content": "You are a precise architecture judge. Return JSON only with verdict (meaningful|coincidental|uncertain), confidence 0-1, reason (1-2 sentences)."},
                                    {"role": "user", "content": prompt},
                                ],
                                response_format={"type": "json_object"},  # type: ignore
                            )
                            text = resp.choices[0].message.content or ""
                            import re as _re
                            raw = text.strip()
                            if "```" in raw:
                                m = _re.search(r"```(?:json)?\s*(.*?)\s*```", raw, _re.DOTALL)
                                if m:
                                    raw = m.group(1).strip()
                            if not raw.lstrip().startswith("{"):
                                # balanced extraction handles reason containing braces
                                def _balanced(s: str):
                                    last = None
                                    i = 0
                                    while i < len(s):
                                        if s[i] == "{":
                                            depth = 0
                                            start = i
                                            for j in range(i, len(s)):
                                                if s[j] == "{":
                                                    depth += 1
                                                elif s[j] == "}":
                                                    depth -= 1
                                                    if depth == 0:
                                                        block = s[start:j+1]
                                                        if '"verdict"' in block:
                                                            last = block
                                                        i = j
                                                        break
                                        i += 1
                                    return last
                                bal = _balanced(raw)
                                if bal:
                                    raw = bal
                                else:
                                    ms = _re.findall(r"\{[^{}]*\"verdict\"[^{}]*\}", raw, _re.DOTALL)
                                    if ms:
                                        raw = ms[-1]
                            data = json.loads(raw)
                            if isinstance(data, dict) and "verdict" not in data:
                                for v in data.values():
                                    if isinstance(v, dict) and "verdict" in v:
                                        data = v
                                        break
                            result = JudgeResult(verdict=str(data["verdict"]).lower(), confidence=float(data["confidence"]), reason=str(data["reason"]).strip(), model=client.model)  # type: ignore
                            validate_judge_result(result)
                        except Exception as e:
                            result = failsafe_grouped_result(grouped, f"OpenRouter grouped error: {type(e).__name__}: {e}")
                else:
                    # Generic client: try calling judge with grouped package directly
                    result = client.judge(grouped)  # type: ignore
            else:
                result = client.judge(grouped)  # type: ignore
        except Exception as e:
            result = failsafe_grouped_result(grouped, f"judge grouped fallback error: {e}")

    if result is None:
        result = failsafe_grouped_result(grouped, "No client method succeeded for grouped judgment")

    validate_judge_result(result)

    if use_cache and cache_path is not None:
        cache = _load_cache(cache_path)
        cache[cache_key] = {
            "verdict": result.verdict,
            "confidence": result.confidence,
            "reason": result.reason,
            "model": result.model,
            "cache_key_dict": grouped.cache_key_dict(),
        }
        _save_cache(cache_path, cache)

    return result


def judge_grouped_packages(
    grouped_packages: List[Any],
    client: Any,
    cache_path: Optional[Union[Path, str]] = None,
    use_cache: bool = True,
) -> List[Tuple[Any, JudgeResult]]:
    results: List[Tuple[Any, JudgeResult]] = []
    for pkg in sorted(grouped_packages, key=lambda g: g.grouping_key):
        result = judge_grouped_package(pkg, client, cache_path=cache_path, use_cache=use_cache)
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
