"""Stage 2 Tests: Parse + Normalize

Covers required cases:
1. Parsing a service
2. Environment mapping syntax
3. Environment list syntax
4. .env variable resolution
5. Named volume parsing
6. Multiple services
7. Missing optional env/volume sections
8. Three Stage 1 fixtures (facts only, no dependency inference)
"""

import tempfile
from pathlib import Path

import pytest

from blindspot.parser import (
    Project,
    normalize_environment,
    normalize_volume,
    normalize_volumes,
    parse_compose_file,
    parse_compose_string,
    load_env_file,
)


# ---------------------------------------------------------------------------
# 1. Parsing a service
# ---------------------------------------------------------------------------

def test_parsing_single_service():
    yaml_text = """
services:
  orders:
    image: orders:latest
    environment:
      DB_HOST: shared-db
"""
    project = parse_compose_string(yaml_text)
    assert "orders" in project.services
    svc = project.services["orders"]
    assert svc.name == "orders"
    assert svc.environment == {"DB_HOST": "shared-db"}
    assert svc.volumes == []


# ---------------------------------------------------------------------------
# 2. Environment mapping syntax
# ---------------------------------------------------------------------------

def test_environment_mapping_syntax():
    raw = {"DB_HOST": "postgres", "DB_NAME": "orders", "DEBUG": "true"}
    result = normalize_environment(raw)
    assert result == {"DB_HOST": "postgres", "DB_NAME": "orders", "DEBUG": "true"}


def test_environment_mapping_with_null_and_int():
    # YAML may parse numbers/booleans; ensure coercion to string
    raw = {"PORT": 8000, "ENABLED": True, "EMPTY": None}
    result = normalize_environment(raw)
    assert result == {"PORT": "8000", "ENABLED": "True", "EMPTY": None}


# ---------------------------------------------------------------------------
# 3. Environment list syntax
# ---------------------------------------------------------------------------

def test_environment_list_syntax():
    raw = ["DB_HOST=postgres", "DB_NAME=orders"]
    result = normalize_environment(raw)
    assert result == {"DB_HOST": "postgres", "DB_NAME": "orders"}


def test_environment_list_without_value():
    raw = ["DB_HOST=postgres", "DEBUG"]
    result = normalize_environment(raw)
    assert result == {"DB_HOST": "postgres", "DEBUG": None}


def test_environment_list_with_equals_in_value():
    raw = ["DATABASE_URL=postgres://user:pass@host/db?ssl=true"]
    result = normalize_environment(raw)
    assert result == {"DATABASE_URL": "postgres://user:pass@host/db?ssl=true"}


# ---------------------------------------------------------------------------
# 4. .env variable resolution
# ---------------------------------------------------------------------------

def test_env_resolution_braced():
    env_vars = {"DB_HOST": "shared-db"}
    raw = {"DB_HOST": "${DB_HOST}"}
    result = normalize_environment(raw, env_vars)
    assert result == {"DB_HOST": "shared-db"}


def test_env_resolution_unbraced():
    env_vars = {"DB_HOST": "shared-db"}
    raw = {"DB_HOST": "$DB_HOST"}
    result = normalize_environment(raw, env_vars)
    assert result == {"DB_HOST": "shared-db"}


def test_env_resolution_unresolved_preserved():
    env_vars = {}
    raw = {"DB_HOST": "${DB_HOST}"}
    result = normalize_environment(raw, env_vars)
    # Must preserve original, not invent empty string
    assert result == {"DB_HOST": "${DB_HOST}"}


def test_env_resolution_with_default():
    env_vars = {}
    raw = {"DB_HOST": "${DB_HOST:-fallback-db}"}
    result = normalize_environment(raw, env_vars)
    assert result == {"DB_HOST": "fallback-db"}


def test_env_resolution_with_default_when_set():
    env_vars = {"DB_HOST": "shared-db"}
    raw = {"DB_HOST": "${DB_HOST:-fallback-db}"}
    result = normalize_environment(raw, env_vars)
    assert result == {"DB_HOST": "shared-db"}


def test_env_resolution_list_syntax():
    env_vars = {"DB_HOST": "shared-db"}
    raw = ["DB_HOST=${DB_HOST}"]
    result = normalize_environment(raw, env_vars)
    assert result == {"DB_HOST": "shared-db"}


def test_load_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DB_HOST=shared-db\nDB_NAME=orders\n# comment\n", encoding="utf-8")
    result = load_env_file(env_file)
    assert result == {"DB_HOST": "shared-db", "DB_NAME": "orders"}


def test_load_env_file_missing(tmp_path: Path):
    missing = tmp_path / ".env.nonexistent"
    result = load_env_file(missing)
    assert result == {}


def test_parse_with_env_file(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """
services:
  orders:
    image: orders:latest
    environment:
      DB_HOST: ${DB_HOST}
      DB_NAME: ${DB_NAME}
""",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("DB_HOST=shared-db\nDB_NAME=orders\n", encoding="utf-8")

    project = parse_compose_file(compose, env_file)
    assert project.services["orders"].environment == {"DB_HOST": "shared-db", "DB_NAME": "orders"}


def test_parse_with_env_file_unresolved_preserved(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """
services:
  orders:
    image: orders:latest
    environment:
      DB_HOST: ${DB_HOST}
""",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    project = parse_compose_file(compose, env_file)
    assert project.services["orders"].environment == {"DB_HOST": "${DB_HOST}"}


# ---------------------------------------------------------------------------
# 5. Named volume parsing
# ---------------------------------------------------------------------------

def test_named_volume_parsing():
    vol = normalize_volume("shared-data:/data")
    assert vol.source == "shared-data"
    assert vol.target == "/data"
    assert vol.type == "named"
    assert vol.read_only is False


def test_named_volume_with_ro():
    vol = normalize_volume("shared-data:/data:ro")
    assert vol.source == "shared-data"
    assert vol.target == "/data"
    assert vol.type == "named"
    assert vol.read_only is True


def test_bind_mount_parsing():
    vol = normalize_volume("./src:/app")
    assert vol.source == "./src"
    assert vol.target == "/app"
    assert vol.type == "bind"


def test_anonymous_volume_parsing():
    vol = normalize_volume("/data")
    assert vol.source is None
    assert vol.target == "/data"
    assert vol.type == "anonymous"


def test_volume_long_syntax_named():
    vol = normalize_volume({"type": "volume", "source": "shared-data", "target": "/data"})
    assert vol.source == "shared-data"
    assert vol.target == "/data"
    assert vol.type == "named"


def test_volume_long_syntax_bind():
    vol = normalize_volume({"type": "bind", "source": "./src", "target": "/app", "read_only": True})
    assert vol.type == "bind"
    assert vol.read_only is True


def test_normalize_volumes_empty():
    assert normalize_volumes(None) == []
    assert normalize_volumes([]) == []


# ---------------------------------------------------------------------------
# 6. Multiple services
# ---------------------------------------------------------------------------

def test_multiple_services():
    yaml_text = """
services:
  orders:
    image: orders:latest
    environment:
      DB_HOST: shared-db
  reports:
    image: reports:latest
    environment:
      DB_HOST: shared-db
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: orders
"""
    project = parse_compose_string(yaml_text)
    assert set(project.services.keys()) == {"orders", "reports", "db"}
    assert project.services["orders"].environment["DB_HOST"] == "shared-db"
    assert project.services["reports"].environment["DB_HOST"] == "shared-db"
    assert project.services["db"].environment["POSTGRES_DB"] == "orders"


def test_multiple_services_with_volumes():
    yaml_text = """
services:
  orders:
    volumes: ["shared-data:/data"]
  reports:
    volumes: ["shared-data:/data"]
volumes:
  shared-data:
"""
    project = parse_compose_string(yaml_text)
    assert len(project.services["orders"].volumes) == 1
    assert len(project.services["reports"].volumes) == 1
    assert project.services["orders"].volumes[0].source == "shared-data"
    assert project.services["reports"].volumes[0].source == "shared-data"


# ---------------------------------------------------------------------------
# 7. Missing optional env/volume sections
# ---------------------------------------------------------------------------

def test_missing_environment_and_volumes():
    yaml_text = """
services:
  orders:
    image: orders:latest
  reports:
    image: reports:latest
"""
    project = parse_compose_string(yaml_text)
    assert project.services["orders"].environment == {}
    assert project.services["orders"].volumes == []
    assert project.services["reports"].environment == {}
    assert project.services["reports"].volumes == []


def test_service_with_no_data():
    yaml_text = """
services:
  orders:
"""
    project = parse_compose_string(yaml_text)
    assert project.services["orders"].environment == {}
    assert project.services["orders"].volumes == []


def test_empty_services():
    yaml_text = """
services: {}
"""
    project = parse_compose_string(yaml_text)
    assert project.services == {}


# ---------------------------------------------------------------------------
# 8. Stage 1 fixtures — facts only, no dependency inference
# ---------------------------------------------------------------------------

def test_fixture_shared_env():
    # Only check that parser extracts facts; do NOT detect dependency here
    project = parse_compose_file("fixtures/shared_env/docker-compose.yml")
    assert "orders" in project.services
    assert "reports" in project.services

    orders_env = project.services["orders"].environment
    reports_env = project.services["reports"].environment

    assert orders_env.get("DB_HOST") == "shared-db"
    assert orders_env.get("DB_NAME") == "orders"
    assert reports_env.get("DB_HOST") == "shared-db"
    assert reports_env.get("DB_NAME") == "orders"

    # Also check db service exists but has different key
    assert "db" in project.services
    assert project.services["db"].environment.get("POSTGRES_DB") == "orders"

    # Deterministic check — same file produces same dict
    project2 = parse_compose_file("fixtures/shared_env/docker-compose.yml")
    assert project.to_dict() == project2.to_dict()


def test_fixture_shared_volume():
    project = parse_compose_file("fixtures/shared_volume/docker-compose.yml")
    assert "orders" in project.services
    assert "reports" in project.services

    for svc_name in ("orders", "reports"):
        vols = project.services[svc_name].volumes
        assert len(vols) == 1
        v = vols[0]
        assert v.source == "shared-data"
        assert v.target == "/data"
        assert v.type == "named"

    # Deterministic
    project2 = parse_compose_file("fixtures/shared_volume/docker-compose.yml")
    assert project.to_dict() == project2.to_dict()


def test_fixture_near_miss():
    project = parse_compose_file("fixtures/near_miss/docker-compose.yml")
    assert "orders" in project.services
    assert "reports" in project.services

    orders_port = project.services["orders"].environment.get("PORT")
    reports_port = project.services["reports"].environment.get("PORT")

    assert orders_port == "8000"
    assert reports_port == "9000"
    # Same name but different values — parser only records fact

    # Verify no volumes leak into near_miss
    assert project.services["orders"].volumes == []
    assert project.services["reports"].volumes == []

    # Deterministic
    project2 = parse_compose_file("fixtures/near_miss/docker-compose.yml")
    assert project.to_dict() == project2.to_dict()


# ---------------------------------------------------------------------------
# Additional: determinism across string parse
# ---------------------------------------------------------------------------

def test_deterministic_normalization():
    yaml_text = """
services:
  a:
    environment:
      - FOO=bar
      - BAZ
    volumes:
      - shared-data:/data:ro
  b:
    environment:
      FOO: bar
      BAZ:
    volumes:
      - type: volume
        source: shared-data
        target: /data
"""
    p1 = parse_compose_string(yaml_text)
    p2 = parse_compose_string(yaml_text)
    assert p1.to_dict() == p2.to_dict()
    # Environment without value => None, not ""
    assert p1.services["a"].environment["BAZ"] is None
    assert p1.services["b"].environment["BAZ"] is None
