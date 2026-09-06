"""Tests for bounded resolution + identity normalization (Tier 1 redesign)."""

from blindspot.parser import parse_compose_string, parse_compose_file
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages, EvidencePackage
from blindspot.resolution import bounded_resolve, MAX_RESOLUTION_DEPTH


def test_chain_resolution_via_lookup():
    yaml = """
services:
  calcom:
    environment:
      DATABASE_DIRECT_URL: ${DATABASE_URL}
      DATABASE_URL: postgresql://user:pass@database:5432/calcom
  calcom-api:
    environment:
      DATABASE_DIRECT_URL: ${DATABASE_URL}
      DATABASE_URL: postgresql://user:pass@database:5432/calcom
  database:
    image: postgres:15
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    # DATABASE_DIRECT_URL should resolve via chain to internal postgres
    pkg = next(p for p in pkgs if p.resource == "DATABASE_DIRECT_URL")
    assert pkg.resolution_status == "internal"
    assert pkg.normalized_identity == "postgresql|database|5432|calcom"
    assert pkg.identity_strength == "exact"
    assert len(pkg.resolution_chain) >= 1
    assert pkg.final_value == "postgresql://user:pass@database:5432/calcom"
    assert pkg.resolved_service == "database"
    # chain should contain DATABASE_URL
    assert any(step["variable"] == "DATABASE_URL" for step in pkg.resolution_chain)


def test_external_confirmed_without_compose_service():
    yaml = """
services:
  a:
    environment:
      DATABASE_URL: postgresql://prod-db.company.com:5432/app
  b:
    environment:
      DATABASE_URL: postgresql://prod-db.company.com:5432/app
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resolution_status == "external_confirmed"
    assert pkg.resource_protocol == "postgresql"
    assert pkg.normalized_identity == "postgresql|prod-db.company.com|5432|app"
    assert pkg.identity_strength == "exact"
    assert pkg.resolved_service is None


def test_normalized_identity_strips_credentials():
    yaml = """
services:
  a:
    environment:
      DATABASE_URL: postgresql://user1:secret1@database:5432/calcom
  b:
    environment:
      DATABASE_URL: postgresql://user2:secret2@database:5432/calcom
  database:
    image: postgres:15
"""
    proj = parse_compose_string(yaml)
    cands = discover_candidates(proj)
    # discovery sees different values, but build_evidence_packages should keep because normalized same
    pkgs = build_evidence_packages(cands, proj)
    assert len(pkgs) == 1
    pkg = pkgs[0]
    # Both raw values differ but normalized same
    assert pkg.normalized_identity == "postgresql|database|5432|calcom"
    assert pkg.resolution_status == "internal"


def test_unresolved_stays_unresolved_not_external():
    yaml = """
services:
  a:
    environment:
      DB_HOST: shared-db
  b:
    environment:
      DB_HOST: shared-db
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    # shared-db not a compose service, not a URI -> unresolved, not external
    assert pkg.resolution_status == "unresolved"
    assert pkg.normalized_identity is None
    assert pkg.identity_strength == "config"  # same config template


def test_partial_identity_unresolved_host():
    yaml = """
services:
  a:
    environment:
      DATABASE_URL: postgresql://${HOST}/mydb
  b:
    environment:
      DATABASE_URL: postgresql://${HOST}/mydb
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resolution_status == "partial"
    assert "HOST" in pkg.unresolved_vars
    assert pkg.resource_protocol == "postgresql"
    assert pkg.identity_strength == "config"


def test_cycle_detection():
    yaml = """
services:
  a:
    environment:
      A: ${B}
      B: ${C}
      C: ${A}
  b:
    environment:
      A: ${B}
      B: ${C}
      C: ${A}
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    for pkg in pkgs:
        # Each should be cyclic/unresolved
        assert pkg.is_cyclic is True or pkg.resolution_status == "unresolved"
        assert pkg.final_value is not None


def test_max_depth_bounded():
    # Build 12-step chain, max depth 10
    env_lines = "\n".join([f"      V{i}: ${{V{i+1}}}" for i in range(1, 12)]) + "\n      V12: final"
    yaml = f"""
services:
  a:
    environment:
{env_lines}
  b:
    environment:
      V1: ${{V2}}
"""
    proj = parse_compose_string(yaml)
    rr = bounded_resolve("${V1}", proj, "a", "b", resource="V1")
    assert rr.depth_reached == MAX_RESOLUTION_DEPTH
    assert rr.depth_reached <= MAX_RESOLUTION_DEPTH
    assert len(rr.chain) <= MAX_RESOLUTION_DEPTH


def test_internal_plain_host():
    yaml = """
services:
  app1:
    environment:
      DB_HOST: postgres
  app2:
    environment:
      DB_HOST: postgres
  postgres:
    image: postgres:15
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resolution_status == "internal"
    assert pkg.resolved_service == "postgres"
    assert pkg.normalized_identity == "service|postgres"


def test_db_name_not_internal_false_positive():
    yaml = """
services:
  orders:
    image: orders:latest
    environment:
      DB_NAME: orders
  reports:
    environment:
      DB_NAME: orders
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    # DB_NAME=orders should NOT resolve to orders service as host
    assert pkg.resolution_status != "internal" or pkg.resolved_service != "orders"
    # Should be unresolved/config, not internal
    assert pkg.resolution_status == "unresolved"
    assert pkg.resolved_service is None


def test_unknown_protocol_not_invented():
    proj = parse_compose_string("""
services:
  a:
    environment:
      CUSTOM_RESOURCE: abc://internal-system/production
  b:
    environment:
      CUSTOM_RESOURCE: abc://internal-system/production
""")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resource_protocol is None
    assert pkg.normalized_identity is None
    assert pkg.resolution_status == "unresolved"
    # But same raw value still kept
    assert pkg.value == "abc://internal-system/production"


def test_mysql_normalization():
    proj = parse_compose_string("""
services:
  a:
    environment:
      DATABASE_URL: mysql://user:pass@mysql-host:3306/mydb
  b:
    environment:
      DATABASE_URL: mysql://user:pass@mysql-host:3306/mydb
""")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resource_protocol == "mysql"
    assert pkg.normalized_identity == "mysql|mysql-host|3306|mydb"
    assert pkg.resolution_status == "external_confirmed"


def test_redis_normalization():
    proj = parse_compose_string("""
services:
  a:
    environment:
      REDIS_URL: redis://redis:6379/0
  b:
    environment:
      REDIS_URL: redis://redis:6379/0
  redis:
    image: redis:7
""")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resource_protocol == "redis"
    # host redis is internal service
    assert pkg.resolution_status == "internal"
    assert pkg.normalized_identity is not None and "redis" in pkg.normalized_identity


def test_mongodb_normalization():
    proj = parse_compose_string("""
services:
  a:
    environment:
      MONGO_URL: mongodb://user:pass@mongo:27017/mydb
  b:
    environment:
      MONGO_URL: mongodb://user:pass@mongo:27017/mydb
""")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    assert pkg.resource_protocol == "mongodb"
    assert pkg.normalized_identity == "mongodb|mongo|27017|mydb"


def test_deterministic_ordering():
    yaml = """
services:
  b:
    environment:
      FOO: bar
  a:
    environment:
      FOO: bar
"""
    proj = parse_compose_string(yaml)
    pkgs1 = build_evidence_packages(discover_candidates(proj), proj)
    pkgs2 = build_evidence_packages(discover_candidates(proj), proj)
    assert pkgs1[0].to_dict() == pkgs2[0].to_dict()


def test_cache_key_includes_normalized_identity():
    proj = parse_compose_string("""
services:
  a:
    environment:
      DATABASE_URL: postgresql://host1:5432/db
  b:
    environment:
      DATABASE_URL: postgresql://host1:5432/db
""")
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    key = pkgs[0].cache_key_dict()
    assert "normalized_identity" in key
    assert "resolution_status" in key
    assert "final_value" in key


def test_interpolation_default_fallback():
    yaml = """
services:
  a:
    environment:
      FOO: ${MISSING:-fallback}
  b:
    environment:
      FOO: ${MISSING:-fallback}
"""
    proj = parse_compose_string(yaml)
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    pkg = pkgs[0]
    # Should resolve default
    assert pkg.final_value == "fallback"
    # No unresolved
    assert pkg.unresolved_vars == ()


def test_same_config_vs_exact_identity():
    # Template with unresolved host -> config identity
    proj_partial = parse_compose_string("""
services:
  a:
    environment:
      DATABASE_URL: postgresql://${HOST}/mydb
  b:
    environment:
      DATABASE_URL: postgresql://${HOST}/mydb
""")
    pkg_partial = build_evidence_packages(discover_candidates(proj_partial), proj_partial)[0]
    assert pkg_partial.identity_strength == "config"
    assert pkg_partial.resolution_status == "partial"

    # Fully resolved -> exact
    proj_exact = parse_compose_string("""
services:
  a:
    environment:
      DATABASE_URL: postgresql://myhost:5432/mydb
  b:
    environment:
      DATABASE_URL: postgresql://myhost:5432/mydb
""")
    pkg_exact = build_evidence_packages(discover_candidates(proj_exact), proj_exact)[0]
    assert pkg_exact.identity_strength == "exact"
    assert pkg_exact.resolution_status == "external_confirmed"
