"""Stage 1+2 acceptance: input adapters + L0/L1 discovery (hermetic, no LLM)."""

import json
import tempfile
from pathlib import Path

from blindspot.inputs import (
    SUPPORTED_COMPOSE_FILENAMES,
    discover_compose_files,
    find_compose_file,
    load_compose_document,
)
from blindspot.parser import parse_compose_file, parse_compose_string
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages, _decide_with_project
from blindspot.aggregation import aggregate_evidence_packages
from blindspot.coupling import CouplingModel
from blindspot.graph import build_graph_from_groups
from blindspot.judge import JudgeResult


def _levels(cands):
    return {(c.service_a, c.service_b, c.resource_type, c.level, c.relationship_type) for c in cands}


# 1. Existing Compose behavior remains correct
def test_existing_fixtures_still_parse():
    for name in ("shared_env", "shared_volume", "near_miss"):
        proj = parse_compose_file(f"fixtures/{name}/docker-compose.yml")
        assert len(proj.services) >= 2
        assert proj.sources == ("docker-compose.yml",)


# 2. Supported filename variations work
def test_filename_variations_discovered_and_parsed():
    body = "services:\n  a:\n    image: nginx\n"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for name in SUPPORTED_COMPOSE_FILENAMES:
            (tmp / name).write_text(
                json.dumps({"services": {"a": {"image": "nginx"}}}) if name.endswith(".json") else body,
                encoding="utf-8",
            )
        found = {p.name for p in discover_compose_files(tmp)}
        assert set(SUPPORTED_COMPOSE_FILENAMES) <= found
        # find_compose_file prefers top-level deterministically (first supported name present)
        first = find_compose_file(tmp)
        assert first is not None and first.name == SUPPORTED_COMPOSE_FILENAMES[0]
        # each variant parses to one service
        for name in SUPPORTED_COMPOSE_FILENAMES:
            proj = parse_compose_file(tmp / name)
            assert set(proj.services) == {"a"}


# 3. Equivalent YAML and JSON normalize consistently
def test_yaml_json_equivalence():
    yml = "services:\n  web:\n    image: nginx:1.0\n    environment:\n      FOO: bar\n    depends_on: [db]\n  db:\n    image: postgres:16\n"
    js = json.dumps({"services": {"web": {"image": "nginx:1.0", "environment": {"FOO": "bar"}, "depends_on": ["db"]}, "db": {"image": "postgres:16"}}})
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "docker-compose.yml").write_text(yml, encoding="utf-8")
        (tmp / "compose.json").write_text(js, encoding="utf-8")
        assert load_compose_document(tmp / "compose.json")["services"]["web"]["image"] == "nginx:1.0"
        py = parse_compose_file(tmp / "docker-compose.yml")
        pj = parse_compose_file(tmp / "compose.json")
        assert {k: v.to_dict() for k, v in py.services.items()} == {k: v.to_dict() for k, v in pj.services.items()} or (
            py.services["web"].environment == pj.services["web"].environment
            and py.services["web"].depends_on == pj.services["web"].depends_on == ("db",)
        )
        assert discover_candidates(py) == discover_candidates(pj) or (
            {(c.service_a, c.service_b, c.resource, c.resource_type) for c in discover_candidates(py)}
            == {(c.service_a, c.service_b, c.resource, c.resource_type) for c in discover_candidates(pj)}
        )


# 4. .env / env_file / interpolation / multi-file remain correct
def test_env_interpolation_and_multifile_with_depends():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / ".env").write_text("BASE_HOST=db\n", encoding="utf-8")
        (tmp / "common.env").write_text("FROM_FILE=keep\n", encoding="utf-8")
        (tmp / "base.yml").write_text(
            "services:\n  a:\n    image: x\n    env_file: [common.env]\n    environment:\n      HOST: ${BASE_HOST}\n      MISS: ${NOPE}\n      DEF: ${NOPE:-fallback}\n    depends_on: [db]\n  db:\n    image: postgres:16\n",
            encoding="utf-8",
        )
        (tmp / "over.yml").write_text(
            "services:\n  a:\n    environment:\n      EXTRA: \"1\"\n    depends_on: [cache]\n  cache:\n    image: redis:7\n",
            encoding="utf-8",
        )
        proj = parse_compose_file([tmp / "base.yml", tmp / "over.yml"])
        a = proj.services["a"]
        assert a.environment["HOST"] == "db"  # interpolated from .env-adjacent? base.yml dir .env
        # .env is resolved per-file (base.yml dir has .env at tmp) — HOST must not be invented
        assert a.environment["MISS"] == "${NOPE}"  # unresolved preserved
        assert a.environment["DEF"] == "fallback"
        assert a.environment["FROM_FILE"] == "keep"
        assert a.environment["EXTRA"] == "1"
        assert a.depends_on == ("cache", "db")  # union, sorted
        assert set(proj.sources) == {"base.yml", "over.yml"}


# 5. Explicit L0 represented, not confused with hidden coupling
def test_l0_explicit_not_hidden():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    cands = discover_candidates(proj)
    l0 = [c for c in cands if c.level == "L0"]
    assert l0, "depends_on must yield L0 candidates"
    assert all(c.resource_type == "service_dependency" and c.relationship_type == "explicit_dependency" for c in l0)
    assert all(c.origin == "compose:depends_on" for c in l0)
    assert ("api", "db") in {(c.service_a, c.service_b) for c in l0}
    # L0 directional, includes missing-target uncertainty (lonely -> ghost)
    ghost = [c for c in l0 if c.service_b == "ghost"]
    assert len(ghost) == 1 and ghost[0].resource_identity is None
    # L0 distinguishable from L1 hidden
    assert all(c.level == "L1" for c in cands if c.resource_type in ("env_var", "named_volume", "shared_endpoint"))


# 6. Shared-resource candidates discovered (env + cross-var endpoint)
def test_shared_resource_candidates():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    cands = discover_candidates(proj)
    # Same-key unresolved shared ref still discovered (uncertainty preserved)
    assert any(c.resource == "MYSTERY_REF" and c.resource_type == "env_var" for c in cands)
    # Cross-variable same endpoint: DATABASE_URL vs DB_URL -> one shared_endpoint candidate
    eps = [c for c in cands if c.resource_type == "shared_endpoint"]
    assert len(eps) == 1
    ep = eps[0]
    assert {ep.service_a, ep.service_b} == {"api", "worker"}
    assert ep.resource_identity == "postgresql|db|5432|appdb"
    assert ep.level == "L1" and ep.relationship_type == "shared_endpoint"


# 7. Generic overlap does not become a resource dependency
def test_generic_overlap_not_resource():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    cands = discover_candidates(proj)
    # PORT shared key exists at discovery (broad) but filtering drops it; no endpoint for PORT
    assert any(c.resource == "PORT" and c.resource_type == "env_var" for c in cands)
    assert not any(c.resource_type == "shared_endpoint" and "8000" in (c.resource or "") for c in cands)
    pkgs = build_evidence_packages(cands, proj)
    assert not any(p.resource == "PORT" for p in pkgs)
    keep, _ = _decide_with_project(next(c for c in cands if c.resource == "PORT"), proj)
    assert keep is False


# 8. Unresolved references preserve uncertainty
def test_unresolved_preserved():
    proj = parse_compose_string("services:\n  a:\n    environment:\n      X: ${MISSING}\n  b:\n    environment:\n      X: ${MISSING}\n")
    cands = discover_candidates(proj)
    assert len(cands) == 1 and cands[0].value == "${MISSING}"
    pkgs = build_evidence_packages(cands, proj)
    assert len(pkgs) == 1
    pkg = pkgs[0]
    assert "MISSING" in list(pkg.unresolved_vars) or "${MISSING}" in str(pkg.final_value)
    assert pkg.resolution_status in ("unresolved", "partial")
    assert pkg.value == "${MISSING}"  # never invented


# 9. Candidate IDs + ordering deterministic
def test_candidate_ids_deterministic():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    c1 = discover_candidates(proj)
    c2 = discover_candidates(parse_compose_file("fixtures/stage12_levels/docker-compose.yml"))
    assert c1 == c2
    assert [c.candidate_id for c in c1] == [c.candidate_id for c in c2]
    assert len({c.candidate_id for c in c1}) == len(c1)  # unique
    keys = [(c.service_a, c.service_b, c.resource_type, c.resource) for c in c1]
    assert keys == sorted(keys)
    d1 = [c.to_dict() for c in c1]
    assert all("candidate_id" in d and "level" in d and "origin" in d and "provenance" in d for d in d1)
    import json as _j
    _j.dumps(d1)  # serializable


# 10. Dedup equivalents without merging distinct resources
def test_dedup_distinct_kept():
    proj = parse_compose_string(
        "services:\n  a:\n    environment:\n      U1: postgresql://u@h1:5432/d1\n  b:\n    environment:\n      V1: postgresql://u@h1:5432/d1\n  c:\n    environment:\n      W1: postgresql://u@h2:5432/d2\n"
    )
    cands = discover_candidates(proj)
    eps = [c for c in cands if c.resource_type == "shared_endpoint"]
    # a-b share h1 identity (one candidate), c distinct (no candidate with a/b on h2)
    assert len(eps) == 1 and {eps[0].service_a, eps[0].service_b} == {"a", "b"}
    assert eps[0].resource == "postgresql|h1|5432|d1"


# 11. Explicit L0 edges are service→service; hidden edges stay service→resource.
def test_graph_unified_explicit_and_hidden():
    proj = parse_compose_file("fixtures/stage12_levels/docker-compose.yml")
    cands = discover_candidates(proj)
    pkgs = build_evidence_packages(cands, proj)
    groups = aggregate_evidence_packages(pkgs)
    assert groups
    pairs = [(g, JudgeResult(verdict="meaningful", confidence=0.8, reason="test", model="test")) for g in groups]
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)

    explicit = [e for e in graph["edges"] if e["data"].get("classification") == "explicit"]
    hidden = [e for e in graph["edges"] if e["data"].get("classification") != "explicit"]
    assert explicit, "depends_on must produce explicit service→service edges"
    assert hidden, "shared resources must produce hidden service→resource edges"

    for e in explicit:
        assert e["source"].startswith("service:") and e["target"].startswith("service:")
        assert e["data"]["relationship_type"] == "explicit_dependency"
        assert e["data"]["semantics"] == "startup_dependency"
        assert "confidence" not in e["data"]
        assert "decision" not in e["data"]
    assert "explicit:service:api->service:db" in {e["id"] for e in explicit}
    ghost = [e for e in explicit if e["target"] == "service:ghost"]
    assert ghost and ghost[0]["data"]["target_resolved"] is False

    for e in hidden:
        assert e["source"].startswith("service:") and e["target"].startswith("resource:")
        assert e["data"]["semantics"] == "resource_mediated"
        assert "confidence" in e["data"]

    # L0 is no longer represented as a resource node.
    rtypes = {n["data"].get("resource_type") for n in graph["nodes"] if n["type"] == "resource"}
    assert "service_dependency" not in rtypes
    assert rtypes & {"env_var", "shared_endpoint", "named_volume"}


# Unsupported inputs documented: non-mapping top-level rejected; K8s/Terraform not adapters
def test_unsupported_inputs_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bad = tmp / "docker-compose.yml"
        bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
        try:
            load_compose_document(bad)
            assert False, "non-mapping must raise"
        except ValueError:
            pass
