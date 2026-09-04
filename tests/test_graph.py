"""Stage 6 — Resource Graph (React Flow DATA contract) tests.

Per modified AGENTS.md §6:
- bipartite Service ↔ Resource, no service-service edges
- dedup by resource_type, keep multiple resources between same services
- confidence preserved, model hidden, deterministic, JSON serializable, empty handled
"""

import json

from blindspot.filtering import EvidencePackage
from blindspot.judge import JudgeResult
from blindspot.model import Dependency, DependencyModel
from blindspot.graph import build_graph, build_graph_data


def _pkg(sa, sb, resource, rtype, value, ref="external"):
    return EvidencePackage(
        service_a=sa, service_b=sb, resource=resource, resource_type=rtype,
        value=value, evidence="x", reference_type=ref,
    )


def _dep(sa, sb, resource, rtype, value, verdict="meaningful", conf=0.93, model="test-model", ref="external"):  # type: ignore[assignment]
    pkg = _pkg(sa, sb, resource, rtype, value, ref)
    res = JudgeResult(verdict=verdict, confidence=conf, reason="ok", model=model)  # type: ignore[arg-type]
    return Dependency.from_evidence_judgment(pkg, res)


def test_meaningful_produces_service_and_resource_nodes():
    dep = _dep("orders", "reports", "DB_HOST", "env_var", "postgres", ref="compose_service")
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    ids = {n["id"] for n in g["nodes"]}
    assert "service:orders" in ids
    assert "service:reports" in ids
    assert "resource:env_var:DB_HOST=postgres" in ids
    types = {n["type"] for n in g["nodes"]}
    assert "service" in types and "resource" in types


def test_no_direct_service_service_edges():
    deps = [
        _dep("orders", "reports", "DB_HOST", "env_var", "postgres"),
        _dep("api", "worker", "shared-data", "named_volume", None, ref="named_volume"),
    ]
    g = build_graph(DependencyModel(deps), meaningful_only=True)
    for e in g["edges"]:
        # bipartite only — neither endpoint is service-service
        assert not (e["source"].startswith("service:") and e["target"].startswith("service:"))
        assert e["source"].startswith("service:") and e["target"].startswith("resource:")


def test_each_dependency_creates_two_edges():
    dep = _dep("orders", "reports", "DB_HOST", "env_var", "postgres")
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    # 1 dep → 2 edges (a→resource, b→resource)
    assert len(g["edges"]) == 2
    sources = {e["source"] for e in g["edges"]}
    assert sources == {"service:orders", "service:reports"}
    targets = {e["target"] for e in g["edges"]}
    assert targets == {"resource:env_var:DB_HOST=postgres"}


def test_identical_resources_deduplicated():
    dep1 = _dep("orders", "reports", "DB_HOST", "env_var", "postgres")
    dep2 = _dep("orders", "analytics", "DB_HOST", "env_var", "postgres")
    dep3 = _dep("reports", "analytics", "DB_HOST", "env_var", "postgres")
    g = build_graph(DependencyModel([dep1, dep2, dep3]), meaningful_only=True)
    r_nodes = [n for n in g["nodes"] if n["type"] == "resource"]
    assert len(r_nodes) == 1
    assert r_nodes[0]["id"] == "resource:env_var:DB_HOST=postgres"
    # 3 services × 1 resource = 3 distinct service→resource edges? Actually 6 edges but dedup per pair per service
    # services orders, reports, analytics each connect once → 3 edges
    assert len(g["edges"]) == 3


def test_different_resource_types_same_name_distinct():
    dep_env = _dep("a", "b", "REDIS", "env_var", "redis://x")
    dep_vol = _dep("a", "b", "REDIS", "named_volume", None, ref="named_volume")
    g = build_graph(DependencyModel([dep_env, dep_vol]), meaningful_only=True)
    r_ids = {n["id"] for n in g["nodes"] if n["type"] == "resource"}
    assert "resource:env_var:REDIS=redis://x" in r_ids
    assert "resource:named_volume:REDIS" in r_ids
    assert len(r_ids) == 2


def test_multiple_resources_between_same_services_separate():
    dep1 = _dep("orders", "reports", "DB_HOST", "env_var", "postgres")
    dep2 = _dep("orders", "reports", "DB_NAME", "env_var", "orders")
    dep3 = _dep("orders", "reports", "shared-data", "named_volume", None, ref="named_volume")
    g = build_graph(DependencyModel([dep1, dep2, dep3]), meaningful_only=True)
    r_ids = {n["id"] for n in g["nodes"] if n["type"] == "resource"}
    assert len(r_ids) == 3
    assert "resource:env_var:DB_HOST=postgres" in r_ids
    assert "resource:env_var:DB_NAME=orders" in r_ids
    assert "resource:named_volume:shared-data" in r_ids
    assert len(g["edges"]) == 6  # 3 resources × 2 services


def test_confidence_preserved():
    dep = _dep("a", "b", "X", "env_var", "v", conf=0.77)
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    for e in g["edges"]:
        assert e["data"]["confidence"] == 0.77


def test_model_not_exposed():
    dep = _dep("a", "b", "X", "env_var", "v", model="gemini-3.7-flash")
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    blob = json.dumps(g)
    assert "gemini" not in blob
    assert "nemotron" not in blob
    assert "test-model" not in blob
    for n in g["nodes"]:
        assert "model" not in n["data"]
        assert "model" not in n["id"]
    for e in g["edges"]:
        assert "model" not in e["data"]


def test_empty_model():
    g = build_graph(DependencyModel([]), meaningful_only=True)
    assert g["nodes"] == []
    assert g["edges"] == []


def test_no_meaningful_returns_empty_when_all_coincidental():
    deps = [
        _dep("a", "b", "PORT", "env_var", "8000", verdict="coincidental", conf=0.9),
        _dep("a", "b", "Y", "env_var", "v", verdict="uncertain", conf=0.5),
    ]
    g = build_graph(DependencyModel(deps), meaningful_only=True)
    assert g["nodes"] == [] and g["edges"] == []
    g2 = build_graph(DependencyModel(deps), meaningful_only=False)
    assert len(g2["nodes"]) > 0


def test_deterministic():
    deps = [_dep("b", "a", "X", "env_var", "v"), _dep("a", "c", "Y", "env_var", "w")]
    m = DependencyModel(deps)
    g1 = build_graph(m, meaningful_only=True)
    g2 = build_graph(m, meaningful_only=True)
    assert g1 == g2
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


def test_json_serializable_and_typed_wrapper():
    dep = _dep("orders", "reports", "DB_HOST", "env_var", "postgres")
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    s = json.dumps(g)
    assert json.loads(s) == g
    # typed wrapper
    gd = build_graph_data(DependencyModel([dep]), meaningful_only=True)
    assert gd.to_dict() == g
    assert json.loads(gd.to_json()) == g


def test_future_extensibility_data_can_carry_source_locations():
    """data is extensible — adding directory/source_locations does not break contract."""
    dep = _dep("orders", "reports", "DB_HOST", "env_var", "postgres")
    g = build_graph(DependencyModel([dep]), meaningful_only=True)
    # Simulate future frontend adding source_locations to node data
    for n in g["nodes"]:
        n["data"]["directory"] = f"services/{n['data']['name']}" if n["type"] == "service" else f"config/{n['data']['name']}"
        n["data"]["source_locations"] = [{"file": "docker-compose.yml", "line": 14}]
    # Must remain JSON serializable and still have required fields
    s = json.dumps(g)
    assert "source_locations" in s and "directory" in s
