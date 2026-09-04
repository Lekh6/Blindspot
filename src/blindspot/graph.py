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
from typing import Any, Dict, List, Tuple

from .model import Dependency, DependencyModel

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


def _resource_key(resource: str, resource_type: str, value: Any) -> str:
    """Deterministic resource identity — includes type so env_var:REDIS ≠ named_volume:REDIS.

    Matches spec: resource:env_var:DB_HOST=postgres, resource:named_volume:shared-data
    For env_var with value, suffix =value; for named_volume/shared-data value may be None.
    """
    base = f"resource:{resource_type}:{resource}"
    if value is not None and resource_type == "env_var":
        # Keep =value for display and dedup — same resource+value is same node
        base = f"{base}={value}"
    return base


def _resource_display_name(resource: str, value: Any) -> str:
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
        # Resource node — deduped by resource_key (type + resource + value)
        rid = _resource_key(dep.resource, dep.resource_type, dep.value)
        if rid not in resource_nodes:
            resource_nodes[rid] = GraphNode(
                id=rid,
                type="resource",
                data={
                    "name": _resource_display_name(dep.resource, dep.value),
                    "resource_type": dep.resource_type,
                    "value": dep.value,
                },
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
