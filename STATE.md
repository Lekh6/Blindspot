# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-09-07 (Input Transparency & Accounting)
**Branch:** `main` — working tree: Stages 1–7 **DONE** + Tier 1 Redesign **DONE** + Prompt 2 **DONE** (grouped resource-centric) + **Interactive CLI** + **Edge-Case Sweep (12 fixes)** + **General README + Deterministic Fallback + run.py** + **Windows Input Fix** + **Fix .env Spam (4×→0)** + **Versioned History (report_1, _2)** + **Input Transparency & Accounting**; Tier 2 (Kubernetes) next
**Status:** `Tier 1 COMPLETE + REDESIGN + GROUPED + INTERACTIVE CLI + SWEEP + GENERAL SETUP + WIN FIX + NOSPAM + VERSIONED + ACCOUNTING` — Stages 1–7 **DONE** (parser + discovery + filtering + **bounded resolution** + **aggregation by normalized_identity** + **LLM Judge grouped 1/group** + **CouplingModel** + **Graph from groups** + **Grouped Report + Accounting** + **Interactive CLI: absolute C:\ path + low/medium/high + API-key prompt every run + deterministic-only JSONs** + **run.py/run.bat + versioned history + separate Services/Candidates accounting**) — Tier 1 is demoable; `celery` 5 services → 0 candidates now clearly distinguished from 0 services; Tier 2 next

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC (hybrid spec) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence with `internal/external_confirmed/partial/unresolved` + identity `exact/config/unknown`, §4 one call/candidate, confidence mandatory, §6 React Flow DATA + normalized_identity dedup) + provider-agnostic |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 540 LOC + `count_named_volumes()` + `discovery.py` 132 LOC + `resolution.py` 607 LOC + `aggregation.py` 200 LOC + `coupling.py` 150 LOC + `filtering.py` 530 LOC + `judge.py` 1050 LOC + `model.py` 265 LOC + `graph.py` 350 LOC + `report.py` 550 LOC (accounting `application`/`inputs`/`analysis` + `Analysis input`/`Pipeline summary` + zero-result explanations) + `cli.py` ~750 LOC (input source tracking `_discover_compose_sources`/`_relative_to_root` + full pipeline accounting + separate Services/Candidates CLI) + `run.py`/`run.bat`/`run.sh` |
| **Fixtures** | 3 messy fixtures — invariants preserved |
| **Tests** | **98 passed** (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17 + `test_grouping` 14 + `test_accounting` 6) |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed 2026-09-07 (input transparency: `Analysis input`/`Pipeline summary`, separate `Services` vs `Candidates`, `application`/`inputs`/`analysis` in JSON) |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` + `out/` / `report.json` / `report.md` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py:45` `Service.image`, `parser.py:488` image capture, `parser.py:397` multi-file, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py:20` `Candidate` with `value`, pairwise env + `named_volume` only, sorted |
| 3 | **Filtering + Resolution + Aggregation** | `Done` ⬅ **PROMPT 2 + ACCOUNTING** | `resolution.py:1` `ResolutionResult` + `bounded_resolve:270` + `aggregation.py:1` `aggregate_evidence_packages` (group by `normalized_identity`) — now with `raw_candidates` vs `observations` vs `filtered_out` accounting |
| 4 | **LLM Judge (Grouped)** | `Done` | `judge.py:96` `build_grouped_judge_prompt` + `judge_grouped_package:cache` + `0+1/group`, cache `groups_judged` vs `llm_calls`/`cache_hits` accounting |
| 5 | **Coupling Model** | `Done` ⬅ **PROMPT 2** | `coupling.py:1` `CouplingGroup` — one per shared resource, Graph+Report consume same |
| 6 | **Graph (Grouped)** | `Done` | `graph.py:76` `_resource_key` + `build_graph_from_groups:150` — Cal.com 1 node +3 edges, now `graph.nodes`/`edges` in accounting |
| 7 | **Report (Grouped)** | `Done` ⬅ **ACCOUNTING** | `report.py:550` `GroupedReportData` now `application`/`inputs`/`analysis` + `Analysis input`/`Pipeline summary` + zero-result explanations (`No Tier 1 candidates generated` vs `No services discovered`), separate `Services discovered` vs `Candidates generated` |

**Overall Tier 1:** **100% (code) + redesign** — Stages 1–7 done + bounded chain/identity redesign — Tier 1 is demoable; **Tier 2 (Kubernetes) is next — this is the whole point**
**Tier 2 (Kubernetes):** `Next` — ConfigMap/Secret/shared-volume detection via same pipeline (YAML parsing, workload normalization)

---

## 3. Repo Structure (Actual 2026-09-07 General + Deterministic)

```
Blindspot/
├── AGENTS.md (522), PROJECT_PLAN.md (301), STATE.md, DECISIONS.md, HANDOFF.md
├── README.md (First Time Setup vs Running — general purpose, now with Analysis input/Pipeline summary docs)
├── run.py / run.bat / run.sh (simple launchers — no PYTHONPATH needed)
├── .gitignore (allows fixtures/**/.env, ignores cache.json + .env + out/)
├── .env (API key, gitignored — created via prompt if missing)
├── fixtures/ (shared_env, shared_volume, near_miss) + out/ per repo (report.json/md, graph.json)
├── src/blindspot/
│   ├── __init__.py (exports all stages + grouped)
│   ├── parser.py (540 LOC + YAML/UTF-8 + env_file warnings + count_named_volumes)
│   ├── discovery.py (132 LOC)
│   ├── resolution.py (607 LOC) — bounded chain + normalize
│   ├── aggregation.py (200 LOC) — group by normalized_identity + truncation warn
│   ├── coupling.py (150 LOC) — CouplingGroup/Model
│   ├── filtering.py (530 LOC) — states + identity
│   ├── judge.py (1050 LOC, grouped prompt/cache + balanced JSON + atomic cache)
│   ├── model.py (265 LOC)
│   ├── graph.py (350 LOC, build_graph + build_graph_from_groups)
│   ├── report.py (550 LOC, grouped + accounting application/inputs/analysis + Analysis input/Pipeline summary)
│   └── cli.py (~750 LOC, input source tracking + full accounting + separate Services/Candidates)
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    ├── test_filtering.py (8)
    ├── test_graph.py (13)
    ├── test_resolution.py (17)
    ├── test_grouping.py (14) — resource-centric aggregation
    └── test_accounting.py (6) — Cases A-F (services vs candidates, no sources, filtered, aggregation, meaningful, sources)
```

**Validation & Next:**
- Tested on 3 synthetic fixtures + `celery-docker-example` (5 services, `docker-compose.yml` used, 0 candidates → correctly `5 services, 0 candidates, 0 observations` not `0 services`) + `docker` (Cal.com-like, 5 services, 6 raw → 6 obs → 1 group → 1 meaningful → 4 nodes/3 edges) + versioned history (`report.json` → `report_1.json`). `98 tests pass`.
- **Tier 2 NEXT:** Kubernetes manifests (ConfigMap/Secret/volumes) → same filtering → Judge → Model → Graph → Report pipeline

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

- 2026-09-07: **Input Transparency & Accounting DONE** — Prompt observability: `parser.py:62` `count_named_volumes()`, `cli.py` `_discover_compose_sources`/`_relative_to_root` + full accounting (`application_root`, `sources.discovered/used`, `parsed.services/named_volumes`, `discovery.raw_candidates/observations/filtered_out`, `aggregation.resource_groups`, `judgment.groups_judged/llm_calls/cache_hits/meaningful`, `graph.nodes/edges`) passed to `report.py` `build_grouped_report(accounting)` → `report.json` now `application`/`inputs`/`analysis` + `summary` (backward compat) + `report.md` `Analysis input`/`Pipeline summary` with separate `Services discovered` vs `Candidates generated` and explanations (`No Tier 1 candidates generated` vs `No services discovered`, `6 obs → 1 group`). CLI interactive/batch now same accounting. `celery` 5 services → 0 candidates now diagnosable, `docker` 6→6→1→1 still consistent. Added `tests/test_accounting.py` 6 cases (A-F), total `98 tests pass`.
- 2026-09-07: **Versioned History DONE** — `cli.py` now keeps history instead of overwrites: `out/<app>/report.json` (1st), `report_1.json` / `report_1.md` / `graph_1.json` / `report_1.log.json` (2nd), `report_2.json` etc. via `_versioned_path` (handles `report.log.json` → `report_1.log.json`). Re-analyzing same `C:\path\to\YourApp` no longer loses previous outputs.
- 2026-09-07: **Fix .env Spam DONE** — `parser.py` `env_file not found: .../.env` printed 4× for `C:\...\docker` (5 services each `env_file: .env`). Fixed via `_warned_env_files` dedup + generic missing → `debug` (0 visible at WARNING), `required:true` → `warning` deduped to 1. Verified `docker-compose.yaml` 5 services → 0 warnings, `6 candidates → 1 group → 1 meaningful` clean.
- 2026-09-07: **Windows Input Fix DONE** — `run.py` `os.execv` broke `input()` on Windows (console handle not inherited → cmd tried to execute typed path `'C:\...\docker' is not recognized`). Fixed by switching to `subprocess.call` + `SystemExit` which preserves console for interactive prompts; also made `run.py` robust when `yaml` missing (helpful `run.bat` hint) and updated `HANDOFF`/`README` to recommend `run.bat` on Windows. Verified `python run.py --help` and piped `C:\path\to\YourApp` + `low` + `n` flow.
- 2026-09-07: **General README + Deterministic Fallback + Simple Start DONE** — `README.md` split into `First Time Setup (one-time)` vs `Running (every time)`, now general purpose (`C:\path\to\YourApp`, `C:\path\to\Blindspot`, no Lekha paths); API-key `echo` removed — CLI now prompts Yes/No every run if no key (Y → paste `sk-or-...`/`AIza...` saved to `.env`, n → deterministic-only JSONs without AI reasoning, banner `Deterministic-Only Mode`); added `run.py`/`run.bat`/`run.sh` simple launchers (`python run.py`); `cli.py` new `_has_api_key`/`_prompt_for_api_key`/`_deterministic_pairs` + `deterministic_only` branch.
- 2026-09-07: **Repository Sweep — Simple Errors & Edge Cases DONE** — Audited 10 modules; fixes: `__init__.py` missing `placeholder_future_judge` export, `cli.py` fragile `out_dir`/`C:\` root + missing API-key warning + `find_compose` ×4 `rglob` → single scan + parse exception handling, `parser.py` YAML/UTF-8 context + required `env_file` warning, `resolution.py` dead vars, `judge.py` balanced JSON extraction + atomic `cache.json` temp+replace, `report.py` empty boundary, `aggregation.py` truncation warning; 5 documented non-fixes (mongodb multi-host, dual `_decide`, `THINKING_BUDGETS none`, cross-platform `C:` fallback, Windows volume `C:\` colon). 92 tests pass.
- 2026-09-07: **CLI Interactive Menu DONE** — `cli.py` polished interactive mode (default when no args): banner + absolute `C:\` path validation (exists/is_dir/compose warning, quote stripping, `Ctrl+C` clean) + `low/medium/high` thinking validation (no `none`), runs `run_one_repo` via `auto` provider; advanced flags retained (`--interactive` to force, absolute-path check on batch). `README.md` one-command section replaced with interactive guide.
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
