# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-09-06 (Prompt 2 Done)
**Current Phase:** **Tier 1 Complete + Redesign + Resource-Centric Aggregation DONE** (parser + discovery + **bounded resolution** + **aggregation by normalized_identity** + **Grouped LLM 1/group** + **CouplingModel** + **Graph from groups** + **Grouped Report** + **CLI minimal**) — **Tier 2 Kubernetes NEXT (whole point)**
**Current Branch:** `main` — working tree: Prompt 2 done, 92 tests, Tier 2 next

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence with `internal/external_confirmed/partial/unresolved`, §3b aggregation by `normalized_identity`, §4 one call/group, §5 CouplingModel, §6 Graph from groups) + `PROJECT_PLAN.md` + `STATE.md` §2, then this file.
2. **Stages 1–7 + Redesign + Prompt 2 DONE:** `parser.py` 540 LOC, `discovery.py` 132 LOC, `resolution.py` 607 LOC, `aggregation.py` 200 LOC (`GroupedEvidencePackage`, `aggregate_evidence_packages`), `coupling.py` 150 LOC (`CouplingGroup/Model`), `filtering.py` 530 LOC, `judge.py` 900 LOC (`build_grouped_judge_prompt`, `judge_grouped_packages` 0+1/group), `graph.py` 350 LOC (`build_graph_from_groups`), `report.py` 400 LOC (`GroupedReportData`), `cli.py` grouped. **92 tests pass** (32+8+8+13+17+14). Cal.com 6 obs →1 group (3 svcs) →1 finding →1 node+3 edges.
3. **Full pipeline now (grouped):** `parse_compose_file` → `discover_candidates` → `build_evidence_packages` → `aggregate_evidence_packages` (by `normalized_identity`) → `judge_grouped_packages` (0+1/group, cached on grouped key) → `CouplingModel.from_grouped_judgments` → `build_graph_from_groups` → `build_grouped_report` → `report.json+report.md+graph.json` (model hidden). CLI wraps for one/many repos (minimal `Provider/Thinking/Out`).
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-030 grouped), `HANDOFF.md`.
5. `.env` gitignored, `!fixtures/**/.env` allowed, `cache.json` ignored. **Windows: use absolute quoted `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low`** (or `.venv\Scripts\python` if `python` is system python → `No module named 'yaml'`).

---

## 2. Where We Left Off

- `AGENTS.md:1` 522 LOC + `PROJECT_PLAN.md:1` 301 LOC hybrid spec (plus redesign notes).
- **Parser:** `parser.py:45` `Service.image` + `parse_compose_file:488`/`505` + `_merge_projects:401`.
- **Resolution (NEW):** `resolution.py:1` `ResolutionResult/Step` + `bounded_resolve:270` (lookup from `Compose/.env/env_file`, while `${VAR}` with cycle/depth, `MAX_RESOLUTION_DEPTH=10`, `_normalize_connection_identity` for `postgresql/mysql/mongodb/redis` stripping creds, `internal` only if host-like or URI host matches service, `external_confirmed/partial/unresolved`, `exact/config/unknown` via ` host|port|db`). `D-029`.
- **Filtering (REDESIGN):** `filtering.py:68` `EvidencePackage` extended with `resolution_status/normalized_identity/resource_protocol/identity_strength/chain/final_value/unresolved_vars/is_cyclic/depth` + `_resolve_candidate:160` handles different-values via both sides normalize check + `_decide_with_project:386` + `build_evidence_packages:420` (enriched `filter: kept — normalized identity`). Keeps `filter_candidates` backward compat for unit tests.
- **Judge (REDESIGN):** `judge.py:96` `build_judge_prompt` now renders `resolution_status/normalized_identity/identity_strength/chain/unresolved` + confidence guidance `exact 0.85-1.0 / config 0.6-0.85 / unknown 0.0-0.6`; `cache_key_dict` now includes `normalized_identity/resolution_status/final_value`.
- **Model:** `model.py:27` `Dependency{_model(hidden)}` + `model.py:218` `from_list` rehydrates new fields.
- **Graph (REDESIGN):** `graph.py:76` `_resource_key(resource, resource_type, value, normalized_identity=None)` prefers `normalized_identity` (`resource:env_var:postgresql|db|5432|calcom`) else legacy, `build_graph:102` includes `normalized_identity/resource_protocol/resolution_status` in node `data`, dedup strips credentials.
- **Report (REDESIGN):** `report.py:105` `to_markdown` branches `INTERNAL/EXTERNAL_CONFIRMED/PARTIAL/UNRESOLVED` + `Normalized:` + `Resolution chain` (bounded 5) + `Identity strength` + `Unresolved vars`.
- **CLI:** `cli.py:1` one-command, `find_compose`, `--thinking low` typical for Windows example `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` (absolute path, quoted; use `.venv\Scripts\python` if `python` is system python).
- Tests: 78 passed. `shared_env` now `unresolved config` 0.75 honest (not `external` 0.90), `calcom` `DATABASE_URL` chain `internal exact postgresql|database||calcom`.

---

## 3. Immediate Next Steps — Tier 2 is the Whole Point

**Tier 1 + redesign is demoable — Tier 2 Kubernetes is next (same pipeline, provider-agnostic):**
* Parse Kubernetes YAML → workloads → shared ConfigMap/Secret/shared-volume candidates → same `Filtering (with resolution) → Judge → Model → Graph → Report` pipeline `AGENTS.md:385`.
* Do not create a separate downstream architecture for K8s findings.

**How to test any repo(s) — Windows cmd.exe vs bash:**

```cmd
REM Windows — from C:\Users\Lekha\Projects\Blindspot — absolute path, quoted, venv python
.venv\Scripts\python -m pip install -r requirements.txt
echo OPENROUTER_API_KEY=sk-or-v1-...>> .env
REM if `python` is system python and you get ModuleNotFoundError: No module named 'yaml', replace `python` with `.venv\Scripts\python`
set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low
set PYTHONPATH=src && python -m blindspot.cli "C:\path\to\repo1" "C:\path\to\repo2" --out out --provider openrouter --cache cache.json
type out\calcom\report.md
```

```bash
# Git Bash / Linux
pip install -r requirements.txt
echo OPENROUTER_API_KEY=sk-or-v1-... >> .env
PYTHONPATH=src .venv/Scripts/python -m blindspot.cli /path/to/repo --out out --thinking medium
PYTHONPATH=src .venv/Scripts/python -m blindspot.cli /tmp/real --out out --provider openrouter --cache cache.json
cat out/repo/report.md
# Summary table printed: cand -> pkgs -> deps (meaningful) -> nodes/edges
```

Tier 1 validates via CLI above; Tier 2 extends candidate discovery to K8s manifests without changing downstream.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges filtered + bounded packages (one per package).
- **Shared names ≠ dependencies** — `PORT` filtered before LLM. Different raw that normalize same (`user1:pass@db` vs `user2:pass@db` → `postgresql|db|5432|calcom`) are *kept* (project-aware).
- **Windows venv trap** — `python -m blindspot.cli` fails with `ModuleNotFoundError: No module named 'yaml'` if `python` is system python. Use `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` when venv is activated, or `set PYTHONPATH=src && .venv\Scripts\python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` explicitly. `PyYAML` lives in `.venv`.
- **Evidence matters + bounded + distinct states** — Never silently `external`. States: `internal` (Compose service matched, host-like gated), `external_confirmed` (supported URI fully resolved), `partial` (supported scheme but unresolved vars), `unresolved` (plain `shared-db`, cycle, depth, unknown `abc://`). Provide `normalized_identity` only for exact/partial, credentials stripped, deterministic.
- **Chain bounded** — `MAX_RESOLUTION_DEPTH=10`, cycle detection via `seen_values`/`seen_vars`, deterministic lookup from `Compose/.env/env_file` (sorted services, `service_a/b` first), `resolution_chain` max 5 rendered.
- **Identity strength** — `exact` (proven physical `host+db`), `config` (same template `shared-db` or `postgresql://${HOST}/db` unresolved), `unknown`. Judge prompt guides confidence accordingly.
- **Value-structure, not name dictionary** — No `DATABASE_URL` list. Parsers on `://` scheme (`postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss`). Unknown `abc://` stays `resource_protocol=None`.
- **Dedup by normalized_identity** — `graph.py:76` `resource:env_var:postgresql|db|5432|calcom` dedup strips credentials; fallback to `resource_type:resource[=value]`. Preserves `confidence`, hides `model`, bipartite only, deterministic.
- **One LLM call per survivor** — `0 for obvious noise + 1 per interesting candidate`; `uncertain` allowed; `cache.json` key = `sha256(cache_key_dict with normalized_identity/resolution_status/final_value)`.
- **Provider-agnostic** — Do not tie prompt/architecture to Gemini; `DEFAULT_MODEL` = `nvidia/nemotron-3-ultra-550b-a55b`; lazy `type: ignore` imports.
- **Confidence is first-class + reflects strength** — `exact` → 0.85-1.0, `config` → 0.6-0.85, `unknown` → 0.0-0.6. Do not invent via prompt wording alone; strengthen evidence first.
- **Model hidden** — `Dependency._model` private, `to_log_dict`/`cache.json` retain.
- **Stack** — `pyyaml`, `python-dotenv`, `google-genai`, `openai`, `networkx`, `matplotlib`.

---

## 5. Project Checklist — Tier 1 Done + Redesign, Tier 2 Next

- [x] `STATE.md` Stages 1–7 DONE + redesign (78 tests, normalized dedup)
- [x] `HANDOFF.md` redesign + Windows venv gotcha documented
- [x] `DECISIONS.md` D-021 → D-029 (hybrid → graph DATA → report+CLI → resolution/identity redesign)
- [x] `README.md` finished Tier 1 + redesign (pipeline stage 3 states, normalized identity, Windows cmd example `set PYTHONPATH=src && .venv\Scripts\python -m blindspot.cli ..\Docker --out out\calcom --thinking medium`, 78 tests) — still notes Tier 2 as next
- [x] Tests 78 passed (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13 + `test_resolution` 17)
- [x] `src/blindspot/{parser, discovery, resolution, filtering, judge, model, graph, report, cli}.py` complete
- [ ] Tier 2 Kubernetes (ConfigMap/Secret/volumes, same pipeline) — **NEXT, whole point of project**

Next agent: implement Tier 2 K8s candidate discovery → same Filtering→Judge→Model→Graph→Report pipeline.

---

## 6. Useful Commands

```cmd
REM Windows
git status
set PYTHONPATH=src && python -m pytest -v
REM judge with OpenRouter (low thinking) on absolute-path repo
set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low
type out\calcom\report.md
type out\calcom\graph.json
REM if ModuleNotFoundError: No module named 'yaml', use .venv\Scripts\python instead of python
```

```bash
# Git Bash
git status
PYTHONPATH=src .venv/Scripts/python -m pytest -v
# judge with Gemini (low thinking) single synthetic check
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([p.to_dict() for p in build_evidence_packages(discover_candidates(p), p)])"
PYTHONPATH=src .venv/Scripts/python -c "from blindspot.judge import JudgeResult, validate_judge_result; validate_judge_result(JudgeResult(verdict='meaningful', confidence=0.93, reason='ok', model='test'))"
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md` (§3 bounded evidence with states, §4 one call/candidate, §5 Dependency Model, §6 React Flow DATA + normalized_identity)
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md` (§4 hybrid diagram, §6 DATA)
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md` (redesign 2026-09-06)
4. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/resolution.py` (`bounded_resolve:270`, `ResolutionResult`, `MAX_RESOLUTION_DEPTH`)
5. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/filtering.py` (`EvidencePackage` with `resolution_status`, `_decide_with_project`)
6. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/graph.py` (`_resource_key` normalized dedup)
