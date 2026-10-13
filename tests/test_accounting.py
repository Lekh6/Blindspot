"""Tests for Prompt: Input Transparency and Analysis Accounting (Cases A-F)."""

import json
import tempfile
from pathlib import Path

from blindspot.parser import parse_compose_string, parse_compose_file
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.aggregation import aggregate_evidence_packages
from blindspot.coupling import CouplingModel
from blindspot.graph import build_graph_from_groups
from blindspot.report import build_grouped_report
from blindspot.judge import JudgeResult
from blindspot.cli import run_one_repo


# Case A — Services parsed, zero candidates (celery-docker-example)
def test_case_a_services_zero_candidates():
    yaml = """
services:
  db:
    image: postgres:9.6.5
    volumes:
      - postgres_data:/var/lib/postgresql/data/
  redis:
    image: "redis:alpine"
  web:
    build: .
    volumes:
      - .:/code
  celery:
    build: .
    volumes:
      - .:/code
  celery-beat:
    build: .
    volumes:
      - .:/code
volumes:
  postgres_data:
"""
    proj = parse_compose_string(yaml)
    assert len(proj.services) == 5
    # Named volumes: only postgres_data is named, but only one service uses it -> not shared
    assert proj.count_named_volumes() == 1
    candidates = discover_candidates(proj)
    # No shared env, no shared named volume -> 0 candidates
    assert len(candidates) == 0
    pkgs = build_evidence_packages(candidates, proj)
    assert len(pkgs) == 0
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 0
    model = CouplingModel.from_grouped_judgments([])
    graph = build_graph_from_groups(model)
    # Pass total_services explicitly as CLI does
    report = build_grouped_report(model, graph_data=graph, total_services=len(proj.services), accounting={
        "application_root": "C:\\\\test",
        "sources": {"discovered": ["docker-compose.yml"], "discovered_count": 1, "successfully_parsed": ["docker-compose.yml"], "successfully_parsed_count": 1, "used": ["docker-compose.yml"], "used_count": 1},
        "parsed": {"services": len(proj.services), "named_volumes": proj.count_named_volumes()},
        "discovery": {"raw_candidates": len(candidates), "observations": len(pkgs), "filtered_out": 0},
        "aggregation": {"resource_groups": len(groups), "observations": len(pkgs)},
        "judgment": {"groups_judged": 0, "meaningful": 0, "coincidental": 0, "uncertain": 0, "llm_calls": 0, "cache_hits": 0},
        "graph": {"nodes": 0, "edges": 0, "service_nodes": 0, "resource_nodes": 0},
    })
    # Must distinguish from parsing failure
    assert report.summary["services_analyzed"] == 5
    assert report.summary["observations"] == 0
    assert report.summary["resource_groups"] == 0
    # JSON must contain new accounting
    j = json.loads(report.to_json())
    assert j["application"]["root"] == "C:\\\\test"
    assert j["inputs"]["sources_used"] == ["docker-compose.yml"]
    assert j["analysis"]["parsed"]["services"] == 5
    assert j["analysis"]["discovery"]["raw_candidates"] == 0
    # Markdown must explain legitimate zero
    md = report.to_markdown()
    assert "Services discovered: 5" in md
    assert "Candidates generated: 0" in md
    assert "No Tier 1 candidates generated" in md or "No Tier 1 candidates were generated" in md
    assert "does not mean the services have no dependencies" in md


# Case B — No sources (parsing failure / no compose)
def test_case_b_no_sources():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # No compose file
        res = run_one_repo(tmp, None, tmp / "out", "auto", "low", None, True)
        # Should have error and 0 services
        assert "not found" in res["error"].lower()
        j = json.loads(Path(res["report.json"]).read_text(encoding="utf-8"))
        # New accounting must show 0 sources used and 0 services
        assert j["inputs"]["sources_used"] == []
        assert j["analysis"]["parsed"]["services"] == 0
        assert j["summary"]["services_analyzed"] == 0
        # Must be distinguishable from Case A (which has services 5)
        assert j["analysis"]["parsed"]["services"] == 0
        md = Path(res["report.md"]).read_text(encoding="utf-8")
        assert "No services discovered" in md or "no supported Compose configuration found" in md.lower()


# Case C — Candidates filtered away (generic)
def test_case_c_candidates_filtered():
    yaml = """
services:
  a:
    environment:
      PORT: 8000
      DEBUG: 1
  b:
    environment:
      PORT: 8000
      DEBUG: 1
"""
    proj = parse_compose_string(yaml)
    candidates = discover_candidates(proj)
    # Should have 2 candidates (PORT, DEBUG) before filtering
    assert len(candidates) == 2
    pkgs = build_evidence_packages(candidates, proj)
    # Both are generic -> filtered to 0
    assert len(pkgs) == 0
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 0
    model = CouplingModel.from_grouped_judgments([])
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, total_services=len(proj.services), accounting={
        "application_root": "test",
        "sources": {"discovered": ["docker-compose.yml"], "discovered_count": 1, "successfully_parsed": ["docker-compose.yml"], "successfully_parsed_count": 1, "used": ["docker-compose.yml"], "used_count": 1},
        "parsed": {"services": 2, "named_volumes": 0},
        "discovery": {"raw_candidates": len(candidates), "observations": len(pkgs), "filtered_out": len(candidates) - len(pkgs)},
        "aggregation": {"resource_groups": 0, "observations": 0},
        "judgment": {"groups_judged": 0, "meaningful": 0, "coincidental": 0, "uncertain": 0, "llm_calls": 0, "cache_hits": 0},
        "graph": {"nodes": 0, "edges": 0, "service_nodes": 0, "resource_nodes": 0},
    })
    assert report.summary["services_analyzed"] == 2
    j = json.loads(report.to_json())
    assert j["analysis"]["discovery"]["raw_candidates"] == 2
    assert j["analysis"]["discovery"]["observations"] == 0
    assert j["analysis"]["discovery"]["filtered_out"] == 2
    md = report.to_markdown()
    assert "Candidates generated: 2" in md
    assert "Candidates were generated" in md or "filtered" in md.lower()


# Case D — Aggregation (6 observations -> 1 group)
def test_case_d_aggregation():
    yaml = """
services:
  calcom:
    environment:
      DATABASE_URL: "postgresql://${HOST}/${DB}"
  calcom-api:
    environment:
      DATABASE_URL: "postgresql://${HOST}/${DB}"
  studio:
    environment:
      DATABASE_URL: "postgresql://${HOST}/${DB}"
"""
    proj = parse_compose_string(yaml)
    candidates = discover_candidates(proj)
    pkgs = build_evidence_packages(candidates, proj)
    # 3 services -> 3 choose 2 = 3 pairs * 1 var = 3 packages? Actually each pair shares DATABASE_URL, so 3 packages
    # But with the yaml above, we have 3 services each with same DATABASE_URL, so 3 candidates
    assert len(pkgs) == 3
    groups = aggregate_evidence_packages(pkgs)
    # All 3 observations share same normalized (partial) -> 1 group
    assert len(groups) == 1
    assert groups[0].evidence_count == 3
    pairs = [(g, JudgeResult(verdict="meaningful", confidence=0.8, reason="ok", model="test")) for g in groups]
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, total_services=len(proj.services), accounting={
        "application_root": "test",
        "sources": {"discovered": ["docker-compose.yml"], "discovered_count": 1, "successfully_parsed": ["docker-compose.yml"], "successfully_parsed_count": 1, "used": ["docker-compose.yml"], "used_count": 1},
        "parsed": {"services": 3, "named_volumes": 0},
        "discovery": {"raw_candidates": len(candidates), "observations": len(pkgs), "filtered_out": 0},
        "aggregation": {"resource_groups": len(groups), "observations": len(pkgs)},
        "judgment": {"groups_judged": len(groups), "meaningful": 1, "coincidental": 0, "uncertain": 0, "llm_calls": 1, "cache_hits": 0},
        "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "service_nodes": 3, "resource_nodes": 1},
    })
    j = json.loads(report.to_json())
    assert j["analysis"]["aggregation"]["resource_groups"] == 1
    assert j["analysis"]["discovery"]["observations"] == 3
    md = report.to_markdown()
    assert "3 configuration observations were grouped into 1 shared resource" in md


# Case E — Normal meaningful finding
def test_case_e_normal_meaningful():
    yaml = """
services:
  orders:
    environment:
      DB_HOST: postgres
  reports:
    environment:
      DB_HOST: postgres
  postgres:
    image: postgres:16
"""
    proj = parse_compose_string(yaml)
    candidates = discover_candidates(proj)
    pkgs = build_evidence_packages(candidates, proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    pairs = [(g, JudgeResult(verdict="meaningful", confidence=0.9, reason="shared db", model="test")) for g in groups]
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, total_services=len(proj.services), accounting={
        "application_root": "test",
        "sources": {"discovered": ["docker-compose.yml"], "discovered_count": 1, "successfully_parsed": ["docker-compose.yml"], "successfully_parsed_count": 1, "used": ["docker-compose.yml"], "used_count": 1},
        "parsed": {"services": 3, "named_volumes": 0},
        "discovery": {"raw_candidates": len(candidates), "observations": len(pkgs), "filtered_out": 0},
        "aggregation": {"resource_groups": 1, "observations": 1},
        "judgment": {"groups_judged": 1, "meaningful": 1, "coincidental": 0, "uncertain": 0, "llm_calls": 1, "cache_hits": 0},
        "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "service_nodes": 2, "resource_nodes": 1},
    })
    j = json.loads(report.to_json())
    assert j["analysis"]["parsed"]["services"] == 3
    assert j["analysis"]["discovery"]["raw_candidates"] == 1
    assert j["analysis"]["aggregation"]["resource_groups"] == 1
    assert j["analysis"]["judgment"]["meaningful"] == 1
    assert j["analysis"]["graph"]["nodes"] == 3  # 2 services + 1 resource (postgres service not in graph, only orders/reports + resource)
    # Check CLI and report agree
    assert j["summary"]["services_analyzed"] == 3


# Case F — Input source reporting (relative paths)
def test_case_f_input_source_reporting(monkeypatch):
    # Hermetic: block the developer's real .env keys so this test never
    # performs live LLM calls (run_one_repo loads .env on purpose in prod).
    for var in ("OPENROUTER_API_KEY", "OR_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("blindspot.cli.load_dotenv", lambda *a, **k: False)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Create a compose file
        compose = tmp / "docker-compose.yml"
        compose.write_text("""
services:
  web:
    image: nginx
    environment:
      FOO: bar
  api:
    image: nginx
    environment:
      FOO: bar
""", encoding="utf-8")
        res = run_one_repo(tmp, None, tmp / "out", "auto", "low", None, True)
        j = json.loads(Path(res["report.json"]).read_text(encoding="utf-8"))
        # Should record relative path
        assert j["inputs"]["sources_used"] == ["docker-compose.yml"]
        assert j["application"]["root"] == str(tmp.resolve())
        # Also test with explicit compose.yaml
        compose2 = tmp / "compose.yaml"
        compose2.write_text("services:\n  a:\n    image: nginx\n", encoding="utf-8")
        # Remove first compose to force second
        compose.unlink()
        res2 = run_one_repo(tmp, None, tmp / "out2", "auto", "low", None, True)
        j2 = json.loads(Path(res2["report.json"]).read_text(encoding="utf-8"))
        assert j2["inputs"]["sources_used"] == ["compose.yaml"]
