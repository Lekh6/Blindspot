"""Audit regression tests — Tier 1 loose-end closure.

Covers:
  F1: Windows drive-letter bind mounts must not parse as named volume "C".
  F2: Judge prompts must use the schema verdict token `uncertain`, not
      bare "insufficient", for the cannot-decide option.
  F3: Judge cache behaviour (hit reuse, key sensitivity, failsafe paths),
      model validation, report serialization, graph bipartite property.
All tests are hermetic (no network, no API keys).
"""

import json

from blindspot.aggregation import aggregate_evidence_packages
from blindspot.coupling import CouplingGroup, CouplingModel
from blindspot.discovery import discover_candidates
from blindspot.filtering import build_evidence_packages
from blindspot.graph import build_graph_from_groups
from blindspot.judge import (
    GeminiJudgeClient,
    JudgeResult,
    OpenRouterJudgeClient,
    _cache_key_for_grouped,
    _cache_key_for_package,
    build_grouped_judge_prompt,
    build_judge_prompt,
    judge_evidence_package,
    judge_evidence_packages,
    judge_grouped_package,
    judge_grouped_packages,
    validate_judge_result,
)
from blindspot.model import Dependency, DependencyModel
from blindspot.parser import normalize_volume, parse_compose_string
from blindspot.report import build_grouped_report


def _two_svc_db_yaml():
    return """
services:
  a: { environment: { DATABASE_URL: postgresql://host:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://host:5432/db } }
"""


def _grouped_one():
    proj = parse_compose_string(_two_svc_db_yaml())
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    groups = aggregate_evidence_packages(pkgs)
    assert len(groups) == 1
    return groups[0]


def _package_one():
    proj = parse_compose_string(_two_svc_db_yaml())
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    assert len(pkgs) == 1
    return pkgs[0]


# ---------------------------------------------------------------------------
# F1: Windows drive-letter bind mounts
# ---------------------------------------------------------------------------

def test_windows_bind_backslash_is_bind_not_named():
    vol = normalize_volume("C:\\hostpath:/data", {})
    assert vol.type == "bind"
    assert vol.source == "C:\\hostpath"
    assert vol.target == "/data"
    assert vol.read_only is False


def test_windows_bind_forward_slash_with_ro():
    vol = normalize_volume("C:/hostpath:/data:ro", {})
    assert vol.type == "bind"
    assert vol.source == "C:/hostpath"
    assert vol.target == "/data"
    assert vol.read_only is True


def test_windows_binds_do_not_create_shared_C_candidate():
    yaml = """
services:
  a:
    volumes: ['C:\\data-a:/data']
  b:
    volumes: ['C:\\data-b:/data']
"""
    proj = parse_compose_string(yaml)
    assert all(v.type == "bind" for svc in proj.services.values() for v in svc.volumes)
    assert discover_candidates(proj) == []


def test_shared_windows_bind_is_ignored_like_other_binds():
    yaml = """
services:
  a:
    volumes: ['C:\\shared:/data']
  b:
    volumes: ['C:\\shared:/data']
"""
    proj = parse_compose_string(yaml)
    # Consistent with existing policy: bind mounts never produce candidates
    assert discover_candidates(proj) == []


def test_interpolated_windows_drive_path_is_bind():
    vol = normalize_volume("${D}:/data", {"D": "C:\\x"})
    assert vol.type == "bind"
    assert vol.source == "C:\\x"


def test_named_volume_unaffected_by_drive_fix():
    vol = normalize_volume("shared-data:/data", {})
    assert (vol.source, vol.target, vol.type) == ("shared-data", "/data", "named")


# ---------------------------------------------------------------------------
# F2: Prompt wording matches verdict schema
# ---------------------------------------------------------------------------

def test_pairwise_prompt_uses_uncertain_token():
    prompt = build_judge_prompt(_package_one())
    assert "uncertain" in prompt
    assert "3. insufficient" not in prompt
    assert '"meaningful" | "coincidental" | "uncertain"' in prompt


def test_grouped_prompt_uses_uncertain_token():
    prompt = build_grouped_judge_prompt(_grouped_one())
    assert "uncertain" in prompt
    assert "3. insufficient" not in prompt
    assert '"meaningful" | "coincidental" | "uncertain"' in prompt


def test_bare_insufficient_verdict_is_rejected():
    try:
        validate_judge_result(
            JudgeResult(verdict="insufficient", confidence=0.5, reason="x", model="t")
        )
    except ValueError:
        return
    raise AssertionError("bare 'insufficient' verdict must be rejected by schema")


# ---------------------------------------------------------------------------
# F3: Judge cache behaviour (hermetic fake clients)
# ---------------------------------------------------------------------------

class _FakeGroupedClient:
    def __init__(self):
        self.calls = 0
        self.model = "fake-grouped"

    @property
    def model_name(self):
        return self.model

    def judge_grouped(self, grouped):
        self.calls += 1
        return JudgeResult(
            verdict="meaningful", confidence=0.9,
            reason="fake grouped judgment", model=self.model,
        )


class _FakePackageClient:
    def __init__(self):
        self.calls = 0
        self.model = "fake-package"

    @property
    def model_name(self):
        return self.model

    def judge(self, package):
        self.calls += 1
        return JudgeResult(
            verdict="meaningful", confidence=0.85,
            reason="fake package judgment", model=self.model,
        )


def test_grouped_cache_hit_reuses_without_recall(tmp_path):
    cache = tmp_path / "cache.json"
    client = _FakeGroupedClient()
    grouped = _grouped_one()
    first = judge_grouped_package(grouped, client, cache_path=cache)
    assert client.calls == 1
    second = judge_grouped_package(grouped, client, cache_path=cache)
    assert client.calls == 1  # cache hit: no second LLM call
    assert (second.verdict, second.confidence) == (first.verdict, first.confidence)


def test_grouped_cache_key_changes_with_evidence():
    g1 = _grouped_one()
    proj = parse_compose_string(
        """
services:
  a: { environment: { DATABASE_URL: postgresql://other:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://other:5432/db } }
"""
    )
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    g2 = aggregate_evidence_packages(pkgs)[0]
    assert _cache_key_for_grouped(g1) != _cache_key_for_grouped(g2)


def test_pairwise_cache_hit_reuses_without_recall(tmp_path):
    cache = tmp_path / "cache.json"
    client = _FakePackageClient()
    pkg = _package_one()
    judge_evidence_package(pkg, client, cache_path=cache)
    assert client.calls == 1
    judge_evidence_package(pkg, client, cache_path=cache)
    assert client.calls == 1


def test_pairwise_cache_key_changes_with_value():
    p1 = _package_one()
    proj = parse_compose_string(
        """
services:
  a: { environment: { DATABASE_URL: postgresql://other:5432/db } }
  b: { environment: { DATABASE_URL: postgresql://other:5432/db } }
"""
    )
    p2 = build_evidence_packages(discover_candidates(proj), proj)[0]
    assert _cache_key_for_package(p1) != _cache_key_for_package(p2)


def test_judge_without_cache_path_still_works():
    pkg = _package_one()
    res = judge_evidence_package(pkg, _FakePackageClient(), cache_path=None)
    assert res.verdict == "meaningful"


def test_invalid_client_result_raises_not_cached(tmp_path):
    class _BadClient:
        @property
        def model_name(self):
            return "bad"

        def judge_grouped(self, grouped):
            return JudgeResult(verdict="bogus", confidence=9.9, reason="", model="bad")

    try:
        judge_grouped_package(_grouped_one(), _BadClient(), cache_path=tmp_path / "c.json")
    except ValueError:
        return
    raise AssertionError("invalid JudgeResult must raise instead of being stored")


def test_missing_api_key_failsafe_without_network(monkeypatch):
    for var in ("OPENROUTER_API_KEY", "OR_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    pkg = _package_one()
    for client in (GeminiJudgeClient(), OpenRouterJudgeClient()):
        res = client.judge(pkg)
        assert res.verdict == "uncertain"
        assert 0.0 <= res.confidence <= 1.0
        assert res.reason.strip()


def test_deterministic_pairs_shape():
    from blindspot.cli import _deterministic_pairs

    grouped = [_grouped_one()]
    pairs = _deterministic_pairs(grouped)
    assert len(pairs) == 1
    g, jr = pairs[0]
    assert jr.verdict == "uncertain" and jr.confidence == 0.0
    model = CouplingModel.from_grouped_judgments(pairs)
    assert len(model.groups) == 1


# ---------------------------------------------------------------------------
# Model validation + report serialization + graph shape
# ---------------------------------------------------------------------------

def test_coupling_group_rejects_bad_verdict_and_confidence():
    grouped = _grouped_one()
    good = JudgeResult(verdict="meaningful", confidence=0.9, reason="ok", model="t")
    CouplingGroup.from_grouped_judgment(grouped, good)  # must not raise
    for bad in (
        JudgeResult(verdict="bogus", confidence=0.5, reason="ok", model="t"),
        JudgeResult(verdict="meaningful", confidence=1.5, reason="ok", model="t"),
        JudgeResult(verdict="meaningful", confidence=0.5, reason="  ", model="t"),
    ):
        try:
            CouplingGroup.from_grouped_judgment(grouped, bad)
        except ValueError:
            continue
        raise AssertionError(f"invalid judgment accepted: {bad!r}")


def test_dependency_model_hides_provider():
    pkg = _package_one()
    dep = Dependency.from_evidence_judgment(
        pkg, JudgeResult(verdict="meaningful", confidence=0.9, reason="ok", model="secret-model")
    )
    assert "secret-model" not in json.dumps(dep.to_dict())
    model = DependencyModel.from_judgments([(pkg, JudgeResult(
        verdict="meaningful", confidence=0.9, reason="ok", model="secret-model"))])
    assert len(model.meaningful_only()) == 1


def test_grouped_report_json_round_trip_and_graph_bipartite():
    grouped = _grouped_one()
    pairs = [(grouped, JudgeResult(verdict="meaningful", confidence=0.9, reason="ok", model="t"))]
    model = CouplingModel.from_grouped_judgments(pairs)
    graph = build_graph_from_groups(model)
    report = build_grouped_report(model, graph_data=graph, total_services=2)
    parsed = json.loads(report.to_json())  # must be JSON-serializable
    assert parsed["summary"]["meaningful_groups"] == 1
    assert len(parsed["findings"]) == 1
    for edge in graph["edges"]:
        assert not (edge["source"].startswith("service:") and edge["target"].startswith("service:"))
        assert edge["target"].startswith("resource:")
    md = report.to_markdown()
    assert "Meaningful implicit coupling" in md
    assert "0.90" in md


def test_judge_packages_batch_sorted_and_cached(tmp_path):
    proj = parse_compose_string(
        """
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
    )
    pkgs = build_evidence_packages(discover_candidates(proj), proj)
    assert len(pkgs) == 2
    client = _FakePackageClient()
    cache = tmp_path / "cache.json"
    out = judge_evidence_packages(pkgs, client, cache_path=cache)
    assert client.calls == 2
    out2 = judge_evidence_packages(pkgs, client, cache_path=cache)
    assert client.calls == 2  # all cache hits on second pass
    assert [p.resource for p, _ in out2] == sorted(p.resource for p, _ in out2)
