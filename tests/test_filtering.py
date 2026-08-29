"""Stage 3 Tests: Candidate Filtering

Conservative heuristics: generic keys (PORT/DEBUG/LOG_LEVEL etc) and
same-key-different-values should be dropped before LLM.
"""

from blindspot.parser import parse_compose_file, parse_compose_string
from blindspot.discovery import discover_candidates
from blindspot.filtering import filter_candidates, filter_with_reasons


def test_filtering_shared_env_keeps_real():
    proj = parse_compose_file("fixtures/shared_env/docker-compose.yml")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    # DB_HOST and DB_NAME should survive
    resources = {(c.resource, c.value) for c in kept}
    assert ("DB_HOST", "shared-db") in resources
    assert ("DB_NAME", "orders") in resources
    # SHARED_EXTRA is generic noise → filtered
    assert not any(c.resource == "SHARED_EXTRA" for c in kept)
    assert len([c for c in kept if c.resource_type == "env_var"]) == 2
    # Evidence enriched with filter reason
    assert all("filter: kept" in c.evidence for c in kept)


def test_filtering_shared_volume_keeps_named_volume():
    proj = parse_compose_file("fixtures/shared_volume/docker-compose.yml")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    # shared-data volume should survive
    assert any(c.resource == "shared-data" and c.resource_type == "named_volume" for c in kept)
    # DATA_PATH is generic → filtered
    assert not any(c.resource == "DATA_PATH" for c in kept)
    assert len(kept) == 1


def test_filtering_near_miss_drops_all():
    proj = parse_compose_file("fixtures/near_miss/docker-compose.yml")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    # PORT (different values) + APP_ENV + SHARED_NOISE all generic/dropped
    assert len(kept) == 0
    # Verify reasons
    annotated = {c.resource: reason for c, keep, reason in filter_with_reasons(cands) if not keep}
    assert "PORT" in annotated and "different values" in annotated["PORT"]
    assert "APP_ENV" in annotated


def test_filtering_same_key_different_values_dropped():
    proj = parse_compose_string("""
services:
  a:
    environment: {PORT: 8000}
  b:
    environment: {PORT: 9000}
""")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    assert len(kept) == 0


def test_filtering_same_key_same_value_kept_if_specific():
    proj = parse_compose_string("""
services:
  a:
    environment: {DB_HOST: shared-db}
  b:
    environment: {DB_HOST: shared-db}
""")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    assert len(kept) == 1
    assert kept[0].resource == "DB_HOST" and kept[0].value == "shared-db"


def test_filtering_generic_keys_dropped():
    for key in ["PORT", "DEBUG", "LOG_LEVEL", "APP_ENV"]:
        proj = parse_compose_string(f"""
services:
  a:
    environment: {{{key}: foo}}
  b:
    environment: {{{key}: foo}}
""")
        cands = discover_candidates(proj)
        kept = filter_candidates(cands)
        assert len(kept) == 0, f"{key} should be filtered"


def test_filtering_named_volume_always_kept():
    proj = parse_compose_string("""
services:
  a:
    volumes: ["my-vol:/data"]
  b:
    volumes: ["my-vol:/data"]
""")
    cands = discover_candidates(proj)
    kept = filter_candidates(cands)
    assert len(kept) == 1
    assert kept[0].resource == "my-vol"


def test_filtering_bind_volume_never_candidate():
    proj = parse_compose_string("""
services:
  a:
    volumes: ["./src:/app"]
  b:
    volumes: ["./src:/app"]
""")
    cands = discover_candidates(proj)
    assert len(cands) == 0
    kept = filter_candidates(cands)
    assert len(kept) == 0
