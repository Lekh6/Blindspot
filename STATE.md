# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-10-29 (Unified Stage 6/7 + Frontend verified)
**Branch:** `main` — working tree: Tier 1 + unified explicit/hidden graph/report + React Flow frontend + local API server; 174 tests green (verified 2026-10-29); Kubernetes out of scope
**Status:** `STAGE 6/7 UNIFIED + FRONTEND DONE` — Stage 6 now emits explicit `depends_on` as `service → service` (`classification: explicit`, no confidence/LLM decision) plus potential hidden `service → resource` edges (`potential_hidden`/`uncertain`/`rejected`) with decision summaries. Stage 7 separates explicit relationships from hidden findings. `frontend/` is a Vite + React + TS Obsidian-style graph explorer backed by `api/server.py`. Verification 2026-10-29: `pytest` 174 passed; `npm run typecheck` clean; `npm run build` clean; API endpoints (`/api/runs`, `/api/run`, `POST /api/analyze`) exercised live. Browser-level interaction (click/panel/minimap) is implemented but not yet verified in a live browser session. Next: real-world validation and evidence-based fixes. Findings remain potential coupling with evidence + confidence

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 530+ LOC + `PROJECT_PLAN.md` 310+ LOC (hybrid spec + D-044) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence with `internal/external_confirmed/partial/unresolved` + identity `exact/config/unknown`, §4 one call/candidate, confidence mandatory, §6 React Flow DATA + normalized_identity dedup) + provider-agnostic + D-044 L0/L1 discovery |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` (Service.image/depends_on/source_file, Project.sources, multi-file merge) + `inputs.py` 119 LOC (4 YAML + 2 JSON adapters) + `discovery.py` 387 LOC (L0/L1) + `filtering.py` 875 LOC + `resolution.py` 607 LOC + `aggregation.py` 266 LOC + `context.py` 551 LOC + `context_judge.py` 426 LOC + `judge.py` 1394 LOC (contextual primary) + `coupling.py` 232 LOC + `decision.py` 602 LOC + `model.py` 285 LOC + `graph.py` 691 LOC (unified explicit + hidden edges) + `report.py` 996 LOC (explicit relationships + hidden findings + decisions) + `cli.py` ~920 LOC + `secrets.py` + `run.py`/`run.bat`/`run.sh` + `start_ui.py`/`start_ui.bat`/`start_ui.sh` (one-click UI launcher) + `api/server.py` (runs listing/load + analyze trigger, serves `frontend/dist`) + `frontend/` (Vite + React 19 + TS + `@xyflow/react`) |
| **Fixtures** | 4 fixture dirs: `shared_env`, `shared_volume`, `near_miss`, `stage12_levels` (L0 + cross-var endpoint + generic + unresolved + missing target) |
| **Tests** | **174 passed** (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14 + `test_accounting` 6 + `test_audit` 21 + `test_stage12` 12 + `test_decision` 18 + `test_stage34` 18 + `test_unified_graph` 7) — hermetic, no network; verified 2026-10-29 |
| **Dev env** | `.venv` rebuilt 2026-09-28 (Python 3.12.10) + `requirements.txt` + pytest; `python run.py --help` verified; frontend `node_modules` installed, `npm run typecheck` + `npm run build` verified 2026-10-29 |
| **Docs** | `STATE.md`/`HANDOFF.md`/`README.md` refreshed 2026-10-29 (unified Stage 6/7 + frontend); D-044 records Stage 1+2, D-045 records Stage 4/5, D-046 records frontend + stdlib API + one-click launcher |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` + `out/` / `report.json` / `report.md` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py` + `inputs.py` adapter: 4 YAML + 2 JSON, `Service.image/depends_on/source_file`, `Project.sources`, multi-file merge, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py`: `Candidate` with `candidate_id/level/relationship_type/origin/resource_identity/provenance`; L0 `depends_on` + L1 `shared_env`/`shared_volume`/`shared_endpoint` (cross-var identity), deterministic dedup/sort |
| 3 | **Filtering + Resolution + Aggregation** | `Done` | `resolution.py` `bounded_resolve` + `aggregation.py` `aggregate_evidence_packages` (group by `normalized_identity`) — L0 fast-path `internal/unresolved` + endpoints `internal/external_confirmed` |
| 4 | **LLM Judge (Contextual)** | `Done` | `context.py` bounded investigation contexts + `context_judge.py` validation/cache + `judge.py` `judge_contextual` (one call per context, per-candidate verdicts); grouped judge retained as fallback |
| 5 | **Coupling + Decision Model** | `Done` | `coupling.py` `CouplingGroup`/`CouplingModel` (one per shared resource) + `decision.py` `DecisionRecord`/`DecisionModel` (deterministic policy → `potential_dependency`/`insufficient_evidence`/`review`, processing status, versioned policy) |
| 6 | **Graph (Unified)** | `Done` | `graph.py` `build_graph_from_groups`: L0 `depends_on` as **direct `service → service` edges** (`classification: explicit`, `semantics: startup_dependency`, no confidence/decision) + L1 couplings as `service → resource` edges (`potential_hidden`/`uncertain`/`rejected`, decision summaries on nodes, confidence on hidden edges, model hidden) — `decisions=` param added |
| 7 | **Report (Unified)** | `Done` | `report.py` `build_grouped_report(decisions=…)`: `explicit_relationships[]` separate from `findings[]` (hidden only); findings carry `classification`, `decisions`, decision summary; Markdown renders "Explicitly configured relationships" + "Stage 5 decision" sections |

**Overall:** **Stages 1–7 complete (unified Stage 6/7) + React Flow frontend.** Findings are potential shared-resource coupling signals, not runtime proof (D-038).
**Kubernetes:** out of scope — no adapter, fixture, dependency, or design work. Focus is Compose-only detection quality.

---

## 3. Repo Structure (Actual 2026-10-12 D-044)

```
Blindspot/
├── AGENTS.md (530+), PROJECT_PLAN.md (310+), STATE.md, DECISIONS.md, HANDOFF.md
├── README.md (First Time Setup vs Running — general purpose, with Input Formats & Dependency Levels)
├── run.py / run.bat / run.sh (simple launchers — no PYTHONPATH needed)
├── start_ui.py / start_ui.bat / start_ui.sh (one-click UI launcher: API + frontend + browser; Ctrl+C stops all; --build serves dist via API only)
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
│   ├── graph.py (691 LOC, build_graph + build_graph_from_groups + unified explicit/hidden edges)
│   ├── report.py (996 LOC, grouped + accounting + explicit relationships + hidden findings + decision rendering)
│   ├── cli.py (~920 LOC, input source tracking + full accounting + separate Services/Candidates)
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
    ├── test_stage12.py (12) — input adapters + L0/L1 acceptance
    ├── test_decision.py (18) — Stage 5 decision policy/schema
    ├── test_stage34.py (18) — Stage 3/4 contexts, validation, cache, contextual judging
    └── test_unified_graph.py (7) — unified Stage 6/7: explicit vs hidden edges, decision metadata, determinism
├── api/
│   └── server.py — local run server (127.0.0.1:8765): `/api/runs`, `/api/run?id=`, `POST /api/analyze` (wraps CLI), serves `frontend/dist` static hosting
└── frontend/
    ├── src/App.tsx (tabs + run list + selection + URL params), api.ts, types.ts (typed against backend contract)
    ├── src/graph/layout.ts (dagre LR layout, classification → edge styling), src/components/{GraphView,FlowNodes,DetailsPanel,AnalyzeTab}.tsx
    ├── src/styles.css (~1200 LOC Obsidian-style dark theme), vite.config.ts (proxy `/api` → 127.0.0.1:8765), dist/ (prebuilt)
```

**Validation & Next:**
- Tested on 4 synthetic fixtures + `celery-docker-example` (5 services, 0 candidates) + `tmp_calcom2` (3 services, 6 raw → 6 obs → 1 group) + `docker` (Cal.com-like, 5 services, 6→6→1→1). `174 tests pass` (verified 2026-10-29).
- Frontend verification 2026-10-29: `npm run typecheck` clean, `npm run build` clean (bundle byte-identical to existing `dist/`), live API round-trip (`/api/runs` → `/api/run` → `POST /api/analyze` on a synthetic 3-service repo → run served, smoke artifacts removed), and dev-mode integration verified (`npm run dev` serves the app; `/api` proxy forwards to the API server). NOT yet verified: interactive browser session (node/edge clicks, details panel behavior, minimap) — implemented but not visually proven.
- **NEXT: real-world multi-repo validation** (precision/recall + ground truth) and a browser-level frontend walkthrough; then evidence-based fixes only.

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai==0.8.0`, `openai==1.102.0`
- **LLM Providers:** Gemini 3.7-flash / 3.1-flash-lite (google-genai) + Nemotron 3 Ultra 550B (OpenRouter via openai SDK) — provider-agnostic, prompt not tied to Gemini. If no key, CLI prompts Yes/No every run; No → deterministic-only (no LLM, `uncertain 0.0`, JSONs only, report.md banner).
- **Resolution:** `resolution.py` — bounded `MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup from `Compose/.env/env_file`, protocols `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss`, credentials stripped, `service|name` vs `postgresql|host|port|db`
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Startup:** `python run.py` / `run.bat` / `run.sh` (handles `PYTHONPATH` + venv) — simple for any user; first-time setup includes `python -m venv .venv && pip install -r requirements.txt`. UI: `start_ui.bat` / `start_ui.sh` / `python start_ui.py` one-click launcher (API + dev server + browser; `--build` serves `frontend/dist` via the API only).
- **Thinking:** low 1024 / medium 4096 / high 8192 → OpenRouter max_tokens 512/1024/2048, dynamically via `set_thinking_level()`; CLI accepts only `low/medium/high` (default `low`)
- **Windows:** Venv required (`ModuleNotFoundError: No module named 'yaml'` if using system `python`) — `run.bat` auto-uses `.venv`; `run.py` also auto-relaunches via `subprocess.call` preserving console for `input()`.
- **Frontend:** Vite 6 + React 19 + TypeScript 5.7, `@xyflow/react` 12.8 (React Flow), `@dagrejs/dagre` 1.1 (layout), `lucide-react` (icons); Node via `npm run dev`/`npm run typecheck`/`npm run build`; Vite dev proxy forwards `/api` → `127.0.0.1:8765` (`api/server.py`, no external dependencies — stdlib `http.server`).

---

## 5. Development Priorities — Validation Next

1. Messy fixtures — **DONE**
2. Config parser — **DONE**
3. Candidate discovery — **DONE (+ D-044 L0/L1)**
4. Candidate filtering + bounded evidence/resolution — **DONE**
5. Resource aggregation — **DONE**
6. LLM judgment (contextual, cached, validated) — **DONE (Stage 4 enhanced)**
7. Coupling + Decision model — **DONE (Stage 5 enhanced: `CouplingModel` + `DecisionModel`)**
8. Stage 6 Graph enhancement — **DONE (unified explicit + hidden edges, decision summaries; 7 tests)**
9. Stage 7 Report enhancement — **DONE (explicit relationships separated from hidden findings; decisions rendered)**
10. React Flow frontend + local API server — **DONE (verified: typecheck/build/pytest/API round-trip 2026-10-29; browser walkthrough pending)**
11. Validation on multiple real Compose repos + ground truth — **NEXT** (precision/recall where defensible, LLM consistency)
12. Browser-level frontend verification walkthrough — pending (implemented but not visually verified)
13. Kubernetes — **out of scope** (no adapter, fixture, dependency, or design work)

---

## 6. Recent Activity

- 2026-10-29: **Unified Stage 6/7 + Frontend recovered, documented, and verified** — graph.py now emits explicit `depends_on` as direct `service → service` edges (grey, no confidence/decision) alongside `service → resource` hidden-coupling edges (yellow `potential_hidden` / dashed `uncertain` / dotted hidden-by-default `rejected`) with per-node decision summaries; report separates `explicit_relationships` from hidden `findings` with Stage 5 decision cards. Added `tests/test_unified_graph.py` (7 tests). New `frontend/` (Vite + React 19 + TS + `@xyflow/react` + dagre + lucide): Obsidian-style dark theme, graph default tab with run sidebar, clickable nodes/edges → details panel (evidence, confidence bars, resolution chains, decisions), Analyze tab (local path → CLI via `POST /api/analyze`), URL params `?run=/?select=/?view=`. New `api/server.py` (stdlib HTTP, `/api/runs`, `/api/run`, `POST /api/analyze`, serves `frontend/dist`). New one-click launcher `start_ui.py` / `start_ui.bat` / `start_ui.sh` (API + dev server + browser auto-open, first-run `npm install`, process-tree cleanup on exit; `--build` mode verified serving `frontend/dist` via the API only; dev mode verified through the launcher). Verification: `pytest` 174 passed; `npm run typecheck` clean; `npm run build` clean; API round-trip exercised live with a synthetic repo. Docs updated (README frontend section + Graph DATA contract bullets; STATE/HANDOFF reconciled). Unverified: in-browser interaction walkthrough. Next: real-world validation.

- 2026-10-28: **Stage 4 + Stage 5 Enhancement DONE (docs refreshed)** — Stage 4's primary path is now contextual multi-candidate judgment: `context.py` builds bounded `InvestigationContext` sections, `context_judge.py` validates per-candidate JSON (`CandidateJudgment`/`JudgmentFailure`), caches per-context, and `judge.py` `judge_contextual` packs/splits deterministically (one LLM call per context, not per pair). Stage 5 now persists both resource-centric `CouplingGroup`/`CouplingModel` and per-candidate `DecisionRecord`/`DecisionModel` (deterministic policy `stage5-v1`, `potential_dependency`/`insufficient_evidence`/`review`, `ProcessingStatus`, versioned schema). CLI wires `judge_contextual` → `CouplingModel.from_contextual_judgments` → `build_decision_model` and reports decision counts in accounting. Tests `167 passed` (new `test_decision.py` 18, `test_stage34.py` 18). Kubernetes removed from the roadmap.

- 2026-10-12: **D-044 Stage 1+2 Enhancement DONE** — additive-only enhancement on `main` preserving D-042 baseline (119→131 green, hermetic). Stage 1 (`inputs.py` new, `parser.py`/`cli.py` adapted): `Input format → adapter → canonical Project → pipeline`. `SUPPORTED_COMPOSE_FILENAMES` = 4 YAML + `docker-compose.json`/`compose.json` (equivalent model, shared `_parse_services`, no separate discovery). Canonical `Service` gains `depends_on` (list/mapping/string normalized, sorted) + `source_file`; `Project` gains `sources`. Multi-file merge unions `depends_on`/`sources`. Unresolved `${VAR}` still preserved, never invented. CLI delegates discovery/find to `inputs` (superset behavior, same determinism). K8s/Terraform explicitly not built. Stage 2 (`discovery.py` extended, `filtering.py` fast-paths only): `Candidate` gains `candidate_id` (sha256-16, order-independent), `level` (L0/L1), `relationship_type` (`explicit_dependency`/`shared_env`/`shared_volume`/`shared_endpoint`), `origin`, `resource_identity`, `provenance` — all defaulted/backfilled so old constructions keep working. New sources: L0 `depends_on` (directional, missing targets kept unresolved) + L1 `shared_endpoint` (same normalized `protocol|host|port|db` via different var names, e.g. `DATABASE_URL` vs `DB_URL`; skips pairs already covered same-key and skips unknown/unresolved). Generic names alone never create a resource dependency; dedup by `(level,type,resource,value,pair)` keeps distinct resources separate; sort stable. Downstream already passed unknown types through conservatively; added explicit resolve/decide fast-paths so L0 reports `internal/unresolved` + `service|target` and endpoints report `internal/external_confirmed` + exact identity. Graph stays bipartite (L0 as `resource:service_dependency:*` nodes, never service→service). Tests: `fixtures/stage12_levels/` (L0 + cross-var endpoint + generic + unresolved + missing target) + `tests/test_stage12.py` (12 acceptance tests, hermetic). Also fixed pre-existing committed merge markers in `tests/test_accounting.py` (kept hermetic Case F) that blocked collection.

- 2026-09-28: **Tier 1 Audit + Loose-End Closure DONE (D-042)** — full stage-by-stage audit (docs vs implementation vs tests); baseline 98 passed. Fixed F1 Windows drive-letter binds (`C:\data:/app` was parsed as named volume `C` → false shared-volume candidate; now `bind` with full source, `parser.py` `_WINDOWS_DRIVE_RE` + `_is_bind_source`), F2 judge prompts listed option 3 as bare `insufficient` while schema requires `uncertain` (both pairwise + grouped prompts fixed), F4 test hermeticity (`conftest.py` autouse API-key env snapshot/restore + Case F key-block: `run_one_repo` tests previously loaded the real repo `.env` and could make live LLM calls — suite took 20s with network; now 0.35s, no network). Added `tests/test_audit.py` (21 tests: Windows volumes, prompt wording, judge cache hit/reuse/key-sensitivity/failsafe, model validation, report round-trip, graph bipartite). Rebuilt broken `.venv` (Python 3.12.10) and verified `python run.py --help`. E2E re-verified deterministic on 3 fixtures + `tmp_calcom2` (3 svc → 6 obs → 1 group). Observation (not a defect): live-keyed fixture runs judged `uncertain` where README shows `meaningful` — LLM variance, needs Workstream B/C consistency review, no code change.

- 2026-09-28: **Deepening direction set (D-043, provisional — no `src/` changes)** — L0→L1→L2 taxonomy (+visible/hidden label, L3/L4 out), AI as micro-verifier of bounded snippet tasks, one prompt per resource group (map + compose slice + bounded tree + ID-tagged questions, JSON-array response), weighted deterministic combiner → `strong/likely/possible/no-evidence` bands, pointer chains per finding. Sequenced plan (taxonomy → value discovery → table extractor → verifier/combiner → layered graph/report) only after Tier 1 validation.

- 2026-09-27: **Tier 1 Frozen + Tier 2 Proposal-First Reframe DONE (docs only, no `src/` changes)** — `MISSION.md` rewritten (potential-coupling mission, frozen Tier 1, central-but-gated K8s, optional source, evidence tiers `configuration-confirmed/statically inferred/runtime-observed`, guiding principle); `DECISIONS.md` D-038 (freeze + honest claims) / D-039 (K8s proposal: same-key-under-different-names gap, cross-namespace ConfigMap-key + Secret-key + Service-DNS example, objects/evidence, source optional, pipeline flow, `fixtures/k8s_schema_share/` PoC ground truth, non-claims) / D-040 (selective source + tiers); `STATE.md`/`HANDOFF.md`/`AGENTS.md`/`PROJECT_PLAN.md` Tier 2 switched from "implement next" to "proposal approval required". Contradictions resolved: same-DB YAML parsing insufficient, AST-exclusion vs selective source, stretch-vs-central K8s, secret-value guardrail, read-only API preference.

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code