"""
BlindSpot Stage 6: Resource Graph — React Flow DATA Contract (not PNG)

Pipeline position: Stage 5 DependencyModel → **Stage 6 Graph** → Stage 7 Report

Stage 6 does NOT discover, filter, judge, call LLM, modify verdict/confidence,
write cache, or expose model/provider. It only transforms DependencyModel into
deterministic, JSON-serializable, provider-agnostic bipartite graph data for React Flow.

Graph is Service ↔ Resource: orders → DB_HOST=postgres ← reports, never orders—reports.
NetworkX may be used internally only if useful — not the contract. No graph.png primary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Tuple

from .model import Dependency, DependencyModel

# Grouped model (Prompt 2) — lazy to avoid circular
try:
    from .coupling import CouplingGroup, CouplingModel  # type: ignore
except Exception:  # pragma: no cover
    CouplingGroup = Any  # type: ignore
    CouplingModel = Any  # type: ignore

# ---------------------------------------------------------------------------
# Node / Edge dataclasses — React Flow concept, JSON serializable
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphNode:
    """React Flow node. `data` is extensible for future source_locations/directory."""

    id: str  # e.g. service:orders, resource:env_var:DB_HOST=postgres
    type: str  # service | resource
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type, "data": dict(self.data)}


@dataclass(frozen=True)
class GraphEdge:
    """React Flow edge — always Service → Resource (bipartite)."""

    id: str  # e.g. service:orders->resource:env_var:DB_HOST=postgres
    source: str
    target: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "source": self.source, "target": self.target, "data": dict(self.data)}


@dataclass(frozen=True)
class GraphData:
    """Full graph — deterministically sorted, JSON serializable."""

    nodes: Tuple[GraphNode, ...]
    edges: Tuple[GraphEdge, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Helpers — deterministic resource identity
# ---------------------------------------------------------------------------

def _service_id(name: str) -> str:
    return f"service:{name}"


def _resource_key(resource: str, resource_type: str, value: Any, normalized_identity: Any = None) -> str:
    """Deterministic resource identity — prefers normalized_identity when available.

    - If normalized_identity present (exact external/internal), dedup by that (so
      postgresql://user1@db:5432/calcom and postgresql://user2@db:5432/calcom share node)
    - Else includes type so env_var:REDIS ≠ named_volume:REDIS.
    Matches spec: resource:env_var:DB_HOST=postgres, resource:named_volume:shared-data
    For env_var with value, suffix =value; for named_volume/shared-data value may be None.
    """
    if normalized_identity:
        # Normalize identity already includes scheme/host/port/db and is deterministic
        # Prefix with resource_type to keep type distinction but share across variable names
        return f"resource:{resource_type}:{normalized_identity}"
    base = f"resource:{resource_type}:{resource}"
    if value is not None and resource_type == "env_var":
        # Keep =value for display and dedup — same resource+value is same node
        base = f"{base}={value}"
    return base


def _resource_display_name(resource: str, value: Any, normalized_identity: Any = None) -> str:
    if normalized_identity:
        # Show normalized form for external confirmed / internal resources
        return normalized_identity
    if value is not None:
        return f"{resource}={value}"
    return resource


def _edge_id(source: str, target: str) -> str:
    return f"{source}->{target}"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_graph(
    model: DependencyModel,
    meaningful_only: bool = True,
) -> Dict[str, Any]:
    """Build React Flow graph data from DependencyModel.

    What enters Stage 6: DependencyModel from Stage 5 (service-to-resource, confidence, evidence, _model hidden).
    What leaves Stage 6: JSON-serializable dict {"nodes": [...], "edges": [...]} bipartite Service↔Resource.

    - meaningful_only=True (default) uses model.meaningful_only() — primary graph shows confirmed couplings.
    - meaningful_only=False includes all verdicts (coincidental/uncertain) for debugging.
    - Resource deduplication by deterministic resource_key (includes resource_type).
    - Multiple resources between same services kept as separate resource nodes.
    - Confidence preserved in edge data, model never exposed.
    - Deterministic: sorted nodes/edges, same DependencyModel → same graph.
    """
    # Stage 5 input selection
    deps: List[Dependency]
    if meaningful_only:
        deps = list(model.meaningful_only().dependencies)
    else:
        deps = list(model.dependencies)
    # Already sorted in DependencyModel, but re-sort for determinism if caller passed unsorted
    deps.sort(key=lambda d: (d.service_a, d.service_b, d.resource_type, d.resource, str(d.value or "")))

    # Handle empty model — return empty graph without crashing
    if not deps:
        return {"nodes": [], "edges": []}

    # Collect service names and resource identities deterministically
    service_ids: Dict[str, GraphNode] = {}
    resource_nodes: Dict[str, GraphNode] = {}
    edges_by_id: Dict[str, GraphEdge] = {}

    for dep in deps:
        # Service nodes — bipartite type service
        for svc in (dep.service_a, dep.service_b):
            sid = _service_id(svc)
            if sid not in service_ids:
                service_ids[sid] = GraphNode(
                    id=sid,
                    type="service",
                    data={"name": svc},
                    # Future extensibility: directory, source_locations can be added to data without changing contract
                )
        # Resource node — deduped by normalized_identity when available else resource+value
        norm_id = None
        # Evidence stores normalized_identity in dep.evidence.to_dict() and directly dep.evidence.normalized_identity
        try:
            norm_id = dep.evidence.normalized_identity if hasattr(dep.evidence, "normalized_identity") else None
        except Exception:
            norm_id = None
        rid = _resource_key(dep.resource, dep.resource_type, dep.value, normalized_identity=norm_id)
        if rid not in resource_nodes:
            # Include normalized identity + protocol in node data for future frontend evidence panel
            data: Dict[str, Any] = {
                "name": _resource_display_name(dep.resource, dep.value, normalized_identity=norm_id),
                "resource_type": dep.resource_type,
                "value": dep.value,
            }
            if norm_id:
                data["normalized_identity"] = norm_id
                # Also expose protocol / status for evidence panel without breaking contract
                if hasattr(dep.evidence, "resource_protocol") and dep.evidence.resource_protocol:
                    data["resource_protocol"] = dep.evidence.resource_protocol
                if hasattr(dep.evidence, "resolution_status"):
                    data["resolution_status"] = dep.evidence.resolution_status
            resource_nodes[rid] = GraphNode(
                id=rid,
                type="resource",
                data=data,
                # Extensible: later add evidence["source_locations"] etc. here without changing graph architecture
            )
        # Edges — two per dependency, Service → Resource (bipartite, never Service→Service)
        for svc in (dep.service_a, dep.service_b):
            sid = _service_id(svc)
            eid = _edge_id(sid, rid)
            if eid not in edges_by_id:
                # Preserve confidence from Stage 4/5, do not modify; model never exposed
                edges_by_id[eid] = GraphEdge(
                    id=eid,
                    source=sid,
                    target=rid,
                    data={"confidence": float(dep.confidence)},
                )
            else:
                # If same service→resource already exists via another dependency (same resource dedup),
                # keep highest confidence deterministically (max) — do not duplicate edge
                existing = edges_by_id[eid]
                if float(dep.confidence) > float(existing.data.get("confidence", 0)):
                    edges_by_id[eid] = GraphEdge(
                        id=eid,
                        source=sid,
                        target=rid,
                        data={"confidence": float(dep.confidence)},
                    )

    # Deterministic output — sorted by id
    nodes = sorted(list(service_ids.values()) + list(resource_nodes.values()), key=lambda n: n.id)
    edges = sorted(edges_by_id.values(), key=lambda e: e.id)

    # Optional internal validation with networkx (not the contract) — only if installed
    try:
        import networkx as nx  # type: ignore[import-untyped]

        G = nx.Graph()
        for n in nodes:
            G.add_node(n.id)
        for e in edges:
            G.add_edge(e.source, e.target)
        # Quick check: no service-service edge
        for e in edges:
            if e.source.startswith("service:") and e.target.startswith("service:"):
                raise ValueError(f"Graph must not have service→service edge: {e.id}")
    except ImportError:
        pass

    return {"nodes": [n.to_dict() for n in nodes], "edges": [e.to_dict() for e in edges]}


def build_graph_data(
    model: DependencyModel,
    meaningful_only: bool = True,
) -> GraphData:
    """Typed wrapper returning GraphData dataclass (JSON via to_dict()/to_json())."""
    raw = build_graph(model, meaningful_only=meaningful_only)
    nodes = tuple(GraphNode(id=n["id"], type=n["type"], data=n["data"]) for n in raw["nodes"])
    edges = tuple(GraphEdge(id=e["id"], source=e["source"], target=e["target"], data=e["data"]) for e in raw["edges"])
    return GraphData(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Grouped graph (Prompt 2 — resource-centric)
# ---------------------------------------------------------------------------

def _grouped_resource_key(group: Any) -> str:
    """Grouping key already includes normalized dedup; use resource_type + identity."""
    ident = group.resource_identity or f"{group.resource_type}:{group.grouping_key}"
    return f"resource:{group.resource_type}:{ident}"


def _grouped_display_name(group: Any) -> str:
    if group.resource_identity:
        return group.resource_identity
    # Fallback for unknown
    if group.observation_resources:
        return f"{group.resource_type}:{','.join(sorted(group.observation_resources))}"
    return group.grouping_key


# ---------------------------------------------------------------------------
# Classification helpers — semantic fields for the frontend
# ---------------------------------------------------------------------------

RELATIONSHIP_TYPES = {
    "env_var": "shared_env",
    "named_volume": "shared_volume",
    "shared_endpoint": "shared_endpoint",
    "service_dependency": "explicit_dependency",
}

RELATIONSHIP_ORIGINS = {
    "env_var": "compose:environment",
    "named_volume": "compose:volumes",
    "shared_endpoint": "derived:endpoint-identity",
    "service_dependency": "compose:depends_on",
}

DECISION_CLASSIFICATIONS = {
    "potential_dependency": "potential_hidden",
    "review": "uncertain",
    "insufficient_evidence": "rejected",
}

VERDICT_CLASSIFICATIONS = {
    "meaningful": "potential_hidden",
    "uncertain": "uncertain",
    "coincidental": "rejected",
}

_PUBLIC_DECISION_FIELDS = (
    "candidate_id",
    "service_a",
    "service_b",
    "resource",
    "resource_type",
    "resource_identity",
    "resolution_status",
    "identity_strength",
    "stage4_verdict",
    "stage4_confidence",
    "decision",
    "processing_status",
    "score",
    "evidence_references",
    "counter_evidence_references",
    "missing_information",
    "policy_rules_applied",
    "rationale",
    "decision_schema_version",
    "policy_version",
)


def decision_public_view(record: Any) -> Dict[str, Any]:
    """Project a DecisionRecord into graph/report-safe data (never exposes model)."""
    view: Dict[str, Any] = {}
    for name in _PUBLIC_DECISION_FIELDS:
        value = getattr(record, name)
        if isinstance(value, tuple):
            value = list(value)
        elif isinstance(value, Enum):
            value = value.value
        view[name] = value
    return view


def summarize_decision_views(views: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic decision counts + overall outcome for a resource or service."""
    decisions = sorted(str(v.get("decision", "")) for v in views)
    statuses = sorted(str(v.get("processing_status", "")) for v in views)
    counts = {
        "potential_dependency": decisions.count("potential_dependency"),
        "review": decisions.count("review"),
        "insufficient_evidence": decisions.count("insufficient_evidence"),
    }
    status_counts = {
        "ok": statuses.count("ok"),
        "missing_judgment": statuses.count("missing_judgment"),
        "invalid_judgment": statuses.count("invalid_judgment"),
        "operational_failure": statuses.count("operational_failure"),
        "conflicting_evidence": statuses.count("conflicting_evidence"),
    }
    if counts["potential_dependency"]:
        overall: Any = "potential_dependency"
    elif counts["review"]:
        overall = "review"
    elif counts["insufficient_evidence"]:
        overall = "insufficient_evidence"
    else:
        overall = None
    return {
        "overall": overall,
        "total_candidates": len(views),
        "counts": counts,
        "processing_status_counts": status_counts,
        "candidate_ids": sorted(str(v.get("candidate_id", "")) for v in views),
    }


def _decision_index(decisions: Any) -> Dict[str, Any]:
    if decisions is None:
        return {}
    records = getattr(decisions, "decisions", decisions)
    index: Dict[str, Any] = {}
    for record in records or ():
        cid = getattr(record, "candidate_id", None)
        if cid:
            index[str(cid)] = record
    return index


def _group_observations(group: Any) -> Tuple[Any, ...]:
    grouped_package = getattr(group, "grouped_package", None)
    observations = getattr(grouped_package, "observations", ()) if grouped_package else ()
    return tuple(observations or ())


def _group_decision_views(group: Any, index: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map Stage 5 decisions to a hidden group through its observation candidate IDs."""
    views: List[Dict[str, Any]] = []
    for observation in _group_observations(group):
        cid = getattr(observation, "candidate_id", None)
        if cid and str(cid) in index:
            views.append(decision_public_view(index[str(cid)]))
    views.sort(key=lambda v: (v["service_a"], v["service_b"], v["candidate_id"]))
    return views


def _service_decision_views(views: List[Dict[str, Any]], service: str) -> List[Dict[str, Any]]:
    return [
        v for v in views
        if v["service_a"] == service or v["service_b"] == service
    ]


def _classification_for(group: Any, decision_summary: Any) -> str:
    if decision_summary and decision_summary.get("overall"):
        return DECISION_CLASSIFICATIONS.get(decision_summary["overall"], "uncertain")
    return VERDICT_CLASSIFICATIONS.get(group.verdict, "uncertain")


def _is_explicit_group(group: Any) -> bool:
    return getattr(group, "resource_type", "") == "service_dependency"


def _explicit_relationship_rows(group: Any) -> List[Dict[str, Any]]:
    """Extract directional explicit relationships from L0 observations."""
    rows: List[Dict[str, Any]] = []
    for observation in _group_observations(group):
        source = str(observation.service_a)
        target = str(observation.service_b)
        identity = getattr(observation, "normalized_identity", None)
        rows.append({
            "source": source,
            "target": target,
            "candidate_id": getattr(observation, "candidate_id", ""),
            "target_resolved": bool(identity and str(identity).startswith("service|")),
            "evidence": getattr(observation, "evidence", ""),
            "provenance": getattr(observation, "provenance", None),
            "relationship_type": "explicit_dependency",
            "semantics": "startup_dependency",
            "origin": "compose:depends_on",
            "classification": "explicit",
        })
    rows.sort(key=lambda r: (r["source"], r["target"]))
    return rows


def explicit_relationships_from_groups(groups: List[Any]) -> List[Dict[str, Any]]:
    """Deterministic explicit relationship rows from L0 groups (public, reusable by report)."""
    rows: List[Dict[str, Any]] = []
    for group in sorted(groups, key=lambda g: g.grouping_key):
        if _is_explicit_group(group):
            rows.extend(_explicit_relationship_rows(group))
    # Deduplicate identical declared edges while preserving candidate IDs.
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        key = (row["source"], row["target"])
        if key not in merged:
            entry = dict(row)
            entry["candidate_ids"] = [row["candidate_id"]] if row["candidate_id"] else []
            merged[key] = entry
        else:
            entry = merged[key]
            if row["candidate_id"] and row["candidate_id"] not in entry["candidate_ids"]:
                entry["candidate_ids"].append(row["candidate_id"])
            entry["target_resolved"] = entry["target_resolved"] or row["target_resolved"]
    result: List[Dict[str, Any]] = []
    for (source, target), entry in sorted(merged.items()):
        entry["candidate_ids"] = sorted(entry["candidate_ids"])
        entry["relationship_id"] = f"explicit:service:{source}->service:{target}"
        entry["source_id"] = f"service:{source}"
        entry["target_id"] = f"service:{target}"
        result.append(entry)
    return result


def build_graph_from_groups(
    model: Any,  # CouplingModel
    meaningful_only: bool = True,
    decisions: Any = None,  # DecisionModel or iterable[DecisionRecord]
) -> Dict[str, Any]:
    """Build React Flow graph from grouped CouplingModel.

    Explicit L0 relationships become service → service edges with
    classification="explicit" and startup-dependency semantics. Hidden
    shared-resource relationships stay service → resource. Hidden edges carry
    semantic classification plus Stage 5 decision metadata when supplied.

    - Explicit relationships are always included, regardless of meaningful_only.
    - Hidden groups are filtered by meaningful_only as before.
    - Deterministic, provider hidden, confidence preserved only where it exists.
    """
    all_groups = list(getattr(model, "groups", model) or ())  # type: ignore[arg-type]
    all_groups.sort(key=lambda g: g.grouping_key)

    explicit_groups = [g for g in all_groups if _is_explicit_group(g)]
    hidden_all = [g for g in all_groups if not _is_explicit_group(g)]
    if meaningful_only:
        hidden_groups = [g for g in hidden_all if g.verdict == "meaningful"]
    else:
        hidden_groups = hidden_all

    groups = explicit_groups + hidden_groups
    groups.sort(key=lambda g: g.grouping_key)

    if not groups:
        return {"nodes": [], "edges": []}

    decision_index = _decision_index(decisions)

    service_ids: Dict[str, GraphNode] = {}
    resource_nodes: Dict[str, GraphNode] = {}
    edges_by_id: Dict[str, GraphEdge] = {}

    def ensure_service(name: str, resolved: bool = True) -> str:
        sid = _service_id(name)
        existing = service_ids.get(sid)
        if existing is None:
            data: Dict[str, Any] = {"name": name}
            if not resolved:
                data["resolved"] = False
            service_ids[sid] = GraphNode(id=sid, type="service", data=data)
        elif not resolved and existing.data.get("resolved") is not False:
            service_ids[sid] = GraphNode(
                id=sid, type="service", data={**existing.data, "resolved": False}
            )
        return sid

    # Explicit relationships: always service → service, never resource-mediated.
    for row in explicit_relationships_from_groups(explicit_groups):
        source_id = ensure_service(row["source"])
        target_id = ensure_service(row["target"], resolved=bool(row["target_resolved"]))
        edge_data: Dict[str, Any] = {
            "relationship_type": row["relationship_type"],
            "classification": row["classification"],
            "semantics": row["semantics"],
            "origin": row["origin"],
            "target_resolved": bool(row["target_resolved"]),
            "candidate_ids": list(row["candidate_ids"]),
            "evidence": row["evidence"],
        }
        if row.get("provenance"):
            edge_data["provenance"] = row["provenance"]
        eid = row["relationship_id"]
        edges_by_id[eid] = GraphEdge(id=eid, source=source_id, target=target_id, data=edge_data)

    # Hidden relationships: service → resource, one resource node per group.
    for group in hidden_groups:
        group_views = _group_decision_views(group, decision_index)
        decision_summary = summarize_decision_views(group_views) if group_views else None
        classification = _classification_for(group, decision_summary)
        relationship_type = RELATIONSHIP_TYPES.get(group.resource_type, group.resource_type)
        origin = RELATIONSHIP_ORIGINS.get(group.resource_type, "unknown")

        for svc in sorted(group.services):
            ensure_service(svc)

        rid = _grouped_resource_key(group)
        if rid not in resource_nodes:
            data: Dict[str, Any] = {
                "name": _grouped_display_name(group),
                "resource_type": group.resource_type,
                "resource_protocol": group.resource_protocol,
                "resolution_status": group.resolution_status,
                "identity_strength": group.identity_strength,
                "grouping_key": group.grouping_key,
                "resource_identity": group.resource_identity,
                "relationship_type": relationship_type,
                "semantics": "resource_mediated",
                "origin": origin,
                "evidence_count": group.evidence_count,
                "service_count": group.service_count,
                "configuration_evidence": {
                    svc: list(vars_sorted)
                    for svc, vars_sorted in sorted(group.configuration_evidence.items())
                },
                "unresolved_vars": list(group.unresolved_vars),
                "observation_resources": list(group.observation_resources),
                "representative_chain": list(group.representative_chain),
            }
            if decision_summary:
                data["decision_summary"] = decision_summary
                data["candidate_ids"] = decision_summary["candidate_ids"]
                data["decisions"] = group_views
            data = {k: v for k, v in data.items() if v is not None}
            resource_nodes[rid] = GraphNode(id=rid, type="resource", data=data)

        for svc in sorted(group.services):
            sid = _service_id(svc)
            eid = _edge_id(sid, rid)
            edge_data = {
                "confidence": float(group.confidence),
                "relationship_type": relationship_type,
                "classification": classification,
                "semantics": "resource_mediated",
                "origin": origin,
            }
            service_views = _service_decision_views(group_views, svc)
            if service_views:
                service_decision = summarize_decision_views(service_views)
                edge_data["decision"] = service_decision["overall"]
                edge_data["decision_counts"] = service_decision["counts"]
                edge_data["processing_status_counts"] = service_decision["processing_status_counts"]
                edge_data["candidate_ids"] = service_decision["candidate_ids"]
            if eid not in edges_by_id:
                edges_by_id[eid] = GraphEdge(id=eid, source=sid, target=rid, data=edge_data)
            else:
                existing = edges_by_id[eid]
                if float(group.confidence) > float(existing.data.get("confidence", 0)):
                    edges_by_id[eid] = GraphEdge(id=eid, source=sid, target=rid, data=edge_data)

    nodes = sorted(list(service_ids.values()) + list(resource_nodes.values()), key=lambda n: n.id)
    edges = sorted(edges_by_id.values(), key=lambda e: e.id)

    try:
        import networkx as nx  # type: ignore

        G = nx.Graph()
        for n in nodes:
            G.add_node(n.id)
        for e in edges:
            G.add_edge(e.source, e.target)
        for e in edges:
            if e.source.startswith("service:") and e.target.startswith("service:"):
                if e.data.get("classification") != "explicit":
                    raise ValueError(
                        f"Only explicit relationships may be service→service: {e.id}"
                    )
    except ImportError:
        pass

    return {"nodes": [n.to_dict() for n in nodes], "edges": [e.to_dict() for e in edges]}


def build_graph_data_from_groups(
    model: Any,
    meaningful_only: bool = True,
    decisions: Any = None,
) -> GraphData:
    raw = build_graph_from_groups(
        model, meaningful_only=meaningful_only, decisions=decisions
    )
    nodes = tuple(GraphNode(id=n["id"], type=n["type"], data=n["data"]) for n in raw["nodes"])
    edges = tuple(GraphEdge(id=e["id"], source=e["source"], target=e["target"], data=e["data"]) for e in raw["edges"])
    return GraphData(nodes=nodes, edges=edges)
