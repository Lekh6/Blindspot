"""
BlindSpot Stage 4: LLM Judge — Semantic Judgment (One Call Per Surviving Candidate)

Per updated AGENTS.md §4:

- Judges pre-extracted bounded EvidencePackage from Stage 3, not whole repo.
- Normal cost: 0 LLM calls for obvious noise + 1 LLM call per interesting candidate.
- No multiple LLM prompts per evidence item; one package → one call.
- Structured output: verdict ∈ {meaningful, coincidental, uncertain}, confidence 0-1 mandatory, reason.
- Verdicts cached in cache.json with candidate+evidence-aware key (EvidencePackage.cache_key_dict).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal, Protocol, Tuple, Union
import time

from .filtering import EvidencePackage

Verdict = Literal["meaningful", "coincidental", "uncertain"]

VALID_VERDICTS = {"meaningful", "coincidental", "uncertain"}


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


@dataclass
class MockJudgeClient:
    """Deterministic mock for tests — no API key needed.

    Heuristic:
    - named_volume → meaningful (shared filesystem)
    - compose_service resolved (HOST→service) → meaningful
    - generic_variable true → coincidental
    - otherwise external HOST-like with same DB_* → meaningful, else uncertain
    Useful for validating pipeline without calling real LLM.
    """

    model: str = "mock-heuristic-v1"

    @property
    def model_name(self) -> str:
        return self.model

    def judge(self, package: EvidencePackage) -> JudgeResult:
        if package.resource_type == "named_volume":
            return JudgeResult(verdict="meaningful", confidence=0.92, reason="Both services mount same named volume -- shared filesystem implies coupling.", model=self.model)
        if package.reference_type == "compose_service":
            return JudgeResult(verdict="meaningful", confidence=0.95, reason=f"Both services resolve {package.resource}={package.value!r} to Compose service \"{package.resolved_service}\" ({package.resolved_image}) -- shared internal service.", model=self.model)
        if package.generic_variable:
            return JudgeResult(verdict="coincidental", confidence=0.9, reason=f"Generic key {package.resource!r} -- standard coincidence, not coupling.", model=self.model)
        if package.value is None:
            return JudgeResult(verdict="coincidental", confidence=0.85, reason="Same key with different values -- coincidence, not shared config.", model=self.model)
        # For remaining specific external values (e.g. DB_HOST=shared-db external)
        # Treat DB_* / REDIS_* etc as likely coupling if shared same value
        upper = package.resource.upper()
        if any(upper.startswith(p) for p in ("DB_", "DATABASE", "REDIS", "KAFKA", "RABBIT", "POSTGRES", "MYSQL")):
            return JudgeResult(verdict="meaningful", confidence=0.78, reason=f"Shared {package.resource}={package.value!r} with same value -- likely shared external resource, meaningful.", model=self.model)
        return JudgeResult(verdict="uncertain", confidence=0.5, reason="No clear signal -- shared value but insufficient context to decide.", model=self.model)


@dataclass
class FixedJudgeClient:
    """Test helper that returns pre-canned results by (resource, value) map."""

    mapping: Dict[str, JudgeResult]
    model: str = "fixed-test"

    @property
    def model_name(self) -> str:
        return self.model

    def judge(self, package: EvidencePackage) -> JudgeResult:
        # Key by resource or (resource, value)
        key = f"{package.resource}={package.value}" if package.value else package.resource
        if key in self.mapping:
            r = self.mapping[key]
            return JudgeResult(verdict=r.verdict, confidence=r.confidence, reason=r.reason, model=self.model)
        if package.resource in self.mapping:
            r = self.mapping[package.resource]
            return JudgeResult(verdict=r.verdict, confidence=r.confidence, reason=r.reason, model=self.model)
        # Fallback heuristic like Mock
        return MockJudgeClient(model=self.model).judge(package)


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
