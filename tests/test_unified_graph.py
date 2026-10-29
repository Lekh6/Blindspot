"""Unified Stage 6/7 graph tests: explicit Compose relationships + hidden coupling."""

import json

from blindspot.aggregation import aggregate_evidence_packages
from blindspot.context_judge import CandidateJudgment
from blindspot.coupling import CouplingModel
from blindspot.decision import build_decision_model
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.graph import build_graph_from_groups
from blindspot.parser import parse_compose_file, parse_compose_string
from blindspot.report import build_grouped_report


def _pipeline():
    project = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    packages = build_evidence_packages(discover_candidates(project), project)
    groups = aggregate_evidence_packages(packages)
    results = []
    for grouped in groups:
        judgments = [
            CandidateJudgment(
                candidate_id=obs.candidate_id,
                verdict="meaningful",
                confidence=0.95,
                reason="resolved shared resource",
                supporting_evidence=(f"candidate:{obs.candidate_id}",),
                missing_information=(),
                model="test-provider-model",
            )
            for obs in grouped.observations
        ]
        results.append((grouped, judgments, []))
    model = CouplingModel.from_contextual_judgments(results)
    decisions = build_decision_model(results)
    return project, model, decisions


def test_explicit_compose_syntax_variations():
    yaml = """
services:
  api:
    image: app
    depends_on:
      db:
        condition: service_healthy
  worker:
    image: app
    depends_on: db
  db:
    image: postgres:16
"""
    project = parse_compose_string(yaml)
    assert project.services["api"].depends_on == ("db",)
    assert project.services["worker"].depends_on == ("db",)


def test_explicit_and_hidden_edges_are_distinct():
    _, model, decisions = _pipeline()
    graph = build_graph_from_groups(model, decisions=decisions)

    explicit = [e for e in graph["edges"] if e["data"]["classification"] == "explicit"]
    hidden = [e for e in graph["edges"] if e["data"]["classification"] != "explicit"]
    assert explicit and hidden

    for edge in explicit:
        assert edge["source"].startswith("service:")
        assert edge["target"].startswith("service:")
        assert edge["data"]["semantics"] == "startup_dependency"
        assert "confidence" not in edge["data"]
        assert "decision" not in edge["data"]

    for edge in hidden:
        assert edge["source"].startswith("service:")
        assert edge["target"].startswith("resource:")
        assert edge["data"]["semantics"] == "resource_mediated"
        assert edge["data"]["classification"] in ("potential_hidden", "uncertain")

    endpoint = [e for e in hidden if "shared_endpoint" in e["target"]]
    assert endpoint and endpoint[0]["data"]["classification"] == "potential_hidden"
    assert endpoint[0]["data"]["decision"] == "potential_dependency"

    unresolved = [e for e in hidden if "MYSTERY_REF" in e["target"]]
    assert unresolved and unresolved[0]["data"]["classification"] == "uncertain"


def test_explicit_relationships_always_included_and_decision_free():
    _, model, decisions = _pipeline()
    graph = build_graph_from_groups(model, meaningful_only=True, decisions=decisions)
    explicit = [e for e in graph["edges"] if e["data"]["classification"] == "explicit"]
    assert explicit

    # Make an explicit group look non-meaningful; it must still appear.
    for group in model.groups:
        if group.resource_type == "service_dependency":
            object.__setattr__(group, "verdict", "coincidental")
    graph2 = build_graph_from_groups(model, meaningful_only=True, decisions=decisions)
    explicit2 = [e for e in graph2["edges"] if e["data"]["classification"] == "explicit"]
    assert {e["id"] for e in explicit2} == {e["id"] for e in explicit}


def test_graph_decision_metadata_preserved_and_model_hidden():
    _, model, decisions = _pipeline()
    graph = build_graph_from_groups(model, decisions=decisions)
    resource_nodes = [n for n in graph["nodes"] if n["type"] == "resource"]
    assert any(n["data"].get("decisions") for n in resource_nodes)
    blob = json.dumps(graph)
    assert "test-provider-model" not in blob
    assert "stage4_model" not in blob


def test_report_separates_explicit_from_hidden():
    project, model, decisions = _pipeline()
    graph = build_graph_from_groups(model, decisions=decisions)
    report = build_grouped_report(
        model,
        graph_data=graph,
        total_services=len(project.services),
        decisions=decisions,
    )
    data = report.to_dict()
    assert data["explicit_relationships"]
    assert all(f["resource_type"] != "service_dependency" for f in data["findings"])
    assert any(f["classification"] == "potential_hidden" for f in data["findings"])
    assert any(f["decisions"] for f in data["findings"])
    assert "test-provider-model" not in json.dumps(data)
    assert "stage4_model" not in json.dumps(data)

    markdown = report.to_markdown()
    assert "Explicitly configured relationships" in markdown
    assert "startup ordering" in markdown
    assert "Stage 5 decision" in markdown


def test_empty_graph_and_report():
    model = CouplingModel([])
    graph = build_graph_from_groups(model)
    assert graph == {"nodes": [], "edges": []}
    report = build_grouped_report(model)
    assert report.findings == ()
    assert report.explicit_relationships == ()


def test_graph_deterministic_with_unified_edges():
    _, model, decisions = _pipeline()
    first = build_graph_from_groups(model, decisions=decisions)
    second = build_graph_from_groups(model, decisions=decisions)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
