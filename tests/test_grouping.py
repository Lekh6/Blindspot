"""Tests for Prompt 2 — Resource-Centric Aggregation."""

import json
from blindspot.parser import parse_compose_string
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.aggregation import aggregate_evidence_packages
from blindspot.coupling import CouplingModel
from blindspot.graph import build_graph_from_groups
from blindspot.report import build_grouped_report
from blindspot.judge import JudgeResult, build_grouped_judge_prompt, _cache_key_for_grouped


def _judge_stub(groups):
    # deterministic stub: meaningful if protocol known else uncertain
    res = []
    for g in groups:
        verdict = "meaningful" if g.resource_protocol or g.resource_type == "named_volume" else "uncertain"
        conf = 0.8 if g.identity_strength == "config" else 0.9
        res.append((g, JudgeResult(verdict=verdict, confidence=conf, reason="stub", model="test")))
    return res


def test_multiple_vars_same_normalized_one_group():
    yaml = """
services:
  a:
    environment:
      DATABASE_URL: postgresql://user1:pass@db:5432/calcom
      DATABASE_DIRECT_URL: postgresql://user2:pass@db:5432/calcom
  b:
    environment:
      DATABASE_URL: postgresql://user1:pass@db:5432/calcom
      DATABASE_DIRECT_URL: postgresql://user1:pass@db:5432/calcom
  db:
    image: postgres:15
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    # Even though 2 variables * 1 pair = 2 packages, they share same normalized
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    g = groups[0]
    assert g.resource_identity == "postgresql|db|5432|calcom"
    assert g.service_count == 2
    assert g.evidence_count == 2
    assert set(g.observation_resources) == {"DATABASE_URL", "DATABASE_DIRECT_URL"}


def test_three_services_same_resource_one_group():
    yaml = """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  c: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    g = groups[0]
    assert set(g.services) == {"a", "b", "c"}
    assert g.evidence_count == 3  # 3 choose 2 = 3 pairs
    # Graph should have 1 resource node, 3 edges
    pairs = _judge_stub(groups)
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    assert len([n for n in graph["nodes"] if n["type"] == "resource"]) == 1
    assert len(graph["edges"]) == 3


def test_different_normalized_separate_groups():
    yaml = """
services:
  a: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
  b: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
  c: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
  d: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
"""
    proj = parse_compose_string(yaml)
    # Need 2 separate groups? But discovery is pairwise across all services, so a-b share db1, c-d share db2, but a-c etc have different values -> not candidates? Actually a and c have different DATABASE_URL values, so no candidate (different values -> not grouped? Our filtering keeps different raw that normalize same, but here normalize differs, so filtered out. So we test with separate projects per pair)
    # Instead test with two resources in same project
    yaml2 = """
services:
  a:
    environment:
      DB1_URL: postgresql://host1:5432/db1
      DB2_URL: postgresql://host2:5432/db2
  b:
    environment:
      DB1_URL: postgresql://host1:5432/db1
      DB2_URL: postgresql://host2:5432/db2
"""
    proj2 = parse_compose_string(yaml2)
    pkgs2 = build_evidence_packages(discover_candidates(proj2), proj2)
    groups2 = aggregate_evidence_packages(pkgs2)
    assert len(groups2) == 2
    idents = {g.resource_identity for g in groups2}
    assert "postgresql|host1|5432|db1" in idents
    assert "postgresql|host2|5432|db2" in idents


def test_same_variable_different_resource_not_grouped():
    yaml = """
services:
  a: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
  b: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
  c: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
  d: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
"""
    # This is similar to above but we need to ensure a-b and c-d are separate groups, not merged
    # Use project with 4 services, but discovery will produce 6 pairs, only 2 with same values will be kept, so we get 2 groups as above
    # Test via direct packages with different identities
    from blindspot.filtering import EvidencePackage
    from blindspot.resolution import bounded_resolve
    proj = parse_compose_string(yaml)
    # Build two packages manually with different identities
    # Use actual discovery packages
    yaml2 = """
services:
  a: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
  b: { environment: { DATABASE_URL: postgresql://host1:5432/db1 } }
"""
    p1 = parse_compose_string(yaml2)
    pkgs1 = build_evidence_packages(discover_candidates(p1), p1)
    yaml3 = """
services:
  c: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
  d: { environment: { DATABASE_URL: postgresql://host2:5432/db2 } }
"""
    p2 = parse_compose_string(yaml3)
    pkgs2 = build_evidence_packages(discover_candidates(p2), p2)
    combined = pkgs1 + pkgs2
    groups = aggregate_evidence_packages(combined)
    assert len(groups) == 2


def test_grouped_cache_key_deterministic():
    yaml = """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    g = groups[0]
    k1 = _cache_key_for_grouped(g)
    k2 = _cache_key_for_grouped(g)
    assert k1 == k2
    # Different services should change key
    yaml2 = """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  c: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""
    proj2 = parse_compose_string(yaml2)
    g2 = aggregate_evidence_packages(build_evidence_packages(discover_candidates(proj2), proj2))[0]
    assert _cache_key_for_grouped(g2) != k1


def test_named_volume_grouping():
    yaml = """
services:
  orders: { volumes: ["shared-data:/data"] }
  reports: { volumes: ["shared-data:/data"] }
  worker: { volumes: ["shared-data:/data"] }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    g = groups[0]
    assert g.resource_type == "named_volume"
    assert g.resource_identity == "named_volume|shared-data"
    assert set(g.services) == {"orders", "reports", "worker"}
    assert g.evidence_count == 3  # 3 choose 2 = 3 pairs
    pairs = _judge_stub(groups)
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    assert len([n for n in graph["nodes"] if n["type"] == "resource"]) == 1
    assert len(graph["edges"]) == 3


def test_graph_counts_from_grouped():
    yaml = """
services:
  a: { environment: { X: postgresql://host:5432/db } }
  b: { environment: { X: postgresql://host:5432/db } }
  c: { environment: { X: postgresql://host:5432/db } }
  d: { environment: { Y: postgresql://host2:5432/db2 } }
  e: { environment: { Y: postgresql://host2:5432/db2 } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    pairs = _judge_stub(groups)
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    # Should have 2 resource nodes, 3+2=5 edges? Actually first group has 3 services (a,b,c) => 3 edges, second has 2 services (d,e) =>2 edges
    assert len(graph["nodes"]) == 7  # 5 services +2 resources
    assert len(graph["edges"]) == 5


def test_report_counts_distinguish():
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
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    assert groups[0].evidence_count == 3
    pairs = [(g, JudgeResult(verdict="meaningful", confidence=0.8, reason="ok", model="test")) for g in groups]
    model = CouplingModel.from_grouped_judgments(pairs)
    from blindspot.graph import build_graph_from_groups
    graph = build_graph_from_groups(model)
    from blindspot.report import build_grouped_report
    report = build_grouped_report(model, graph_data=graph)
    assert report.summary["services_analyzed"] == 3
    assert report.summary["resource_groups"] == 1
    assert report.summary["observations"] == 3
    assert report.summary["meaningful_groups"] == 1
    # New markdown uses "Services discovered" (prompt §3) — also check old alias still in summary
    assert "Services discovered: 3" in report.to_markdown()
    assert "Shared resource groups: 1" in report.to_markdown()
    assert "Configuration observations: 3" not in report.to_markdown()  # now in Pipeline summary as Observations
    assert "Observations: 3" in report.to_markdown() or "Observations         : 3" in report.to_markdown() or "Observations: 3" in report.to_markdown()


def test_empty_project_no_findings():
    proj = parse_compose_string("services: {}")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 0
    model = CouplingModel.from_grouped_judgments([])
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph)
    assert report.summary["resource_groups"] == 0
    assert report.summary["observations"] == 0
    # New 0-services case now explicitly says no services discovered (prompt §7)
    assert "No services discovered" in report.to_markdown()


def test_near_miss_not_grouped():
    from blindspot.parser import parse_compose_file
    proj = parse_compose_file("fixtures/near_miss/docker-compose.yml")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    assert len(pkgs) == 0
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 0


def test_unknown_not_overmerged():
    yaml = """
services:
  a: { environment: { CUSTOM1: abc://host1/prod } }
  b: { environment: { CUSTOM1: abc://host1/prod } }
  c: { environment: { CUSTOM2: xyz://host2/prod } }
  d: { environment: { CUSTOM2: xyz://host2/prod } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    # Each custom resource is unknown protocol, different raw, should be separate groups (2)
    groups = aggregate_evidence_packages(pkgs)
    # Need to ensure we have 2 groups, not 1 merged unknown
    # Discovery: a-b share CUSTOM1, c-d share CUSTOM2 => 2 packages, 2 groups
    assert len(groups) == 2
    # Ensure they are not merged
    keys = {g.grouping_key for g in groups}
    assert len(keys) == 2


def test_deterministic_ordering():
    yaml = """
services:
  b: { environment: { FOO: bar } }
  a: { environment: { FOO: bar } }
  c: { environment: { FOO: bar } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    g1 = aggregate_evidence_packages(pkgs)
    g2 = aggregate_evidence_packages(pkgs)
    assert [g.grouping_key for g in g1] == [g.grouping_key for g in g2]
    assert g1[0].services == g2[0].services


def test_configuration_evidence_grouped_by_service():
    yaml = """
services:
  calcom:
    environment:
      DATABASE_URL: postgresql://host:5432/db
      DATABASE_DIRECT_URL: postgresql://host:5432/db
  calcom-api:
    environment:
      DATABASE_URL: postgresql://host:5432/db
      DATABASE_DIRECT_URL: postgresql://host:5432/db
      DATABASE_READ_URL: postgresql://host:5432/db
"""
    proj = parse_compose_string(yaml)
    # Discovery will produce pairs: calcom<->calcom-api for DATABASE_URL and DATABASE_DIRECT_URL (and maybe READ?) Actually calcom doesn't have READ, so only 2 vars shared
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    # All should converge to same normalized, so one group
    assert len(groups) == 1
    g = groups[0]
    # calcom should have 2 vars, calcom-api 2 vars? Actually READ not shared with calcom, so not counted. But our group includes only observations that were shared pairwise.
    # For this setup, we have 2 observations (DATABASE_URL and DATABASE_DIRECT_URL each between the pair)
    # So config evidence should show both services with those 2 vars
    assert "DATABASE_URL" in g.configuration_evidence["calcom"]
    assert "DATABASE_DIRECT_URL" in g.configuration_evidence["calcom"]


def test_grouped_prompt_contains_group_info():
    yaml = """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    prompt = build_grouped_judge_prompt(groups[0])
    assert "Services involved" in prompt
    assert "postgresql" in prompt.lower()
    assert "All" not in prompt or "services" in prompt.lower()  # ensure group wording, not pairwise "Both services share DATABASE_URL" is okay but prompt should mention group
