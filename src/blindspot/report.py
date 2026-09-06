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
from typing import Any, Dict, List, Optional, Tuple

from .model import Dependency, DependencyModel

# Grouped model (Prompt 2) — lazy
try:
    from .coupling import CouplingGroup, CouplingModel  # type: ignore
except Exception:  # pragma: no cover
    CouplingGroup = Any  # type: ignore
    CouplingModel = Any  # type: ignore


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
            # Resource display — prefer normalized_identity for external/internal resources
            ev = f.evidence
            norm = ev.get("normalized_identity")
            if norm:
                res_display = norm
            else:
                res_display = f.resource + (f"={f.value}" if f.value is not None else "")
            lines.append(f"## {i}. {f.service_a} <-> {f.service_b} through `{res_display}` ({f.resource_type}) -- confidence {f.confidence:.2f} **{f.verdict}**")
            lines.append("")
            lines.append(f"**Reason:** {f.reason}")
            lines.append("")
            # Resolution context — new distinct states
            status = ev.get("resolution_status") or ev.get("reference_type", "unknown")
            protocol = ev.get("resource_protocol")
            norm = ev.get("normalized_identity")
            final_val = ev.get("final_value")
            strength = ev.get("identity_strength", "unknown")
            unresolved = ev.get("unresolved_vars", [])
            is_cyclic = ev.get("is_cyclic", False)
            if ev.get("reference_type") == "named_volume" or status == "internal" and f.resource_type == "named_volume":
                vt = ev.get("volume_targets")
                if vt:
                    vt_str = ", ".join(f"{k}:{v}" for k, v in sorted(vt.items()))
                    lines.append(f"**Resolution:** named volume `{f.resource}` targets {vt_str} -- shared filesystem (internal)")
                else:
                    lines.append(f"**Resolution:** named volume `{f.resource}` -- shared filesystem (internal)")
                if norm:
                    lines.append(f"**Normalized:** `{norm}`")
            elif status == "internal":
                lines.append(f"**Resolution:** `{f.value!r}` -> Compose service `{ev.get('resolved_service')}` (image: {ev.get('resolved_image') or 'unknown'}) -- INTERNAL coupling")
                if protocol:
                    lines.append(f"**Protocol:** {protocol}")
                if norm:
                    lines.append(f"**Normalized:** `{norm}` ({strength})")
                if final_val and final_val != f.value:
                    lines.append(f"**Final value:** `{final_val}`")
            elif status == "external_confirmed":
                lines.append(f"**Resolution:** `{f.value!r}` -> `{final_val or f.value}` -- EXTERNAL_CONFIRMED")
                if protocol:
                    lines.append(f"**Protocol:** {protocol}")
                if norm:
                    lines.append(f"**Normalized:** `{norm}` ({strength})")
                else:
                    lines.append(f"**Identity strength:** {strength}")
            elif status == "partial":
                lines.append(f"**Resolution:** `{f.value!r}` -> `{final_val or f.value}` -- PARTIAL (unresolved: {', '.join(unresolved) if unresolved else 'none'}, cyclic={is_cyclic})")
                if protocol:
                    lines.append(f"**Protocol:** {protocol} (partial)")
                if norm:
                    lines.append(f"**Partial identity:** `{norm}` ({strength})")
                else:
                    lines.append(f"**Identity strength:** {strength} -- same configuration template, physical identity incomplete")
            else:  # unresolved
                line = f"**Resolution:** `{f.value!r}` -> `{final_val or f.value}` -- UNRESOLVED"
                if unresolved:
                    line += f" (unresolved vars: {', '.join(unresolved)})"
                if is_cyclic:
                    line += " [cycle detected]"
                lines.append(line)
                if protocol:
                    lines.append(f"**Tentative protocol:** {protocol}")
                if norm:
                    lines.append(f"**Tentative identity:** `{norm}`")
                lines.append(f"**Identity strength:** {strength} -- insufficient evidence to prove physical resource")
            # Resolution chain
            chain = ev.get("resolution_chain", [])
            if chain:
                lines.append(f"**Resolution chain ({len(chain)} steps):**")
                for step in chain[:5]:
                    lines.append(f"  - {step.get('variable')} via {step.get('source')}: {step.get('from_value')!r} -> {step.get('to_value')!r}")
                if len(chain) > 5:
                    lines.append(f"  - (+{len(chain)-5} more steps bounded)")
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
                lines.append(f"**Filtering:** generic_variable={str(sig.get('generic_variable')).lower()} same_value={str(sig.get('same_value')).lower()} resolved_reference={sig.get('resolved_reference')} resolution_status={status} identity_strength={strength}")
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


# ---------------------------------------------------------------------------
# Grouped Report (Prompt 2 — resource-centric, human-readable)
# ---------------------------------------------------------------------------

def _human_title(group: Any) -> str:
    """Deterministic resource-centric title, not internal identity."""
    proto = (group.resource_protocol or "").lower()
    strength = group.identity_strength
    rtype = group.resource_type
    # Named volume
    if rtype == "named_volume" or (group.resource_identity and group.resource_identity.startswith("named_volume|")):
        # Extract volume name
        name = group.resource_identity.split("|", 1)[-1] if group.resource_identity else "Volume"
        return f"Shared Volume: {name}"
    # Database-like
    if proto in ("postgresql", "postgres", "mysql"):
        if strength == "exact":
            return "Shared PostgreSQL Database" if proto in ("postgresql", "postgres") else "Shared MySQL Database"
        else:
            return "Shared PostgreSQL Database Configuration" if proto in ("postgresql", "postgres") else "Shared MySQL Database Configuration"
    if proto in ("mongodb", "mongodb+srv"):
        return "Shared MongoDB Database" if strength == "exact" else "Shared MongoDB Configuration"
    if proto == "redis":
        return "Shared Redis Database" if strength == "exact" else "Shared Redis Configuration"
    if proto and proto != "unknown":
        # Generic: Shared <Proto> Resource
        pretty = proto.capitalize()
        return f"Shared {pretty} Resource" if strength == "exact" else f"Shared {pretty} Configuration"
    # Fallback for unknown
    if rtype == "env_var" and strength == "config":
        return "Shared Configuration"
    return "Shared Resource Configuration"


def _human_resolution(status: str, strength: str) -> str:
    mapping = {
        ("internal", "exact"): "Internal — exact resource identity",
        ("external_confirmed", "exact"): "Confirmed external resource — exact identity",
        ("partial", "config"): "Partial — shared configuration-level identity",
        ("unresolved", "config"): "Unresolved — shared configuration template",
        ("unresolved", "unknown"): "Unresolved — insufficient evidence",
    }
    return mapping.get((status, strength), f"{status.capitalize()} — {strength}")


def _confidence_label(conf: float) -> str:
    if conf >= 0.85:
        return "High"
    if conf >= 0.6:
        return "Medium"
    return "Low"


@dataclass(frozen=True)
class GroupedReportFinding:
    """One grouped finding — human readable, model hidden."""

    title: str
    resource_identity: Optional[str]
    resource_protocol: Optional[str]
    resource_type: str
    resolution_status: str
    identity_strength: str
    services: Tuple[str, ...]
    configuration_evidence: Dict[str, Tuple[str, ...]]
    unresolved_vars: Tuple[str, ...]
    representative_chain: Tuple[Dict[str, Any], ...]
    evidence_count: int
    service_count: int
    observation_resources: Tuple[str, ...]
    verdict: str
    confidence: float
    reason: str

    @classmethod
    def from_group(cls, group: Any) -> "GroupedReportFinding":
        return cls(
            title=_human_title(group),
            resource_identity=group.resource_identity,
            resource_protocol=group.resource_protocol,
            resource_type=group.resource_type,
            resolution_status=group.resolution_status,
            identity_strength=group.identity_strength,
            services=tuple(group.services),
            configuration_evidence=dict(group.configuration_evidence),
            unresolved_vars=tuple(group.unresolved_vars),
            representative_chain=tuple(group.representative_chain),
            evidence_count=group.evidence_count,
            service_count=group.service_count,
            observation_resources=tuple(group.observation_resources),
            verdict=group.verdict,
            confidence=float(group.confidence),
            reason=group.reason.strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "resource_identity": self.resource_identity,
            "resource_protocol": self.resource_protocol,
            "resource_type": self.resource_type,
            "resolution_status": self.resolution_status,
            "identity_strength": self.identity_strength,
            "services": list(self.services),
            "configuration_evidence": {k: list(v) for k, v in self.configuration_evidence.items()},
            "unresolved_vars": list(self.unresolved_vars),
            "representative_chain": list(self.representative_chain),
            "evidence_count": self.evidence_count,
            "service_count": self.service_count,
            "observation_resources": list(self.observation_resources),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GroupedReportData:
    """Grouped report — JSON serializable, deterministic."""

    findings: Tuple[GroupedReportFinding, ...]
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
        lines: List[str] = []
        lines.append("# BlindSpot Report")
        lines.append("")
        lines.append(f"Generated: {self.generated_at}")
        lines.append("")
        # Summary — required concepts distinct
        s = self.summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"Services analyzed: {s.get('services_analyzed', s.get('services', 0))}")
        lines.append(f"Shared resource groups: {s.get('resource_groups', 0)}")
        lines.append(f"Meaningful coupling groups: {s.get('meaningful_groups', 0)}")
        lines.append(f"Configuration observations: {s.get('observations', 0)}")
        if s.get('coincidental_groups', 0) or s.get('uncertain_groups', 0):
            lines.append(f"Coincidental groups: {s.get('coincidental_groups', 0)}")
            lines.append(f"Uncertain groups: {s.get('uncertain_groups', 0)}")
        if self.graph_summary:
            gs = self.graph_summary
            lines.append(f"Graph: {gs.get('nodes',0)} nodes ({gs.get('service_nodes',0)} services, {gs.get('resource_nodes',0)} resources), {gs.get('edges',0)} edges")
        lines.append("")

        # Overview plain language when findings exist
        if self.findings:
            meaningful = [f for f in self.findings if f.verdict == "meaningful"]
            if meaningful:
                # Describe first meaningful group generically
                first = meaningful[0]
                proto = first.resource_protocol or "resource"
                svc_count = first.service_count
                lines.append(
                    f"BlindSpot found {len(meaningful)} shared {proto} resource configuration"
                    f"{'s' if len(meaningful)!=1 else ''} used by {svc_count} service{'s' if svc_count!=1 else ''}."
                    " This may create implicit coupling through shared infrastructure or state."
                )
                lines.append("")
                lines.append(
                    "BlindSpot identified shared resource-level configuration. It has not established how the services use the resource at the application level."
                )
                lines.append("")

        if not self.findings:
            lines.append("_No meaningful coupling groups found — all candidates were filtered as generic or judged coincidental/uncertain._")
            return "\n".join(lines)

        # Each finding — conclusion first
        for i, f in enumerate(self.findings, 1):
            lines.append(f"## {i}. {f.title}")
            lines.append("")
            lines.append("Services involved:")
            for svc in sorted(f.services):
                lines.append(f"- {svc}")
            lines.append("")
            # Assessment + confidence
            verdict_label = {"meaningful": "Meaningful implicit coupling", "coincidental": "Coincidental overlap", "uncertain": "Uncertain — insufficient evidence"}.get(f.verdict, f.verdict)
            conf_label = _confidence_label(f.confidence)
            lines.append(f"Assessment: {verdict_label}")
            lines.append(f"Confidence: {conf_label} ({f.confidence:.2f})")
            lines.append("")
            lines.append(f"**Reason:** {f.reason}")
            lines.append("")
            # Why this matters
            lines.append("### Why this matters")
            lines.append("")
            if f.identity_strength == "exact" and f.resolution_status in ("internal", "external_confirmed"):
                lines.append(
                    f"All {f.service_count} services independently configure access to the same {f.resource_protocol or f.resource_type} resource."
                )
                lines.append("This creates potential coupling through shared infrastructure or state. A change, failure, or configuration issue affecting the shared resource may affect multiple services.")
                lines.append("BlindSpot has not established whether the services directly read or write each other's application data.")
            elif f.identity_strength == "config" or f.resolution_status == "partial":
                lines.append(
                    f"All {f.service_count} services share the same {f.resource_protocol or 'resource'} configuration pattern."
                )
                lines.append(
                    "BlindSpot found a shared configuration pattern, but could not fully resolve the final physical resource from the available project configuration. "
                    "The same template suggests potential coupling through shared infrastructure, but physical identity remains partially unresolved."
                )
            else:
                lines.append("Services share configuration that may indicate coupling, but evidence is ambiguous.")
            lines.append("")

            # Configuration evidence grouped by service
            lines.append("### Configuration evidence")
            lines.append("")
            for svc in sorted(f.configuration_evidence.keys()):
                lines.append(f"{svc}")
                for var in sorted(f.configuration_evidence[svc]):
                    lines.append(f"- {var}")
                lines.append("")

            # Resource resolution in human terms
            lines.append("### Resource resolution")
            lines.append("")
            lines.append(f"Type: {f.resource_protocol or f.resource_type}")
            lines.append(f"Resolution: {_human_resolution(f.resolution_status, f.identity_strength)}")
            lines.append(f"Evidence strength: {f.identity_strength} ({'proven same physical' if f.identity_strength=='exact' else 'shared configuration template' if f.identity_strength=='config' else 'insufficient'})")
            lines.append("")

            # Technical details at bottom
            lines.append("### Technical details")
            lines.append("")
            if f.resource_identity:
                lines.append(f"Normalized identity: `{f.resource_identity}`")
                lines.append("")
            if f.unresolved_vars:
                lines.append("Unresolved variables:")
                for uv in sorted(f.unresolved_vars):
                    lines.append(f"- {uv}")
                lines.append("")
            if f.representative_chain:
                lines.append(f"Representative resolution chain ({len(f.representative_chain)} steps):")
                for step in f.representative_chain[:3]:
                    lines.append(f"- {step.get('variable')} via {step.get('source')}: {step.get('from_value')!r} -> {step.get('to_value')!r}")
                if len(f.representative_chain) > 3:
                    lines.append(f"- (+{len(f.representative_chain)-3} more)")
                lines.append("")
            lines.append(f"Observations: {f.evidence_count} configuration observations across {f.service_count} services (variables: {', '.join(sorted(f.observation_resources)) if f.observation_resources else 'none'})")
            lines.append("")

        # Boundary statement once
        lines.append("---")
        lines.append("BlindSpot Tier 1 identifies shared resource-level configuration and potential implicit coupling. It does not claim a specific application-level dependency without source-level evidence.")
        return "\n".join(lines)


def build_grouped_report(
    model: Any,  # CouplingModel
    graph_data: Optional[Dict[str, Any]] = None,
    meaningful_only: bool = True,
) -> GroupedReportData:
    """Build grouped report from CouplingModel.

    Summary distinguishes: services_analyzed, resource_groups, observations, meaningful_groups, etc.
    """
    # For summary, need observations count across all groups (including coincidental)
    all_groups = list(model.groups) if hasattr(model, "groups") else []
    displayed_groups = list(model.meaningful_only().groups) if meaningful_only and hasattr(model, "meaningful_only") else all_groups
    displayed_groups = sorted(displayed_groups, key=lambda g: g.grouping_key)

    findings = tuple(GroupedReportFinding.from_group(g) for g in displayed_groups)

    # Services analyzed: union across all groups
    all_services = set()
    for g in all_groups:
        all_services.update(g.services)

    observations_total = sum(g.evidence_count for g in all_groups)

    summary: Dict[str, Any] = {
        "services_analyzed": len(all_services),
        "services": len(all_services),  # alias for backward compat
        "resource_groups": len(all_groups),
        "observations": observations_total,
        "meaningful_groups": len([g for g in all_groups if g.verdict == "meaningful"]),
        "coincidental_groups": len([g for g in all_groups if g.verdict == "coincidental"]),
        "uncertain_groups": len([g for g in all_groups if g.verdict == "uncertain"]),
        # legacy aliases
        "total": len(all_groups),
        "meaningful": len([g for g in all_groups if g.verdict == "meaningful"]),
        "coincidental": len([g for g in all_groups if g.verdict == "coincidental"]),
        "uncertain": len([g for g in all_groups if g.verdict == "uncertain"]),
        "reported": len(findings),
        "resources": len(all_groups),
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

    return GroupedReportData(findings=findings, summary=summary, graph_summary=graph_summary)
