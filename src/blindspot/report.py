"""
BlindSpot Stage 7: Report — Human-Readable Explanations

Pipeline position: Stage 6 Graph → **Stage 7 Report** → real-world validation

Stage 7 does NOT discover, filter, resolve, judge, call LLM, write cache, or build graph.
It consumes DependencyModel (Stage 5) and optionally graph_data (Stage 6) and renders
each Dependency as a finding that explains why services are potentially coupled,
through which resource, with what evidence and confidence.

What enters Stage 7:
  DependencyModel (service-to-resource, evidence, verdict/confidence/reason, _model hidden)
  graph_data: dict {"nodes": [...], "edges": [...]} optional (Stage 6 DATA)

What leaves Stage 7:
  ReportData {summary, findings} → report.json (machine) + report.md (human)
  Each finding exposes resource/resource_type/value + evidence (resolved_service/
  resolved_image/is_internal/reference_type/related_config/filtering_signals) +
  verdict/confidence/reason. Model/provider never exposed (stays in logging).

Why this is the end: Tier 1 is demoable after Report — real-world validation
runs same pipeline on one OSS repo and checks report explains Service↔Resource
without exposing model and without claiming direct service→service calls.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model import Dependency, DependencyModel


@dataclass(frozen=True)
class ReportFinding:
    """One human-readable finding — external view, model hidden."""

    service_a: str
    service_b: str
    resource: str
    resource_type: str
    value: Optional[str]
    evidence: Dict[str, Any]  # EvidencePackage.to_dict() — resolved + related + signals
    verdict: str  # meaningful | coincidental | uncertain
    confidence: float  # 0.0-1.0 mandatory
    reason: str

    @classmethod
    def from_dependency(cls, dep: Dependency) -> "ReportFinding":
        """Build one finding from a Dependency (Stage 5).

        - Copies service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason
        - Never copies dep._model — model stays in logging (cache.json)
        - Evidence is kept verbatim (is_internal, resolved_service/image, related_config, filtering_signals)
        """
        return cls(
            service_a=dep.service_a,
            service_b=dep.service_b,
            resource=dep.resource,
            resource_type=dep.resource_type,
            value=dep.value,
            evidence=dep.evidence.to_dict(),
            verdict=dep.verdict,
            confidence=float(dep.confidence),
            reason=dep.reason.strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_a": self.service_a,
            "service_b": self.service_b,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "value": self.value,
            "evidence": dict(self.evidence),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReportData:
    """Full report — JSON serializable, deterministic, provider-agnostic."""

    findings: tuple  # Tuple[ReportFinding, ...]
    summary: Dict[str, Any]
    graph_summary: Optional[Dict[str, Any]] = None
    generated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "graph_summary": dict(self.graph_summary) if self.graph_summary else None,
            "generated_at": self.generated_at,
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False)

    def to_markdown(self) -> str:
        """Human-readable markdown — each finding explains Service <-> Resource with evidence + confidence."""
        lines: List[str] = []
        lines.append("# BlindSpot Report")
        lines.append("")
        s = self.summary
        lines.append(f"**Summary:** {s.get('meaningful',0)} meaningful / {s.get('total',0)} total findings -- {s.get('services',0)} services, {s.get('resources',0)} resources")
        if self.graph_summary:
            gs = self.graph_summary
            lines.append(f"Graph: {gs.get('nodes',0)} nodes ({gs.get('service_nodes',0)} services, {gs.get('resource_nodes',0)} resources), {gs.get('edges',0)} edges")
        lines.append(f"Generated: {self.generated_at}")
        lines.append("")
        if not self.findings:
            lines.append("_No meaningful dependencies found -- all candidates were filtered as generic or judged coincidental/uncertain._")
            return "\n".join(lines)
        for i, f in enumerate(self.findings, 1):
            # Resource display — env_var with value, named_volume without
            res_display = f.resource + (f"={f.value}" if f.value is not None else "")
            lines.append(f"## {i}. {f.service_a} <-> {f.service_b} through `{res_display}` ({f.resource_type}) -- confidence {f.confidence:.2f} **{f.verdict}**")
            lines.append("")
            lines.append(f"**Reason:** {f.reason}")
            lines.append("")
            ev = f.evidence
            # Resolution context — what the value points to
            if ev.get("reference_type") == "compose_service":
                lines.append(f"**Resolution:** `{f.value!r}` -> Compose service `{ev.get('resolved_service')}` (image: {ev.get('resolved_image') or 'unknown'}) -- internal coupling")
            elif ev.get("reference_type") == "named_volume":
                vt = ev.get("volume_targets")
                if vt:
                    vt_str = ", ".join(f"{k}:{v}" for k, v in sorted(vt.items()))
                    lines.append(f"**Resolution:** named volume `{f.resource}` targets {vt_str} -- shared filesystem (internal)")
                else:
                    lines.append(f"**Resolution:** named volume `{f.resource}` -- shared filesystem")
            elif ev.get("reference_type") == "external":
                lines.append(f"**Resolution:** `{f.value!r}` does not resolve to a Compose service -- external/unknown")
            else:
                lines.append(f"**Resolution:** {ev.get('reference_type', 'unknown')} -- insufficient evidence to resolve")
            # Related bounded config
            rc = ev.get("related_config", {})
            if rc:
                parts = []
                for svc, cfg in sorted(rc.items()):
                    if cfg:
                        kv = ", ".join(f"{k}={v!r}" for k, v in sorted(cfg.items()))
                        parts.append(f"{svc}: {kv}")
                if parts:
                    lines.append(f"**Related config (bounded):** {'; '.join(parts)}")
            # Filtering signals
            sig = ev.get("filtering_signals", {})
            if sig:
                lines.append(f"**Filtering:** generic_variable={str(sig.get('generic_variable')).lower()} same_value={str(sig.get('same_value')).lower()} resolved_reference={sig.get('resolved_reference')}")
            lines.append("")
        return "\n".join(lines)


def build_report(
    model: DependencyModel,
    graph_data: Optional[Dict[str, Any]] = None,
    meaningful_only: bool = True,
) -> ReportData:
    """Build ReportData from DependencyModel (and optionally graph_data).

    What enters Stage 7: DependencyModel from Stage 5 (service-to-resource, _model hidden) + optional graph_data from Stage 6.
    What leaves Stage 7: ReportData {summary, findings, graph_summary} — JSON + markdown, model never exposed.

    - meaningful_only=True (default) reports only meaningful couplings (primary report).
    - meaningful_only=False includes coincidental/uncertain for debugging.
    - Deterministic: findings sorted (service_a, service_b, resource_type, resource, value).
    - Preserves confidence/reason/evidence verbatim, does not modify verdict.
    """
    deps = list(model.meaningful_only().dependencies if meaningful_only else model.dependencies)
    deps.sort(key=lambda d: (d.service_a, d.service_b, d.resource_type, d.resource, str(d.value or "")))

    findings = tuple(ReportFinding.from_dependency(d) for d in deps)

    # Summary — deterministic counts
    all_deps = list(model.dependencies)
    services = sorted({d.service_a for d in all_deps} | {d.service_b for d in all_deps}) if all_deps else []
    # Resource identities — dedup by resource+type+value (same as graph)
    res_keys = set()
    for d in deps:
        key = f"{d.resource_type}:{d.resource}={d.value}" if d.value is not None else f"{d.resource_type}:{d.resource}"
        res_keys.add(key)

    summary: Dict[str, Any] = {
        "total": len(all_deps),
        "meaningful": len([d for d in all_deps if d.verdict == "meaningful"]),
        "coincidental": len([d for d in all_deps if d.verdict == "coincidental"]),
        "uncertain": len([d for d in all_deps if d.verdict == "uncertain"]),
        "reported": len(findings),
        "services": len(services),
        "resources": len(res_keys),
    }

    graph_summary: Optional[Dict[str, Any]] = None
    if graph_data is not None:
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        graph_summary = {
            "nodes": len(nodes),
            "edges": len(edges),
            "service_nodes": len([n for n in nodes if n.get("type") == "service"]),
            "resource_nodes": len([n for n in nodes if n.get("type") == "resource"]),
        }

    return ReportData(findings=findings, summary=summary, graph_summary=graph_summary)
