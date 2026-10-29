# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.

**Last Updated:** 2026-10-29 (Unified Stage 6/7 + Frontend verified)
**Current Phase:** **VALIDATION** — Stages 1–7 are complete (unified Stage 6/7: explicit `depends_on` as `service → service` edges + hidden `service → resource` couplings; Report separates explicit relationships from hidden findings and renders Stage 5 decisions). The React Flow frontend (`frontend/`) + local API (`api/server.py`) are implemented and verified at the typecheck/build/pytest/API level; browser-level interaction walkthrough pending. Tests: **174 green** (verified 2026-10-29). Next: real-world multi-repo validation (precision/recall, ground truth), then evidence-based fixes. Kubernetes is out of scope (no adapter/fixture/design work).
**Current Branch:** `main` — working tree: Tier 1 Stages 1–7 + unified Stage 6/7 + D-044/D-045 + frontend + local API, 174 tests, all uncommitted

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence with `internal/external_confirmed/partial/unresolved`, §3b aggregation by `normalized_identity`, §4 one call/candidate, §5 Coupling/Decision model, §6 Graph from groups) + `PROJECT_PLAN.md` + `STATE.md` §2, then this file.
2. **Stages 1–7 + frontend DONE:** `inputs.py` 119 LOC (4 YAML + 2 JSON adapters), `parser.py` 540+ LOC, `discovery.py` 387 LOC (L0 `depends_on` + L1 `shared_env`/`shared_volume`/`shared_endpoint`), `resolution.py` 607 LOC, `aggregation.py` 266 LOC, `filtering.py` 875 LOC, `context.py` 551 LOC, `context_judge.py` 426 LOC, `judge.py` 1394 LOC (`judge_contextual` is the primary path), `coupling.py` 232 LOC (`CouplingGroup`/`CouplingModel`), `decision.py` 602 LOC (`DecisionRecord`/`DecisionModel`, policy `stage5-v1`), `graph.py` 691 LOC (unified explicit + hidden edges), `report.py` 996 LOC (explicit relationships + hidden findings + decisions), `cli.py` ~920 LOC. Plus `api/server.py` (local run server + analyze trigger + static hosting for `frontend/dist`) and `frontend/` (Vite + React 19 + TS + `@xyflow/react` + dagre + lucide). **174 tests pass** (32+8+8+13+17+14+6+21+12+18+18+7 `test_unified_graph.py`), verified 2026-10-29.
3. **Full pipeline now:** `inputs.load_compose_document` → `parse_compose_file` → `discover_candidates` → `build_evidence_packages` → `aggregate_evidence_packages` → API-key check (prompt Yes/No; No → deterministic-only) → `judge_contextual` (one call per bounded investigation context) → `CouplingModel.from_contextual_judgments` + `build_decision_model` → `build_graph_from_groups(decisions=…)` → `build_grouped_report(accounting, decisions=…)`. Outputs: versioned `report.json` (`application`/`inputs`/`analysis` + `explicit_relationships` + `findings` with `classification`/`decisions`), `report.md`, `graph.json`, `report.log.json`. Frontend: `python api/server.py` + `cd frontend && npm run dev` (proxy `/api` → 127.0.0.1:8765) or `npm run build` + serve via the API at http://127.0.0.1:8765.
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-044 Stage 1+2, D-045 Stage 4/5), `HANDOFF.md`, `README.md` (frontend section).
5. `.env` gitignored, `!fixtures/**/.env` allowed, `cache.json` ignored; `node_modules/` + `frontend/dist/` added to `.gitignore`. **Any user:** first-time `python -m venv .venv && pip install -r requirements.txt` (+ `cd frontend && npm install` for the UI), then `python run.py` (prompts path + `low/medium/high` + API key Yes/No). Advanced `python run.py "C:\path\to\repo" --thinking low` still works. **UI:** `start_ui.bat` (Windows) / `bash start_ui.sh` one-click launcher (API + dev server + browser; `--build` serves dist via the API only).

---

## 2. Where We Left Off

- `AGENTS.md` 530+ LOC + `PROJECT_PLAN.md` 310+ LOC hybrid spec (plus D-044 notes).
- **Inputs/Parser:** `inputs.py:1` `SUPPORTED_COMPOSE_FILENAMES` (4 YAML + 2 JSON), `load_compose_document`, `discover_compose_files`, `find_compose_file`. `parser.py:46` `Service.image/depends_on/source_file`, `parser.py:72` `Project.sources`, `parser.py:105` `normalize_depends_on`, `parser.py:488`/`505` image capture, `parser.py:397` multi-file merge (env override, volumes union, `depends_on` union, image latest-wins, sources unioned).
- **Discovery (D-044):** `discovery.py:77` `Candidate` with `candidate_id/level/relationship_type/origin/resource_identity/provenance`. `discovery.py:162` `_discover_shared_env` (L1 `shared_env`), `discovery.py:210` `_discover_shared_volumes` (L1 `shared_volume`), `discovery.py:249` `_discover_explicit_dependencies` (L0 `depends_on`, directional, unresolved kept), `discovery.py:289` `_discover_shared_endpoints` (L1 cross-var identity, `bounded_resolve`, skips same-key/unknown). `discovery.py:360` `discover_candidates` dedup by `(level,type,resource,value,pair)`, stable sort.
- **Resolution:** `resolution.py:1` `ResolutionResult/Step` + `bounded_resolve:270` (lookup from `Compose/.env/env_file`, while `${VAR}` with cycle/depth, `MAX_RESOLUTION_DEPTH=10`, `_normalize_connection_identity` for `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss` stripping creds, `internal` only if host-like or URI host matches service, `external_confirmed/partial/unresolved`, `exact/config/unknown` via `host|port|db`). `D-029`.
- **Filtering (D-044 fast-paths):** `filtering.py:68` `EvidencePackage` extended with `resolution_status/normalized_identity/resource_protocol/identity_strength/chain/final_value/unresolved_vars/is_cyclic/depth` + `_decide_with_project:386` + `build_evidence_packages:420` (enriched `filter: kept — normalized identity`). L0 fast-path returns `internal/unresolved` + `service|target`; endpoint fast-path returns `internal/external_confirmed` + exact identity.
- **Judge (Stage 4, enhanced):** `context.py:274` `build_investigation_context` (bounded sections A–F, `ContextBudget`, deterministic split), `context_judge.py:279` `judge_investigation_context` (one call/context, `validate_candidate_judgments`, per-context cache), `judge.py:1262` `judge_contextual` (primary path; adaptive packing/splitting; returns `(GroupedEvidencePackage, [CandidateJudgment], [JudgmentFailure])`). `judge.py:953` grouped prompt/judge retained as fallback; `JudgeResult`/`failsafe` still used.
- **Models (Stage 5, enhanced):** `coupling.py:25` `CouplingGroup` / `coupling.py:133` `CouplingModel` (one group per shared resource; `from_contextual_judgments` aggregates candidate verdicts; model hidden). `decision.py:56` `DecisionRecord` / `decision.py:427` `DecisionModel` (deterministic policy `stage5-v1`: `potential_dependency`/`insufficient_evidence`/`review`, `ProcessingStatus`, versioned schema, evidence/counter-evidence refs, cache key, `_model` hidden); `build_decision_model:455` builds one record per candidate. `model.py:42` legacy `Dependency`/`DependencyModel` retained.
- **CLI (INTERACTIVE + API-KEY + DETERMINISTIC + ACCOUNTING):** `cli.py:441` `run_one_repo`: parse → discover → evidence → aggregate → API-key check (prompt Yes/No; No → deterministic-only) → `judge_contextual` → `CouplingModel.from_contextual_judgments` + `build_decision_model` → `build_graph_from_groups(decisions=…)` → `build_grouped_report(decisions=…)`. Accounting includes `decision` counts; interactive prompts/path/thinking validation unchanged.
- **Graph (unified Stage 6):** `graph.py:255` `_grouped_resource_key` + `graph.py:270` `build_graph_from_groups(model, decisions=…)` — L0 `depends_on` renders as direct `service → service` edges (`classification: "explicit"`, `semantics: "startup_dependency"`, `origin: "compose:depends_on"`, no confidence/decision, always included even with `meaningful_only=True`); L1 couplings render as `service → resource` edges with `classification: "potential_hidden" | "uncertain" | "rejected"`, `semantics: "resource_mediated"`, confidence on hidden edges, decision summaries/`DecisionView`s on resource nodes, model hidden. Legacy `build_graph:120` retained.
- **Report (unified Stage 7):** `report.py:395` `GroupedReportData` (`application`/`inputs`/`analysis`) + `report.py:648` `build_grouped_report(model, decisions=…)` — output now carries `explicit_relationships[]` (from explicit edges) separate from `findings[]` (hidden only); findings gain `classification`, `relationship_type`, `semantics`, `origin`, `decisions`, `decision_summary`; Markdown renders "Explicitly configured relationships", "startup ordering", and "Stage 5 decision" sections.
- **Frontend:** `frontend/src/App.tsx` — two tabs (graph default, analyze), sidebar run list, URL params `?run=`/`?select=`/`?view=`; `api.ts` (`listRuns`/`loadRun`/`analyzeRepository`); `types.ts` mirrors the backend contract (`classification`, `DecisionView`, decision summaries); `graph/layout.ts` dagre LR layout + classification → edge styling (explicit grey / `potential_hidden` yellow / `uncertain` dashed / `rejected` dotted, hidden behind a "Show rejected" toggle); `components/GraphView.tsx` React Flow + Controls/MiniMap/Background + node/edge/pane click → selection; `components/FlowNodes.tsx` Service/Resource custom nodes; `components/DetailsPanel.tsx` evidence, confidence bars, resolution chains, decision cards; `components/AnalyzeTab.tsx` local path + thinking level → `POST /api/analyze` (nothing uploaded to a cloud service); `api/server.py` serves `/api/runs`, `/api/run?id=`, `POST /api/analyze` (wraps `run_one_repo`) plus static `frontend/dist`. `start_ui.py`/`.bat`/`.sh` is the one-click launcher (API + dev server + browser, first-run `npm install`, kills process trees on exit, `--build` → serve dist via API only). Status: typecheck/build/pytest/`POST /api/analyze` round-trip plus dev-server + `/api` proxy integration verified 2026-10-29; in-browser interaction walkthrough pending.
- **Tests:** 174 passed (verified 2026-10-29). New since 167: `test_unified_graph.py` (7 — Compose `depends_on` syntax variants; explicit vs hidden edge invariants; explicit edges survive `meaningful_only`; decision metadata preserved + model hidden; report splits explicit/hidden; empty boundary; graph determinism).

---

## 3. Immediate Next Steps — Validation, Then Browser Walkthrough

**Stages 1–7 + unified Stage 6/7 + frontend complete (verified 2026-10-29):** 174 tests green (hermetic); `npm run typecheck`/`build` clean; API endpoints exercised live. Kubernetes is out of scope.
1. **Real-world validation (primary):** run `python run.py` against 2–3 real OSS Compose repos; per-repo candidates/findings review, TP/FP with ground truth, precision/recall where defensible; check LLM consistency across repeated judgments. Fix only demonstrated failures (repro + regression test + re-evaluation).
2. **Browser-level frontend walkthrough:** start `python api/server.py` + `cd frontend && npm run dev`; verify in a real browser: run loading, node/edge/pane clicks populate the details panel, confidence bars and decision cards render, yellow `potential_hidden` styling, legend, "Show rejected" toggle, Analyze tab end-to-end, URL params. The code implementing these behaviors is complete but not yet visually verified.
3. Document any demonstrated-but-unverified UI behaviors found during the walkthrough and fix only what is reproduced.
* Do NOT add platforms, adapters, dependencies, or unrelated analysis. Compose-only. Findings stay worded as **potential coupling** with evidence + confidence (D-038).

**How to test any repo — general (any computer, not just Lekha's):**

```cmd
REM First time only — from <path\to\Blindspot>
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

REM Everyday — simple start (no PYTHONPATH, no pip)
python run.py
REM -> BlindSpot banner
REM -> Enter absolute application path (e.g. C:\path\to\YourApp): C:\path\to\YourApp
REM -> Select AI thinking level [low / medium / high] (default: low): low
REM -> (if no API key) Would you like to enter an API key? [Y/n]: Y
REM -> Paste your API key (OpenRouter sk-or-... or Gemini AIza...): sk-or-v1-...
REM -> (if n) deterministic-only mode — JSONs only, no AI reasoning

type out\YourApp\report.md
REM Advanced — bypass menu (still prompts for API key if missing):
python run.py "C:\path\to\YourApp" --thinking low
```

```bash
# macOS / Linux / Git Bash — first time
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# everyday
python run.py
# or: bash run.sh
cat out/YourApp/report.md
```

Tier 1 validates via `python run.py` above; Tier 2 extends candidate discovery to K8s manifests without changing downstream.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges filtered + bounded packages (one per package).
- **Shared names ≠ dependencies** — `PORT` filtered before LLM. Different raw that normalize same (`user1:pass@db` vs `user2:pass@db` → `postgresql|db|5432|calcom`) are *kept* (project-aware).
- **Windows venv trap** — `python -m blindspot.cli` fails with `ModuleNotFoundError: No module named 'yaml'` if `python` is system python. Use `python run.py` (auto-uses `.venv`), or if using the module directly: `set PYTHONPATH=src && python -m blindspot.cli "C:\path\to\YourApp" --thinking low` with venv activated, or `.venv\Scripts\python -m blindspot.cli "C:\path\to\YourApp"` explicitly. `PyYAML` lives in `.venv`.
- **Evidence matters + bounded + distinct states** — Never silently `external`. States: `internal` (Compose service matched, host-like gated), `external_confirmed` (supported URI fully resolved), `partial` (supported scheme but unresolved vars), `unresolved` (plain `shared-db`, cycle, depth, unknown `abc://`). Provide `normalized_identity` only for exact/partial, credentials stripped, deterministic.
- **Chain bounded** — `MAX_RESOLUTION_DEPTH=10`, cycle detection via `seen_values`/`seen_vars`, deterministic lookup from `Compose/.env/env_file` (sorted services, `service_a/b` first), `resolution_chain` max 5 rendered.
- **Identity strength** — `exact` (proven physical `host+db`), `config` (same template `shared-db` or `postgresql://${HOST}/db` unresolved), `unknown`. Judge prompt guides confidence accordingly.
- **Value-structure, not name dictionary** — No `DATABASE_URL` list. Parsers on `://` scheme (`postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss`). Unknown `abc://` stays `resource_protocol=None`.
- **Dedup by normalized_identity** — `graph.py:76` `resource:env_var:postgresql|db|5432|calcom` dedup strips credentials; fallback to `resource_type:resource[=value]`. Preserves `confidence`, hides `model`, bipartite only, deterministic.
- **Interactive CLI contract** — `python run.py` (recommended) or `python -m blindspot.cli` with no args prompts for absolute `C:\path\to\YourApp` (quote-stripped, `is_absolute` + drive `C:` + exists + is_dir + `C:\` root→`repo` fallback + compose warning) and `low/medium/high` only (empty→`low`, `none` rejected), **plus API-key Yes/No every run if no key** (`Y`→ paste `sk-or-...`/`AIza...` saved to `.env`, `n`→ deterministic-only JSONs without AI reasoning, re-prompted next run). Batch `python run.py "C:\path" --thinking low` also validates absolute `C:\` path. Both handle `Ctrl+C` cleanly. `out_dir` now deterministic `out_root.suffix` check, no `sys.argv` hack.
- **General purpose README** — no `C:\Users\Lekha\...` paths; split into **First Time Setup (one-time: `venv` + `pip install`)** vs **Running (every time: `python run.py`)**; `.env` keys not shown as `echo` commands — user is prompted. `run.py`/`run.bat`/`run.sh` hide `PYTHONPATH`.
- **Edge-case sweep (D-032)** — atomic `cache.json` via `mkstemp+replace`, balanced JSON extraction for `reason` containing braces, `aggregation` truncation `warning`, `parser` YAML/UTF-8 contextual errors + required `env_file` warnings, `resolution` dead var cleanup, `report` empty boundary. Documented non-fixes: `mongodb` multi-host, dual `_decide`, `THINKING_BUDGETS none`, cross-platform `C:` fallback, Windows volume `C:\` colon.
- **One LLM call per survivor** — `0 for obvious noise + 1 per interesting candidate`; `uncertain` allowed; `cache.json` key = `sha256(cache_key_dict with normalized_identity/resolution_status/final_value)`. Deterministic-only mode → `0` LLM calls by design (`uncertain 0.0`, JSONs only).
- **Provider-agnostic** — Do not tie prompt/architecture to Gemini; `DEFAULT_MODEL` = `nvidia/nemotron-3-ultra-550b-a55b`; lazy `type: ignore` imports.
- **Confidence is first-class + reflects strength** — `exact` → 0.85-1.0, `config` → 0.6-0.85, `unknown` → 0.0-0.6. Do not invent via prompt wording alone; strengthen evidence first.
- **Model hidden** — `Dependency._model` private, `to_log_dict`/`cache.json` retain.
- **Stack** — `pyyaml`, `python-dotenv`, `google-genai`, `openai`, `networkx`, `matplotlib`.

---

## 5. Project Checklist — Stages 1–7 + Frontend Done, Validation Next

- [x] `STATE.md` unified Stage 6/7 + frontend (174 tests, verified 2026-10-29)
- [x] `HANDOFF.md` unified Stage 6/7 + frontend documented
- [x] `DECISIONS.md` D-021 → D-045 (hybrid → graph DATA → report+CLI → resolution/identity redesign → D-044 input adapters + L0/L1 → D-045 contextual judgment + decision model)
- [x] `README.md` finished Tier 1 + D-044 + Frontend section + unified Graph DATA contract bullets
- [x] Tests 174 passed (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14 + `test_accounting` 6 + `test_audit` 21 + `test_stage12` 12 + `test_decision` 18 + `test_stage34` 18 + `test_unified_graph` 7)
- [x] **Stage 6 — Graph enhancement** (unified explicit `service → service` + hidden `service → resource` edges; decision summaries; model hidden)
- [x] **Stage 7 — Report enhancement** (explicit relationships separated from hidden findings; decision cards rendered)
- [x] **`api/server.py`** (runs list/load, `POST /api/analyze`, static hosting of `frontend/dist`; live-verified)
- [x] **`frontend/`** (graph tab, analyze tab, details panel, dagre layout, dark theme; typecheck/build verified; browser walkthrough pending)
- [x] **`start_ui.py`/`.bat`/`.sh`** — one-click launcher (API + dev server + browser open + first-run `npm install`; dev and `--build` modes verified 2026-10-29)
- [ ] Real-world multi-repo validation (ground truth, precision/recall, LLM consistency)
- [ ] Browser-level frontend verification walkthrough

Kubernetes is out of scope. Do not add adapters, platforms, or unrelated dependencies.

---

## 6. Useful Commands

```cmd
REM Windows — any user (first time vs everyday)
git status
python -m pytest -v
REM Everyday simple start (no PYTHONPATH, handles venv):
python run.py
REM or: run.bat
REM Interactive prompts: C:\path\to\YourApp + low/medium/high + API key Y/n
REM Scripted (bypass menu, still prompts for API key if missing):
python run.py "C:\path\to\YourApp" --thinking low
type out\YourApp\report.md
type out\YourApp\graph.json
REM One-click UI (API + frontend + browser):
start_ui.bat
REM Alternate if run.py not used:
set PYTHONPATH=src && python -m blindspot.cli
```

```bash
# Git Bash / macOS / Linux
git status
python -m pytest -v
# Everyday:
python run.py
# or: bash run.sh
# judge with Gemini (low thinking) single synthetic check
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([p.to_dict() for p in build_evidence_packages(discover_candidates(p), p)])"
PYTHONPATH=src .venv/Scripts/python -c "from blindspot.judge import JudgeResult, validate_judge_result; validate_judge_result(JudgeResult(verdict='meaningful', confidence=0.93, reason='ok', model='test'))"
```

---

## 7. Files to Read First

1. `AGENTS.md` (§3 bounded evidence with states, §4 one call/candidate, §5 Dependency Model, §6 React Flow DATA + normalized_identity)
2. `PROJECT_PLAN.md` (§4 hybrid diagram, §6 DATA)
3. `STATE.md` (current status + unified Stage 6/7 + frontend)
4. `src/blindspot/inputs.py` (adapter boundary, `SUPPORTED_COMPOSE_FILENAMES`, `load_compose_document`, `discover/find_compose_file`)
5. `src/blindspot/parser.py` (`Service.image/depends_on/source_file`, `Project.sources`, `_parse_services`, multi-file merge)
6. `src/blindspot/discovery.py` (`Candidate` new fields, L0 `depends_on`, L1 `shared_endpoint`, dedup)
7. `src/blindspot/resolution.py` (`bounded_resolve:270`, `ResolutionResult`, `MAX_RESOLUTION_DEPTH`)
8. `src/blindspot/filtering.py` (`EvidencePackage` with `resolution_status`, `_decide_with_project`)
9. `src/blindspot/context.py` + `src/blindspot/context_judge.py` (bounded investigation contexts + validated contextual judgment)
10. `src/blindspot/coupling.py` + `src/blindspot/decision.py` (Stage 5 CouplingModel + policy-based DecisionModel)
11. `src/blindspot/graph.py` (`build_graph_from_groups` — unified explicit/hidden edges)
12. `src/blindspot/report.py` (`build_grouped_report` — explicit relationships + hidden findings + decisions)
13. `api/server.py` (local run server + analyze trigger + static hosting) and `start_ui.py`/`.bat`/`.sh` (one-click launcher)
14. `frontend/src/App.tsx` → `api.ts`/`types.ts` → `graph/layout.ts` → `components/` (graph tab, details panel, analyze tab)
15. `run.py` / `start_ui.py` / `README.md` (First Time Setup vs Running vs one-click UI — general purpose; Frontend section)