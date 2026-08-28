"""Stage 2 Tests: Candidate Discovery

Verifies discovery finds shared env config and shared named volumes
without deciding dependency — filtering/LLM will handle near-miss.
"""

from pathlib import Path

from blindspot.parser import parse_compose_file, parse_compose_string
from blindspot.discovery import discover_candidates


def _has_candidate(cands, service_a, service_b, resource, resource_type=None, value=None):
    for c in cands:
        if {c.service_a, c.service_b} == {service_a, service_b} and c.resource == resource:
            if resource_type is not None and c.resource_type != resource_type:
                continue
            if value is not None and c.value != value:
                continue
            # if value is None we don't enforce check unless explicitly passed as sentinel
            # to check for value=None when values differ, caller can pass value="__none__"
            return True
    return False


def test_discovery_shared_env_messy():
    proj = parse_compose_file("fixtures/shared_env/docker-compose.yml")
    cands = discover_candidates(proj)
    # Must find DB_HOST and DB_NAME as env_var candidates (true positives) — resource is key, value is shared value
    assert _has_candidate(cands, "orders", "reports", "DB_HOST", "env_var", "shared-db")
    assert _has_candidate(cands, "orders", "reports", "DB_NAME", "env_var", "orders")
    # Verify value field is split from resource (cleaner for filter→LLM→graph)
    db_host = [c for c in cands if c.resource == "DB_HOST"][0]
    assert db_host.resource == "DB_HOST" and db_host.value == "shared-db"
    # Messy fixture also shares SHARED_EXTRA via common.env — should be discovered
    assert _has_candidate(cands, "orders", "reports", "SHARED_EXTRA", "env_var", "keep")
    # No volume candidates in this fixture
    assert all(c.resource_type != "named_volume" for c in cands)
    # Deterministic ordering
    cands2 = discover_candidates(proj)
    assert cands == cands2


def test_discovery_shared_volume_messy():
    proj = parse_compose_file("fixtures/shared_volume/docker-compose.yml")
    cands = discover_candidates(proj)
    # Must find shared named volume — resource is name, value is None
    assert _has_candidate(cands, "orders", "reports", "shared-data", "named_volume")
    vol = [c for c in cands if c.resource == "shared-data"][0]
    assert vol.value is None and vol.resource_type == "named_volume"
    # Messy fixture also shares DATA_PATH via .env interpolation — discovered as env_var with value split
    assert _has_candidate(cands, "orders", "reports", "DATA_PATH", "env_var", "/data")
    data_path = [c for c in cands if c.resource == "DATA_PATH"][0]
    assert data_path.value == "/data"
    # Should NOT create candidates for anonymous/bind volumes (none here) — total is 2
    assert len([c for c in cands if c.resource_type == "named_volume"]) == 1
    # Deterministic
    assert cands == discover_candidates(proj)


def test_discovery_near_miss_messy():
    proj = parse_compose_file("fixtures/near_miss/docker-compose.yml")
    cands = discover_candidates(proj)
    # Must find PORT as candidate even though values differ — discovery is conservative
    # resource is key only, value is None when mismatched
    assert _has_candidate(cands, "orders", "reports", "PORT", "env_var")
    # Verify evidence notes different values and value is None
    port_cand = [c for c in cands if c.resource == "PORT"][0]
    assert port_cand.value is None
    assert "different values" in port_cand.evidence
    assert "8000" in port_cand.evidence and "9000" in port_cand.evidence
    # Messy fixture also shares APP_ENV and SHARED_NOISE via env_file — discovered with value split
    assert _has_candidate(cands, "orders", "reports", "APP_ENV", "env_var", "development")
    assert _has_candidate(cands, "orders", "reports", "SHARED_NOISE", "env_var", "1")
    # No volume candidates
    assert all(c.resource_type != "named_volume" for c in cands)


def test_discovery_same_key_different_values_still_candidate():
    proj = parse_compose_string("""
services:
  a:
    environment: {PORT: 8000}
  b:
    environment: {PORT: 9000}
""")
    cands = discover_candidates(proj)
    assert len(cands) == 1
    assert cands[0].resource == "PORT"
    assert cands[0].value is None
    assert "different values" in cands[0].evidence


def test_discovery_same_key_same_value():
    proj = parse_compose_string("""
services:
  a:
    environment: {DB_HOST: shared-db}
  b:
    environment: {DB_HOST: shared-db}
""")
    cands = discover_candidates(proj)
    assert len(cands) == 1
    assert cands[0].resource == "DB_HOST"
    assert cands[0].value == "shared-db"
    assert cands[0].resource_type == "env_var"


def test_discovery_bind_and_anonymous_ignored():
    proj = parse_compose_string("""
services:
  a:
    volumes: ["./src:/app", "/tmp/cache"]
  b:
    volumes: ["./src:/app", "/tmp/cache"]
""")
    cands = discover_candidates(proj)
    # bind (./src) and anonymous (/tmp/cache) must NOT be candidates
    assert len(cands) == 0


def test_discovery_named_volume_shared():
    proj = parse_compose_string("""
services:
  a:
    volumes: ["shared-data:/data"]
  b:
    volumes: ["shared-data:/data"]
""")
    cands = discover_candidates(proj)
    assert len(cands) == 1
    assert cands[0].resource == "shared-data"
    assert cands[0].value is None
    assert cands[0].resource_type == "named_volume"


def test_discovery_three_services_pairs():
    proj = parse_compose_string("""
services:
  a:
    environment: {FOO: bar}
  b:
    environment: {FOO: bar}
  c:
    environment: {FOO: bar}
""")
    cands = discover_candidates(proj)
    # 3 choose 2 = 3 pairs, each with FOO — resource is key, value is shared value
    assert len(cands) == 3
    pairs = {(c.service_a, c.service_b) for c in cands}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}
    for c in cands:
        assert c.resource == "FOO" and c.value == "bar"
