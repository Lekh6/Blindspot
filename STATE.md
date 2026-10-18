# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-10-12 (D-044 Stage 1+2 Enhancement)
**Branch:** `main` — working tree: Tier 1 **FROZEN** (Stages 1–7 done, audited, 131 tests green) + D-044 Stage 1+2 enhancement done (input adapters + L0/L1 discovery) + Tier 2 **PROPOSAL ONLY** (D-039, no implementation)
**Status:** `TIER 1 AUDITED + D-044 ENHANCEMENT` — audit complete (Workstream A done); D-044 adds input adapters (4 YAML + 2 JSON), L0 `depends_on`, L1 cross-variable shared-endpoint identity, multi-file merge; tests: 131 passed (119 existing + 12 new `test_stage12.py`). Next: Workstream B multi-repo validation + ground truth, then evidence-based fixes. After validation: deepen toward L2 (table) per D-043 (directional, not final). Kubernetes/source-runtime deferred; evidence tiers + honest claims required

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 530+ LOC + `PROJECT_PLAN.md` 310+ LOC (hybrid spec + D-044) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence with `internal/external_confirmed/partial/unresolved` + identity `exact/config/unknown`, §4 one call/candidate, confidence mandatory, §6 React Flow DATA + normalized_identity dedup) + provider-agnostic + D-044 L0/L1 discovery |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` (Service.image/depends_on/source_file, Project.sources, multi-file merge) + `inputs.py` 119 LOC (adapter boundary: `SUPPORTED_COMPOSE_FILENAMES` 4 YAML + 2 JSON, `load_compose_document`, `discover/find_compose_file`) + `discovery.py` 387 LOC (Candidate `candidate_id/level/relationship_type/origin/resource_identity/provenance`; L0 `depends_on` + L1 `shared_env`/`shared_volume`/`shared_endpoint`) + `filtering.py` 875 LOC + `resolution.py` 607 LOC + `aggregation.py` 200 LOC + `coupling.py` 150 LOC + `judge.py` 1050 LOC + `model.py` 265 LOC + `graph.py` 350 LOC + `report.py` 550 LOC + `cli.py` ~750 LOC + `context.py` + `context_judge.py` + `decision.py` + `secrets.py` + `run.py`/`run.bat`/`run.sh` |
| **Fixtures** | 4 fixture dirs: `shared_env`, `shared_volume`, `near_miss`, `stage12_levels` (L0 + cross-var endpoint + generic + unresolved + missing target) |
| **Tests** | **131 passed** (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14 + `test_accounting` 6 + `test_audit` 21 + `test_stage12` 12) — hermetic, no network |
| **Dev env** | `.venv` rebuilt 2026-09-28 (Python 3.12.10) + `requirements.txt` + pytest; `python run.py --help` verified |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed 2026-10-12 (D-044: input adapters, L0/L1, multi-file merge, 12 new tests) |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` + `out/` / `report.json` / `report.md` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py` + `inputs.py` adapter: 4 YAML + 2 JSON, `Service.image/depends_on/source_file`, `Project.sources`, multi-file merge, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py`: `Candidate` with `candidate_id/level/relationship_type/origin/resource_identity/provenance`; L0 `depends_on` + L1 `shared_env`/`shared_volume`/`shared_endpoint` (cross-var identity), deterministic dedup/sort |
| 3 | **Filtering + Resolution + Aggregation** | `Done` | `resolution.py` `bounded_resolve` + `aggregation.py` `aggregate_evidence_packages` (group by `normalized_identity`) — L0 fast-path `internal/unresolved` + endpoints `internal/external_confirmed` |
| 4 | **LLM Judge (Grouped)** | `Done` | `judge.py` `build_grouped_judge_prompt` + `judge_grouped_packages` `0+1/group`, cache `groups_judged` vs `llm_calls`/`cache_hits` accounting |
| 5 | **Coupling Model** | `Done` | `coupling.py` `CouplingGroup` — one per shared resource, Graph+Report consume same |
| 6 | **Graph (Grouped)** | `Done` | `graph.py` `_resource_key` + `build_graph_from_groups` — L0 as `resource:service_dependency:*` nodes, bipartite |
| 7 | **Report (Grouped)** | `Done` | `report.py` `GroupedReportData` `application`/`inputs`/`analysis` + `Analysis input`/`Pipeline summary` + zero-result explanations |

**Overall Tier 1:** **100% (code) + D-044 enhancement — FROZEN** (change only for concrete bugs/validation). Findings are potential shared-resource coupling signals, not runtime proof (D-038).
**Tier 2 (Kubernetes):** `PROPOSAL ONLY — NO IMPLEMENTATION` — D-039 defines the approval gate: K8s must demonstrate key-level/indirect coupling Tier 1 cannot find (same ConfigMap/Secret key under different env names, cross-namespace, Service DNS → Endpoints). Mere same-database YAML parsing is not a sufficient differentiator. Read-only API preferred; secret values never exposed; eBPF/tracing out of scope.

---

## 3. Repo Structure (Actual 2026-10-12 D-044)

```
Blindspot/
├── AGENTS.md (530+), PROJECT_PLAN.md (310+), STATE.md, DECISIONS.md, HANDOFF.md
├── README.md (First Time Setup vs Running — general purpose, with Input Formats & Dependency Levels)
├── run.py / run.bat / run.sh (simple launchers — no PYTHONPATH needed)
├── .gitignore (allows fixtures/**/.env, ignores cache.json + .env + out/)
├── .env (API key, gitignored — created via prompt if missing)
├── fixtures/ (shared_env, shared_volume, near_miss, stage12_levels) + out/ per repo (report.json/md, graph.json)
├── src/blindspot/
│   ├── __init__.py (exports all stages + grouped)
│   ├── inputs.py (119 LOC, adapter boundary: SUPPORTED_COMPOSE_FILENAMES 4 YAML + 2 JSON, load_compose_document, discover/find_compose_file)
│   ├── parser.py (540+ LOC + YAML/UTF-8 + env_file warnings + count_named_volumes; Service.image/depends_on/source_file; Project.sources; YAML+JSON share _parse_services)
│   ├── discovery.py (387 LOC, Candidate{candidate_id/level/relationship_type/origin/resource_identity/provenance}; L0 depends_on + L1 shared_env/shared_volume/shared_endpoint)
│   ├── resolution.py (607 LOC) — bounded chain + normalize
│   ├── aggregation.py (200 LOC) — group by normalized_identity + truncation warn
│   ├── coupling.py (150 LOC) — CouplingGroup/Model
│   ├── filtering.py (875 LOC) — states + identity + L0/endpoint fast-paths
│   ├── judge.py (1050 LOC, grouped prompt/cache + balanced JSON + atomic cache)
│   ├── model.py (265 LOC)
│   ├── graph.py (350 LOC, build_graph + build_graph_from_groups)
│   ├── report.py (550 LOC, grouped + accounting application/inputs/analysis + Analysis input/Pipeline summary)
│   ├── cli.py (~750 LOC, input source tracking + full accounting + separate Services/Candidates)
│   ├── context.py, context_judge.py, decision.py, secrets.py
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    ├── test_filtering.py (8)
    ├── test_graph.py (13)
    ├── test_resolution.py (17)
    ├── test_grouping.py (14) — resource-centric aggregation
    ├── test_accounting.py (6) — Cases A-F
    ├── test_audit.py (21)
    └── test_stage12.py (12) — input adapters + L0/L1 acceptance
```

**Validation & Next:**
- Tested on 4 synthetic fixtures + `celery-docker-example` (5 services, 0 candidates) + `tmp_calcom2` (3 services, 6 raw → 6 obs → 1 group) + `docker` (Cal.com-like, 5 services, 6→6→1→1). `131 tests pass` (verified 2026-10-12).
- **NEXT (D-041/D-042): Workstream B multi-repo validation** — run `python run.py` against 2–3 real OSS Compose repos; per-repo candidates/findings/TP-FP review + ground-truth set; then evidence-based fixes only. Tier 1 stays frozen except demonstrated fixes.

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai==0.8.0`, `openai==1.102.0`
- **LLM Providers:** Gemini 3.7-flash / 3.1-flash-lite (google-genai) + Nemotron 3 Ultra 550B (OpenRouter via openai SDK) — provider-agnostic, prompt not tied to Gemini. If no key, CLI prompts Yes/No every run; No → deterministic-only (no LLM, `uncertain 0.0`, JSONs only, report.md banner).
- **Resolution:** `resolution.py` — bounded `MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup from `Compose/.env/env_file`, protocols `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss`, credentials stripped, `service|name` vs `postgresql|host|port|db`
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Startup:** `python run.py` / `run.bat` / `run.sh` (handles `PYTHONPATH` + venv) — simple for any user; first-time setup includes `python -m venv .venv && pip install -r requirements.txt`.
- **Thinking:** low 1024 / medium 4096 / high 8192 → OpenRouter max_tokens 512/1024/2048, dynamically via `set_thinking_level()`; CLI accepts only `low/medium/high` (default `low`)
- **Windows:** Venv required (`ModuleNotFoundError: No module named 'yaml'` if using system `python`) — `run.bat` auto-uses `.venv`; `run.py` also auto-relaunches via `subprocess.call` preserving console for `input()`.

---

## 5. Development Priorities — Tier 1 Frozen, Tier 2 Proposal-Gated

1. Messy fixtures — **DONE**
2. Config parser — **DONE (FROZEN)**
3. Candidate discovery — **DONE (FROZEN + D-044 L0/L1)**
4. Candidate filtering — **DONE (FROZEN)**
5. Bounded evidence + resolution redesign (states, chain, identity) — **DONE 2026-09-06 (FROZEN)**
6. LLM judgment layer + verdict cache (`cache.json` with normalized keys) — **DONE (FROZEN)**
7. Dependency model (model hidden) — **DONE (FROZEN)**
8. Resource-based graph (normalized dedup) — **DONE (FROZEN)**
9. Report generation (chain + identity) — **DONE (FROZEN)**
10. CLI one-command testing on one or more repos — **DONE (FROZEN)**
11. Validation on synthetic + real repos — **DONE** (Tier 1 demoable)
12. **Tier 2 Kubernetes — PROPOSAL ONLY (D-039): review differentiator + PoC scope BEFORE any implementation. No adapter, dependency, or Tier 1 redesign until approved.**

---

## 6. Recent Activity

- 2026-10-12: **D-044 Stage 1+2 Enhancement DONE** — additive-only enhancement on `main` preserving D-042 baseline (119→131 green, hermetic). Stage 1 (`inputs.py` new, `parser.py`/`cli.py` adapted): `Input format → adapter → canonical Project → pipeline`. `SUPPORTED_COMPOSE_FILENAMES` = 4 YAML + `docker-compose.json`/`compose.json` (equivalent model, shared `_parse_services`, no separate discovery). Canonical `Service` gains `depends_on` (list/mapping/string normalized, sorted) + `source_file`; `Project` gains `sources`. Multi-file merge unions `depends_on`/`sources`. Unresolved `${VAR}` still preserved, never invented. CLI delegates discovery/find to `inputs` (superset behavior, same determinism). K8s/Terraform explicitly not built. Stage 2 (`discovery.py` extended, `filtering.py` fast-paths only): `Candidate` gains `candidate_id` (sha256-16, order-independent), `level` (L0/L1), `relationship_type` (`explicit_dependency`/`shared_env`/`shared_volume`/`shared_endpoint`), `origin`, `resource_identity`, `provenance` — all defaulted/backfilled so old constructions keep working. New sources: L0 `depends_on` (directional, missing targets kept unresolved) + L1 `shared_endpoint` (same normalized `protocol|host|port|db` via different var names, e.g. `DATABASE_URL` vs `DB_URL`; skips pairs already covered same-key and skips unknown/unresolved). Generic names alone never create a resource dependency; dedup by `(level,type,resource,value,pair)` keeps distinct resources separate; sort stable. Downstream already passed unknown types through conservatively; added explicit resolve/decide fast-paths so L0 reports `internal/unresolved` + `service|target` and endpoints report `internal/external_confirmed` + exact identity. Graph stays bipartite (L0 as `resource:service_dependency:*` nodes, never service→service). Tests: `fixtures/stage12_levels/` (L0 + cross-var endpoint + generic + unresolved + missing target) + `tests/test_stage12.py` (12 acceptance tests, hermetic). Also fixed pre-existing committed merge markers in `tests/test_accounting.py` (kept hermetic Case F) that blocked collection.

- 2026-09-28: **Tier 1 Audit + Loose-End Closure DONE (D-042)** — full stage-by-stage audit (docs vs implementation vs tests); baseline 98 passed. Fixed F1 Windows drive-letter binds (`C:\data:/app` was parsed as named volume `C` → false shared-volume candidate; now `bind` with full source, `parser.py` `_WINDOWS_DRIVE_RE` + `_is_bind_source`), F2 judge prompts listed option 3 as bare `insufficient` while schema requires `uncertain` (both pairwise + grouped prompts fixed), F4 test hermeticity (`conftest.py` autouse API-key env snapshot/restore + Case F key-block: `run_one_repo` tests previously loaded the real repo `.env` and could make live LLM calls — suite took 20s with network; now 0.35s, no network). Added `tests/test_audit.py` (21 tests: Windows volumes, prompt wording, judge cache hit/reuse/key-sensitivity/failsafe, model validation, report round-trip, graph bipartite). Rebuilt broken `.venv` (Python 3.12.10) and verified `python run.py --help`. E2E re-verified deterministic on 3 fixtures + `tmp_calcom2` (3 svc → 6 obs → 1 group). Observation (not a defect): live-keyed fixture runs judged `uncertain` where README shows `meaningful` — LLM variance, needs Workstream B/C consistency review, no code change.

- 2026-09-28: **Deepening direction set (D-043, provisional — no `src/` changes)** — L0→L1→L2 taxonomy (+visible/hidden label, L3/L4 out), AI as micro-verifier of bounded snippet tasks, one prompt per resource group (map + compose slice + bounded tree + ID-tagged questions, JSON-array response), weighted deterministic combiner → `strong/likely/possible/no-evidence` bands, pointer chains per finding. Sequenced plan (taxonomy → value discovery → table extractor → verifier/combiner → layered graph/report) only after Tier 1 validation.

- 2026-09-27: **Tier 1 Frozen + Tier 2 Proposal-First Reframe DONE (docs only, no `src/` changes)** — `MISSION.md` rewritten (potential-coupling mission, frozen Tier 1, central-but-gated K8s, optional source, evidence tiers `configuration-confirmed/statically inferred/runtime-observed`, guiding principle); `DECISIONS.md` D-038 (freeze + honest claims) / D-039 (K8s proposal: same-key-under-different-names gap, cross-namespace ConfigMap-key + Secret-key + Service-DNS example, objects/evidence, source optional, pipeline flow, `fixtures/k8s_schema_share/` PoC ground truth, non-claims) / D-040 (selective source + tiers); `STATE.md`/`HANDOFF.md`/`AGENTS.md`/`PROJECT_PLAN.md` Tier 2 switched from "implement next" to "proposal approval required". Contradictions resolved: same-DB YAML parsing insufficient, AST-exclusion vs selective source, stretch-vs-central K8s, secret-value guardrail, read-only API preference.

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code