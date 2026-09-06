# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-09-06 (Prompt 2: Resource-Centric Aggregation)
**Branch:** `main` — working tree: Stages 1–7 **DONE** + Tier 1 Redesign **DONE** + Prompt 2 **DONE** (grouped resource-centric); Tier 2 (Kubernetes) next
**Status:** `Tier 1 COMPLETE + REDESIGN + GROUPED` — Stages 1–7 **DONE** (parser + discovery + filtering + **bounded resolution** + **aggregation by normalized_identity** + **LLM Judge grouped 1/group** + **CouplingModel** + **Graph from groups** + **Grouped Report** + **CLI**) — Tier 1 is demoable; Cal.com 6 obs → 1 group → 1 finding → 1 node +3 edges; Tier 2 next

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC (hybrid spec) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence with `internal/external_confirmed/partial/unresolved` + identity `exact/config/unknown`, §4 one call/candidate, confidence mandatory, §6 React Flow DATA + normalized_identity dedup) + provider-agnostic |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 540 LOC + `discovery.py` 132 LOC + `resolution.py` 607 LOC + `aggregation.py` 200 LOC (group by normalized_identity) + `coupling.py` 150 LOC + `filtering.py` 530 LOC + `judge.py` 900 LOC (grouped prompt/cache) + `model.py` 265 LOC + `graph.py` 350 LOC + `report.py` 400 LOC (grouped) + `cli.py` |
| **Fixtures** | 3 messy fixtures — invariants preserved |
| **Tests** | **92 passed** (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14) |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed for Prompt 2 grouped 2026-09-06 |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` + `out/` / `report.json` / `report.md` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py:45` `Service.image`, `parser.py:488` image capture, `parser.py:397` multi-file, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py:20` `Candidate` with `value`, pairwise env + `named_volume` only, sorted |
| 3 | **Filtering + Resolution + Aggregation** | `Done` ⬅ **PROMPT 2** | `resolution.py:1` `ResolutionResult` + `bounded_resolve:270` + `aggregation.py:1` `aggregate_evidence_packages` (group by `normalized_identity` primary, fallback `raw:resource:value` for unknown, deterministic, preserves `services[]`/`configuration_evidence`/`unresolved_vars`/`chain`) — Cal.com 6 obs → 1 group |
| 4 | **LLM Judge (Grouped)** | `Done` | `judge.py:96` `build_grouped_judge_prompt` (resource identity/protocol/status/strength + services + config by service) + `judge_grouped_package:cache` + `0+1/group` (not per pair), cache key `grouping_key/services/config/unresolved`, `GEMINI`/`OPENROUTER` + failsafe |
| 5 | **Coupling Model** | `Done` ⬅ **PROMPT 2** | `coupling.py:1` `CouplingGroup{grouping_key, resource_identity, protocol, status, strength, services[], config_evidence, verdict, confidence, reason, _model(hidden), cache_key}` + `CouplingModel{groups, meaningful_only()}` — one per shared resource, Graph+Report consume same |
| 6 | **Graph (Grouped)** | `Done` | `graph.py:76` `_resource_key` + `build_graph_from_groups:150` (one node per group `resource:env_var:postgresql|...`, one edge per service in group) — Cal.com 1 node +3 edges, deterministic, provider hidden |
| 7 | **Report (Grouped)** | `Done` | `report.py:GroupedReportFinding` + `build_grouped_report` (title `Shared PostgreSQL Database Configuration`, Summary `services_analyzed/resource_groups/observations/meaningful_groups`, conclusion→evidence→technical details, no `generic_variable` in body) |

**Overall Tier 1:** **100% (code) + redesign** — Stages 1–7 done + bounded chain/identity redesign — Tier 1 is demoable; **Tier 2 (Kubernetes) is next — this is the whole point**
**Tier 2 (Kubernetes):** `Next` — ConfigMap/Secret/shared-volume detection via same pipeline (YAML parsing, workload normalization)

---

## 3. Repo Structure (Actual 2026-09-06 Prompt 2)

```
Blindspot/
├── AGENTS.md (522), PROJECT_PLAN.md (301), STATE.md, DECISIONS.md, HANDOFF.md
├── .gitignore (allows fixtures/**/.env, ignores cache.json + .env + out/)
├── .env (GEMINI_API_KEY + OPENROUTER_API_KEY, gitignored)
├── fixtures/ (shared_env, shared_volume, near_miss) + out/ per repo (report.json/md, graph.json)
├── src/blindspot/
│   ├── __init__.py (exports all stages + grouped)
│   ├── parser.py (540 LOC)
│   ├── discovery.py (132 LOC)
│   ├── resolution.py (607 LOC) — bounded chain + normalize
│   ├── aggregation.py (200 LOC) — group by normalized_identity
│   ├── coupling.py (150 LOC) — CouplingGroup/Model
│   ├── filtering.py (530 LOC) — states + identity
│   ├── judge.py (900 LOC, grouped prompt/cache)
│   ├── model.py (265 LOC)
│   ├── graph.py (350 LOC, build_graph + build_graph_from_groups)
│   ├── report.py (400 LOC, grouped human-readable)
│   └── cli.py (grouped pipeline)
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    ├── test_filtering.py (8)
    ├── test_graph.py (13)
    ├── test_resolution.py (17)
    └── test_grouping.py (14) — resource-centric aggregation
```

**Validation & Next:**
- Tested on 3 synthetic fixtures (shared_env 2 meaningful `unresolved config` 0.75, shared_volume 1 internal, near_miss 0) + any real repo via `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` (Windows, absolute path quoted; use `.venv\Scripts\python` if `python` is system python) or `PYTHONPATH=src .venv/Scripts/python -m blindspot.cli /path/to/repo --out out` (bash) → `out/<repo>/report.json+report.md+graph.json`
- **Tier 2 NEXT:** Kubernetes manifests (ConfigMap/Secret/volumes) → same filtering → Judge → Model → Graph → Report pipeline

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai==0.8.0`, `openai==1.102.0`
- **LLM Providers:** Gemini 3.7-flash / 3.1-flash-lite (google-genai) + Nemotron 3 Ultra 550B (OpenRouter via openai SDK) — provider-agnostic, prompt not tied to Gemini
- **Resolution:** `resolution.py` — bounded `MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup from `Compose/.env/env_file`, protocols `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss`, credentials stripped, `service|name` vs `postgresql|host|port|db`
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Thinking:** low 1024 / medium 4096 / high 8192 → OpenRouter max_tokens 512/1024/2048, dynamically via `set_thinking_level()`
- **Windows:** Must use `.venv\Scripts\python` (not system `python`) else `ModuleNotFoundError: No module named 'yaml'` — `PyYAML` lives in venv.

---

## 5. Development Priorities — Tier 1 Done + Redesign Done, Tier 2 Next (Whole Point)

1. Messy fixtures — **DONE**
2. Config parser — **DONE**
3. Candidate discovery — **DONE**
4. Candidate filtering — **DONE**
5. Bounded evidence + resolution redesign (states, chain, identity) — **DONE 2026-09-06**
6. LLM judgment layer + verdict cache (`cache.json` with normalized keys) — **DONE**
7. Dependency model (model hidden) — **DONE**
8. Resource-based graph (normalized dedup) — **DONE**
9. Report generation (chain + identity) — **DONE**
10. CLI one-command testing on one or more repos — **DONE**
11. Validation on synthetic + real repos — **DONE** (Tier 1 demoable)
12. **Tier 2 Kubernetes (ConfigMap/Secret/volumes, same pipeline) — NEXT — this is the whole point**

---

## 6. Recent Activity

- 2026-09-06: **Prompt 2 — Resource-Centric Aggregation, Grouped LLM, Graph/Report Redesign DONE** — `aggregation.py:1` `GroupedEvidencePackage` + `aggregate_evidence_packages` (normalized primary, Unknown not over-merged) + `coupling.py:1` `CouplingGroup/Model` (one per shared resource, services[] + config_evidence + verdict/confidence) + `judge.py` `build_grouped_judge_prompt` + `judge_grouped_packages` (0+1/group, cache on grouped key) + `graph.py` `build_graph_from_groups` (one node per group, one edge per service) + `report.py` `GroupedReportData` (Summary services_analyzed/resource_groups/observations/meaningful_groups, title `Shared PostgreSQL Database Configuration`, conclusion→evidence→technical, no `generic_variable` in body) + `cli.py` grouped pipeline; Cal.com 6 obs →1 group (3 svcs, 2 vars) →1 LLM →1 finding →1 node+3 edges, fixtures 2 groups, 92 tests pass.
- 2026-09-06: **Tier 1 Redesign — Bounded Resolution + Resource Identity DONE** — `resolution.py:1` etc., 78 tests pass.
- 2026-09-04: **Stage 7 Report COMPLETE** + CLI `build_report` findings+summary
- 2026-09-04: **Stage 6 Resource Graph (DATA) COMPLETE** — bipartite `Service ↔ Resource`
- 2026-09-04: **Stage 5 Dependency Model COMPLETE** — `to_dict` hides `_model`

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
