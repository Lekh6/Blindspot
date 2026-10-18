# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.

**Last Updated:** 2026-10-12 (D-044 Stage 1+2 Enhancement Done)
**Current Phase:** **WORKSTREAM B — MULTI-REPO VALIDATION (D-041/D-042)** — Tier 1 audited + D-044 enhancement done (131 tests green, hermetic). Next: run `python run.py` on 2–3 real OSS Compose repos, review findings vs ground truth, then evidence-based fixes only. Deepening toward L2 table-level is set as direction (D-043, provisional — no implementation until validation). No K8s adapter, dependency, fixture, source read/write analysis, or Tier 1 redesign except evidence-based fixes.
**Current Branch:** `main` — working tree: Tier 1 frozen + D-044 enhancement + audited, Tier 2 proposal-only

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence with `internal/external_confirmed/partial/unresolved`, §3b aggregation by `normalized_identity`, §4 one call/group, §5 CouplingModel, §6 Graph from groups) + `PROJECT_PLAN.md` + `STATE.md` §2, then this file.
2. **Stages 1–7 + D-044 DONE:** `inputs.py` 119 LOC (adapter: 4 YAML + 2 JSON, `load_compose_document`, `discover/find_compose_file`), `parser.py` 540+ LOC (`Service.image/depends_on/source_file`, `Project.sources`, multi-file merge), `discovery.py` 387 LOC (`Candidate{candidate_id/level/relationship_type/origin/resource_identity/provenance}`; L0 `depends_on` + L1 `shared_env`/`shared_volume`/`shared_endpoint`), `resolution.py` 607 LOC, `aggregation.py` 200 LOC, `coupling.py` 150 LOC, `filtering.py` 875 LOC, `judge.py` 1050 LOC, `graph.py` 350 LOC, `report.py` 550 LOC (`GroupedReportData` `application`/`inputs`/`analysis` + `Analysis input`/`Pipeline summary` + zero-result explanations + separate `Services discovered` vs `Candidates generated`), `cli.py` ~750 LOC (`_discover_compose_sources`/`_relative_to_root` + full pipeline accounting `raw_candidates`/`observations`/`filtered_out`/`llm_calls`/`cache_hits` + separate CLI sections). **131 tests pass** (32+8+8+13+17+14+6+21+12 accounting). `celery` 5 services → 0 candidates now diagnosable as `5 services, 0 candidates, 0 obs` not `0 services`, `docker` `6→6→1→1` still consistent.
3. **Full pipeline now (grouped + accounting + D-044):** `inputs.load_compose_document` → `parse_compose_file` (with `Project.count_named_volumes()`) → `discover_candidates` (`raw_candidates` with L0/L1) → `build_evidence_packages` (`observations`/`filtered_out`) → `aggregate_evidence_packages` (`resource_groups`) → **API-key check (prompt Yes/No every run if missing; No → deterministic-only)** → `CouplingModel.from_grouped_judgments` → `build_graph_from_groups` → `build_grouped_report(accounting)` → `report.json` now `{application:{root}, inputs:{sources_used}, analysis:{parsed:{services, named_volumes}, discovery:{raw_candidates, observations}, aggregation:{resource_groups}, judgment:{groups_judged, llm_calls, cache_hits, meaningful}, graph:{nodes,edges}}}` + `summary` (compat) + `findings` + `report.md` now `Analysis input`/`Pipeline summary` with separate `Services discovered` vs `Candidates generated` and explanations for `0 candidates` vs `0 services` vs `filtered` vs `6→1` grouping. Simple start: `python run.py`; advanced: `python run.py "C:\path\to\repo" --thinking low`.
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-044), `HANDOFF.md`.
5. `.env` gitignored, `!fixtures/**/.env` allowed, `cache.json` ignored. **Any user — not just Lekha:** first-time `python -m venv .venv && pip install -r requirements.txt` (see README **First Time Setup**), then everyday `python run.py` or `run.bat` (prompts for `C:\path\to\YourApp` + `low/medium/high` + API key Yes/No). Advanced `python run.py "C:\path\to\repo" --thinking low` still works.

---

## 2. Where We Left Off

- `AGENTS.md` 530+ LOC + `PROJECT_PLAN.md` 310+ LOC hybrid spec (plus D-044 notes).
- **Inputs/Parser:** `inputs.py:1` `SUPPORTED_COMPOSE_FILENAMES` (4 YAML + 2 JSON), `load_compose_document`, `discover_compose_files`, `find_compose_file`. `parser.py:46` `Service.image/depends_on/source_file`, `parser.py:72` `Project.sources`, `parser.py:105` `normalize_depends_on`, `parser.py:488`/`505` image capture, `parser.py:397` multi-file merge (env override, volumes union, `depends_on` union, image latest-wins, sources unioned).
- **Discovery (D-044):** `discovery.py:77` `Candidate` with `candidate_id/level/relationship_type/origin/resource_identity/provenance`. `discovery.py:162` `_discover_shared_env` (L1 `shared_env`), `discovery.py:210` `_discover_shared_volumes` (L1 `shared_volume`), `discovery.py:249` `_discover_explicit_dependencies` (L0 `depends_on`, directional, unresolved kept), `discovery.py:289` `_discover_shared_endpoints` (L1 cross-var identity, `bounded_resolve`, skips same-key/unknown). `discovery.py:360` `discover_candidates` dedup by `(level,type,resource,value,pair)`, stable sort.
- **Resolution:** `resolution.py:1` `ResolutionResult/Step` + `bounded_resolve:270` (lookup from `Compose/.env/env_file`, while `${VAR}` with cycle/depth, `MAX_RESOLUTION_DEPTH=10`, `_normalize_connection_identity` for `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss` stripping creds, `internal` only if host-like or URI host matches service, `external_confirmed/partial/unresolved`, `exact/config/unknown` via `host|port|db`). `D-029`.
- **Filtering (D-044 fast-paths):** `filtering.py:68` `EvidencePackage` extended with `resolution_status/normalized_identity/resource_protocol/identity_strength/chain/final_value/unresolved_vars/is_cyclic/depth` + `_decide_with_project:386` + `build_evidence_packages:420` (enriched `filter: kept — normalized identity`). L0 fast-path returns `internal/unresolved` + `service|target`; endpoint fast-path returns `internal/external_confirmed` + exact identity.
- **Judge:** `judge.py:96` `build_judge_prompt` renders `resolution_status/normalized_identity/identity_strength/chain/unresolved` + confidence guidance `exact 0.85-1.0 / config 0.6-0.85 / unknown 0.0-0.6`; `cache_key_dict` includes `normalized_identity/resolution_status/final_value`.
- **Model:** `model.py:27` `Dependency{_model(hidden)}` + `model.py:218` `from_list` rehydrates new fields.
- **Graph:** `graph.py:76` `_resource_key(resource, resource_type, value, normalized_identity=None)` prefers `normalized_identity` (`resource:env_var:postgresql|db|5432|calcom`) else legacy, `build_graph:102` includes `normalized_identity/resource_protocol/resolution_status` in node `data`, dedup strips credentials.
- **Report:** `report.py:105` `to_markdown` branches `INTERNAL/EXTERNAL_CONFIRMED/PARTIAL/UNRESOLVED` + `Normalized:` + `Resolution chain` (bounded 5) + `Identity strength` + `Unresolved vars`.
- **CLI (INTERACTIVE + API-KEY + DETERMINISTIC + ACCOUNTING):** `cli.py:1` interactive: `_print_banner`, `_prompt_absolute_path` (absolute `C:\` check, exists/is_dir, quote stripping, compose warning + confirm, `Ctrl+C` clean), `_prompt_thinking` (only `low/medium/high`, default `low`), `_has_api_key`/`_prompt_for_api_key` (prompt Yes/No **every run** if no `OPENROUTER_API_KEY`/`GEMINI_API_KEY`; Y→ paste `sk-or-...`/`AIza...` saved to `.env`, n→ `_deterministic_pairs` `uncertain 0.0` without LLM, deterministic banner, JSONs only, re-prompted next run), `_run_interactive` → `run_one_repo` (`deterministic_only` branch skips `judge_grouped_packages`, `run.py` launcher). Advanced batch still supported: `cli.py "C:\path\to\repo" --thinking low --provider auto` with absolute-path validation.
- **Tests:** 131 passed. `shared_env` now `unresolved config` 0.75 honest (not `external` 0.90), `calcom` `DATABASE_URL` chain `internal exact postgresql|database||calcom`. New `test_stage12.py`: 12 acceptance tests covering input adapters, YAML/JSON equivalence, multi-file merge, L0 `depends_on`, L1 `shared_endpoint`, generic filtering, unresolved preservation, deterministic IDs, dedup, graph bipartite compat, unsupported input rejection.

---

## 3. Immediate Next Steps — Validate Tier 1 on Real Repos (D-041/D-042)

**Workstream A (audit) CLOSED 2026-09-28:** stages verified vs docs, 119 tests green (hermetic), e2e deterministic on fixtures + `tmp_calcom2`, 3 fixes landed (F1 Windows binds, F2 prompt wording, F4 test hermeticity) + `.venv` rebuilt. D-044 enhancement done 2026-10-12.
**Tier 1 code frozen except evidence-based fixes. K8s/source deferred:**
1. Workstream B — multi-repo validation via existing CLI (`python run.py`): Cal.com + 2–3 more; per-repo candidates/findings/TP/FP/misses + unsupported configs.
2. Workstream C — ground truth: synthetic + reviewed-real set; precision/recall where defensible; deterministic vs LLM separately; LLM reliability/calibration.
3. Workstream D — smallest fixes for demonstrated failures only (repro + stage + regression test + re-evaluation).
* Do NOT parse K8s YAML / add dependencies / build an adapter / start source read-write analysis / redesign Tier 1 until Tier 1 is demonstrably useful and a future gate approves it.

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

## 5. Project Checklist — Tier 1 Frozen, Tier 2 Proposal-Gated

- [x] `STATE.md` Stages 1–7 DONE + D-044 enhancement (131 tests)
- [x] `HANDOFF.md` D-044 documented
- [x] `DECISIONS.md` D-021 → D-044 (hybrid → graph DATA → report+CLI → resolution/identity redesign → D-044 input adapters + L0/L1)
- [x] `README.md` finished Tier 1 + redesign + D-044 (Input Formats & Dependency Levels section added)
- [x] Tests 131 passed (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14 + `test_accounting` 6 + `test_audit` 21 + `test_stage12` 12)
- [x] `src/blindspot/{inputs,parser,discovery,resolution,filtering,aggregation,coupling,judge,model,graph,report,cli,context,context_judge,decision,secrets}.py` complete
- [ ] Tier 2 Kubernetes — **PROPOSAL ONLY (D-039)**. Approval required before: PoC fixture `fixtures/k8s_schema_share/`, key-level discovery, or any `src/` change. Mere same-database YAML parsing is not an acceptable differentiator.

Next agent: review D-039. Do NOT implement Tier 2 until the proposal is approved. Tier 1 changes only for concrete bugs.

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
3. `STATE.md` (general setup + deterministic fallback 2026-09-07 + D-044)
4. `src/blindspot/inputs.py` (adapter boundary, `SUPPORTED_COMPOSE_FILENAMES`, `load_compose_document`, `discover/find_compose_file`)
5. `src/blindspot/parser.py` (`Service.image/depends_on/source_file`, `Project.sources`, `_parse_services`, multi-file merge)
6. `src/blindspot/discovery.py` (`Candidate` new fields, L0 `depends_on`, L1 `shared_endpoint`, dedup)
7. `src/blindspot/resolution.py` (`bounded_resolve:270`, `ResolutionResult`, `MAX_RESOLUTION_DEPTH`)
8. `src/blindspot/filtering.py` (`EvidencePackage` with `resolution_status`, `_decide_with_project`)
9. `src/blindspot/graph.py` (`_resource_key` normalized dedup)
10. `run.py` / `README.md` (First Time Setup vs Running — general purpose)