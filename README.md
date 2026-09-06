# BlindSpot — Implicit Cross-Service Coupling Detector

**Find hidden dependencies that network monitors cannot see — shared env vars, shared volumes, and shared configuration in Docker Compose.**

BlindSpot is a finished, demoable tool that turns `docker-compose.yml` + `.env` into an explainable `Service ↔ Resource` graph. It combines **deterministic static analysis** (filtering + bounded evidence resolution) with **one LLM judgment per surviving candidate** (cached, provider-agnostic, confidence mandatory) and renders the result as React Flow-ready graph data + human-readable report.

---

## What BlindSpot Does

Two services can be coupled without ever calling each other:

```yaml
services:
  orders:   { environment: { DB_HOST: postgres } }
  reports:  { environment: { DB_HOST: postgres } }
  postgres: { image: postgres:16 }
  api:      { volumes: [shared-data:/data] }
  worker:   { volumes: [shared-data:/data] }
```

* `orders ↔ reports` share `DB_HOST=postgres → postgres:16` (internal service) → same database → breaking change risk.
* `api ↔ worker` share `shared-data:/data` (named volume) → shared filesystem.

Standard tracing (Dynatrace/Datadog) only sees network calls — these couplings are invisible. BlindSpot makes them visible and explainable.

---

## Pipeline — 7 Stages, End-to-End (Prompt 2: Resource-Centric)

```
Input (docker-compose.yml + .env + env_file)
  → 1 Parse+Normalize (image, env_file, ${VAR}, ${VAR:-default}, unresolved preserved)
  → 2 Candidate Discovery (broad, deterministic: shared env_var + named_volume, value split)
  → 3 Filtering + Bounded Evidence + Resource Identity (GENERIC_ENV_KEYS drop PORT/DEBUG, bounded chain/cycle/depth MAX_RESOLUTION_DEPTH=10, normalized postgresql|host|port|db stripped, states internal/external_confirmed/partial/unresolved, strength exact/config/unknown)
  → 3b Resource-Centric Aggregation (group by normalized_identity — one bounded grouped evidence per shared resource, observations preserved, deterministic, no repo scan)
  → 4 LLM Judge (0 for noise + 1 call per resource group — not per pair, structured verdict/confidence/reason, cache.json sha256 on grouped key, failsafe uncertain 0.5)
  → 5 Coupling Model (resource-centric groups: resource identity/protocol/status/strength + services[] + observations + verdict/confidence/reason, _model hidden)
  → 6 Resource Graph (React Flow DATA {"nodes","edges"} bipartite Service → Resource, one node per group, one edge per service in group, confidence preserved, model hidden, deterministic, JSON serializable)
  → 7 Report (grouped human-readable: conclusion → evidence → technical details, summary distinguishes services_analyzed/resource_groups/observations/meaningful_groups)
  → CLI out/<repo>/report.json + report.md + graph.json (+ report.log.json internal)
```

**Completed:** Stages 1–7, **92 tests passing** (`test_parser 32 + test_discovery 8 + test_filtering 8 + test_graph 13 + test_resolution 17 + test_grouping 14`), resource-centric aggregation, deterministic resolution with chain/identity, provider-agnostic.

---

## Key Properties

* **Hybrid deterministic + LLM:** Static code finds candidates, LLM only interprets bounded grouped evidence (`calcom+calcom-api+studio → postgresql|${database_host}||${POSTGRES_DB}` config) — one judgment per shared resource, not per pair. No unrestricted repo scanning.
* **Filtering before LLM:** `PORT 8000 vs 9000`, `DEBUG`, `LOG_LEVEL`, `TZ` filtered deterministically — obvious noise costs 0 LLM calls. Different raw values that normalize to same physical resource (e.g. `postgresql://user1:pass@db:5432/calcom` vs `user2:pass2` → `postgresql|db|5432|calcom`) are kept and grouped.
* **Resource-centric aggregation:** Pairwise observations grouped by `normalized_identity` (primary key) into one bounded `GroupedEvidencePackage` per shared resource. Cal.com `6 observations → 1 group (3 services, 2 variable names)` → `1 LLM call` → `1 finding` → `1 resource node + 3 edges`. Unknown `CUSTOM` not over-merged; separate `normalized` → separate groups.
* **Evidence matters:** Every finding retains grouped `evidence{resource_identity, protocol, resolution_status, identity_strength, services[], configuration_evidence{service->[vars]}, unresolved_vars, representative_chain, evidence_count}` + `reason`. States `internal`/`external_confirmed`/`partial`/`unresolved` never silently `external`.
* **Normalized resource identity:** Value-structure parsing (`postgresql://`, `postgres://`, `mysql://`, `mongodb://`, `mongodb+srv://`, `redis://`) strips credentials, normalizes to `protocol|host|port|db`. `CUSTOM_RESOURCE=abc://...` stays unknown. `same configuration` vs `proven same physical` via `identity_strength` (`exact`/`config`/`unknown`).
* **Confidence first-class (group-level):** `JudgeResult` → `CouplingGroup` → `Graph` edge `data.confidence` → `Report` finding `confidence: 0.8` — never averaged across pairs; produced for the group directly. Prompt guides `exact→0.85-1.0`, `config→0.6-0.85`, `unknown→0.0-0.6`.
* **Resource-based, not service-to-service:** `calcom, calcom-api, studio → postgresql|${database_host}||${POSTGRES_DB}`. Never `calcom — calcom-api`. Distinct `service` vs `resource` nodes. Graph consumes grouped model: one node per group, one edge per service in group.
* **Provider-agnostic, model hidden:** Prompts (`build_judge_prompt`, `build_grouped_judge_prompt`) are model-agnostic. Clients pluggable; `thinking` low/medium via `set_thinking_level()`. `model` stored privately (`_model`, `cache.json`, `report.log.json`) and omitted from external `report.json`/`graph.json`.
* **Deterministic + cached (grouped):** Same `CouplingModel` → same grouped `cache_key sha256` (`grouping_key`, `resource_identity`, `services`, `configuration_evidence`, `unresolved_vars`) → same graph/report. Bounded chain (`MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup).

---

## Ground-Truth Fixtures (Deliberately Messy)

Fixtures prove parsing of real-world noise (`env_file` string vs list, `${VAR}` interpolation, `common.env`, `image`). They are for regression, not CLI demos.

| Fixture | Discovery | Filtering | Judge (real) | Graph |
|---|---|---|---|---|
| **shared_env** `fixtures/shared_env/` (`env_file: common.env`, `${DB_HOST}`, `${DB_NAME:-orders}`, `postgres:15` + `.env DB_HOST=shared-db`) | 3: `DB_HOST`/`DB_NAME`/`SHARED_EXTRA` | 2 kept (`DB_HOST`/`DB_NAME` `unresolved` `config`, `related_config` bounded) | 2 `meaningful` | 4 nodes (2 svc + 2 res), 4 edges |
| **shared_volume** `fixtures/shared_volume/` (`shared-data:/data` + `${DATA_PATH}`) | 2: `shared-data` + `DATA_PATH` | 1 kept (`shared-data` `internal` `named_volume`) | 1 `meaningful` | 3 nodes, 2 edges |
| **near_miss** `fixtures/near_miss/` (`PORT 8000≠9000`, `APP_ENV`, `SHARED_NOISE`) | 3: `PORT` (different), `APP_ENV`, `SHARED_NOISE` | 0 kept (generic + different-values filtered) | 0 calls | 0 nodes, 0 edges |

---

## Installation & Keys

**Windows (cmd.exe) — use the venv python, not system `python`:**

```cmd
REM from C:\Users\Lekha\Projects\Blindspot
.venv\Scripts\python -m pip install -r requirements.txt
REM creates PyYAML, python-dotenv, networkx, matplotlib, google-genai, openai
REM .env is gitignored, fixtures/**/.env is tracked
echo OPENROUTER_API_KEY=sk-or-v1-...>> .env
echo GEMINI_API_KEY=AQ.Ab8...>> .env
REM auto picks OPENROUTER if present else GEMINI; switch via --provider
```

**Git Bash / Linux / macOS:**

```bash
git clone <repo> && cd Blindspot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # pyyaml, python-dotenv, networkx, matplotlib, google-genai, openai
echo OPENROUTER_API_KEY=sk-or-v1-... >> .env
```

> **Why `.venv\Scripts\python`?** System `python` does not see `PyYAML` (`ModuleNotFoundError: No module named 'yaml'`). Always prefix with `PYTHONPATH=src` and the venv interpreter as shown below.

---

## Usage — One Command on Any Repo

**Windows cmd.exe (your case — absolute path, quoted):**

```cmd
REM from C:\Users\Lekha\Projects\Blindspot — use venv python
REM format: set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low
set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low

REM if `python` is system python and you get ModuleNotFoundError: No module named 'yaml',
REM replace `python` with `.venv\Scripts\python`:
REM set PYTHONPATH=src && .venv\Scripts\python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low

REM more examples (absolute paths, keep quotes)
set PYTHONPATH=src && python -m blindspot.cli "C:\path\to\real-repo" --out out --provider openrouter --thinking low
set PYTHONPATH=src && python -m blindspot.cli "C:\repo1" "C:\repo2" --out out --cache cache.json
set PYTHONPATH=src && python -m blindspot.cli --help
```

**Git Bash / Linux:**

```bash
PYTHONPATH=src .venv/Scripts/python -m blindspot.cli /path/to/repo --out out --thinking medium
PYTHONPATH=src .venv/Scripts/python -m blindspot.cli /tmp/real --out out --provider openrouter --thinking low
PYTHONPATH=src .venv/Scripts/python -m blindspot.cli --help
```

**Options:**

```
--compose docker-compose.yml  explicit file (default: auto-find docker-compose.yml|compose.yml via rglob)
--provider auto|openrouter|gemini
--thinking none|low|medium|high  (low 512 tokens cheap, medium 1024)
--cache cache.json  (use 'none' to disable)
--all  include coincidental/uncertain in graph/report (default: meaningful_only)
--out out  root -> out/<repo>/report.json+report.md+graph.json
```

**Outputs per repo:**

```
out/<repo>/report.json      (machine: summary{total, meaningful, services, resources} + findings[] with evidence{resolution_status, normalized_identity, ...})
out/<repo>/report.md        (human: ## 1. a <-> b through postgresql|prod-db|5432|app -- confidence 0.95 meaningful + Resolution chain + Related + Filtering)
out/<repo>/graph.json       (React Flow DATA {"nodes":[{"id":"service:a",...}, {"id":"resource:env_var:postgresql|prod-db|5432|app",...}], "edges":[...]} bipartite, dedup by normalized_identity)
out/<repo>/report.log.json  (internal: provider, model, cache_key)
cache.json                  (verdict cache, key = sha256(cache_key_dict with normalized_identity))
```

**Reading results:**

```cmd
type out\calcom\report.md
type out\calcom\report.json
type out\calcom\graph.json
type out\calcom\report.log.json
```

**Determinism & cost:** Same repo → same IDs (`sorted` + `sha256`). `near_miss` → 0 LLM calls. Interesting candidate → 1 call each, cached.

**Manual stages (without CLI):**

```bash
# Git Bash
PYTHONPATH=src .venv/Scripts/python -m pytest -v   # 78 tests: test_parser 32 + test_discovery 8 + test_filtering 8 + test_graph 13 + test_resolution 17
PYTHONPATH=src .venv/Scripts/python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([pkg.to_dict() for pkg in build_evidence_packages(discover_candidates(p), p)])"

REM Windows
set PYTHONPATH=src && .venv\Scripts\python -m pytest -v
```

---

## Graph DATA Contract — React Flow Ready (Grouped)

Stage 6 produces provider-agnostic data, not an image. Frontend handles layout/zoom/pan/selection/evidence panels.

```json
{
  "nodes": [
    {"id": "service:calcom", "type": "service", "data": {"name": "calcom"}},
    {"id": "service:calcom-api", "type": "service", "data": {"name": "calcom-api"}},
    {"id": "service:studio", "type": "service", "data": {"name": "studio"}},
    {"id": "resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "type": "resource", "data": {"name": "postgresql|${database_host}||${POSTGRES_DB}", "resource_type": "env_var", "resource_protocol": "postgresql", "resolution_status": "partial", "identity_strength": "config", "grouping_key": "env_var:postgresql|${database_host}||${POSTGRES_DB}", "resource_identity": "postgresql|${database_host}||${POSTGRES_DB}"}}
  ],
  "edges": [
    {"id": "service:calcom->resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "source": "service:calcom", "target": "resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "data": {"confidence": 0.8}},
    {"id": "service:calcom-api->resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "source": "service:calcom-api", "target": "resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "data": {"confidence": 0.8}},
    {"id": "service:studio->resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "source": "service:studio", "target": "resource:env_var:postgresql|${database_host}||${POSTGRES_DB}", "data": {"confidence": 0.8}}
  ]
}
```

* Bipartite `Service → Resource` only (`calcom → postgresql|${database_host}||${POSTGRES_DB} ← calcom-api, studio`), never `service→service`.
* Grouped: one resource node per shared resource identity (normalized), one edge per service in group (Cal.com 3 services → 1 node + 3 edges, not 6 findings → 6 edges). Dedup by `grouping_key` (`env_var:postgresql|...`), credentials stripped, deterministic `sorted` IDs, `networkx` optional internally. Graph consumes `CouplingModel`, not pairwise `DependencyModel`.

---

## Report Format (Grouped, Human-Readable)

`report.json` (grouped):
```json
{
  "summary": {"services_analyzed": 3, "resource_groups": 1, "observations": 6, "meaningful_groups": 1, "coincidental_groups": 0, "uncertain_groups": 0, "resources": 1},
  "graph_summary": {"nodes": 4, "edges": 3, "service_nodes": 3, "resource_nodes": 1},
  "generated_at": "2026-09-06T15:43:31Z",
  "findings": [{
    "title": "Shared PostgreSQL Database Configuration",
    "resource_identity": "postgresql|${database_host}||${POSTGRES_DB}",
    "resource_protocol": "postgresql",
    "resource_type": "env_var",
    "resolution_status": "partial",
    "identity_strength": "config",
    "services": ["calcom", "calcom-api", "studio"],
    "configuration_evidence": {"calcom": ["DATABASE_URL", "DATABASE_DIRECT_URL"], "calcom-api": ["DATABASE_URL", "DATABASE_DIRECT_URL"], "studio": ["DATABASE_URL", "DATABASE_DIRECT_URL"]},
    "unresolved_vars": ["DATABASE_HOST", "POSTGRES_DB"],
    "evidence_count": 6,
    "service_count": 3,
    "verdict": "meaningful", "confidence": 0.8, "reason": "All three services share the same templates..."
  }]
}
```

`report.md` (grouped, per spec §13-19):
```
# BlindSpot Report
Generated: 2026-09-06T19:00:48Z
## Summary
Services analyzed: 3
Shared resource groups: 1
Meaningful coupling groups: 1
Configuration observations: 6
Graph: 4 nodes (3 services, 1 resources), 3 edges
...
## 1. Shared PostgreSQL Database Configuration
Services involved:
- calcom
- calcom-api
- studio
Assessment: Meaningful implicit coupling
Confidence: Medium (0.80)
### Why this matters
...
### Configuration evidence
calcom
- DATABASE_URL
- DATABASE_DIRECT_URL
...
### Resource resolution
Type: postgresql  Resolution: Partial — shared configuration-level identity  Evidence strength: config
### Technical details
Normalized identity: postgresql|${database_host}||${POSTGRES_DB}
Unresolved variables: DATABASE_HOST, POSTGRES_DB
```

Conclusion first, evidence second, technical internals last. No `generic_variable=false` in body — retained only in JSON. Model hidden externally — `report.log.json` + `cache.json` retain provider for audit.

---

## Project Structure

```
Blindspot/
├── AGENTS.md, PROJECT_PLAN.md, STATE.md, DECISIONS.md, HANDOFF.md
├── .env (keys, gitignored), cache.json (gitignored), out/<repo>/ (reports, gitignored)
├── fixtures/ (shared_env, shared_volume, near_miss)  # !fixtures/**/.env tracked
├── src/blindspot/
│   ├── parser.py (Service.image, env_file, ${VAR})
│   ├── discovery.py (Candidate resource+value split, pairwise)
│   ├── filtering.py (GENERIC_ENV_KEYS, EvidencePackage, bounded resolution, _decide_with_project)
│   ├── resolution.py (bounded_resolve, ResolutionResult/Step, MAX_RESOLUTION_DEPTH=10, cycle, normalize postgresql|host|port|db)
│   ├── aggregation.py (aggregate_evidence_packages, GroupedEvidencePackage, grouping by normalized_identity)
│   ├── coupling.py (CouplingGroup, CouplingModel — resource-centric, one per shared resource)
│   ├── judge.py (JudgeResult, Gemini/OpenRouter, build_judge_prompt + build_grouped_judge_prompt, cache.json grouped)
│   ├── model.py (Dependency, DependencyModel — pairwise kept for tests, model hidden)
│   ├── graph.py (GraphNode/Edge/Data, build_graph + build_graph_from_groups, dedup by normalized_identity/grouping_key)
│   ├── report.py (ReportFinding/Data + GroupedReportFinding/Data, build_report + build_grouped_report — human-readable grouped)
│   └── cli.py (one-command Parse->Report with aggregation, grouped LLM, grouped graph/report)
└── tests/ (test_parser 32, test_discovery 8, test_filtering 8, test_graph 13, test_resolution 17, test_grouping 14)
```

---

## Technology

Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` (optional), `google-genai==0.8.0`, `openai==1.102.0`. Docker optional (read compose as text). Thinking `low 1024 → 512 tokens` / `medium 4096 → 1024` via `set_thinking_level()`. Resolution `MAX_RESOLUTION_DEPTH=10`.

---

## Documentation

* `AGENTS.md` — hybrid architecture (§3 bounded evidence with resolution states, §4 one call/candidate, §5 service-to-resource, §6 React Flow DATA, §7 Report)
* `STATE.md` — Stages 1–7 DONE + Tier 1 redesign, 78 tests
* `DECISIONS.md` — D-021 hybrid, D-022 image, D-023 bounded evidence, D-025 provider-agnostic judge, D-026 model hidden, D-027 Graph DATA, D-028 Report+CLI, D-029 resolution/identity redesign

This is Tier 1 finished + redesign — Tier 2 Kubernetes (ConfigMap/Secret/shared-volume via same `Filtering → Judge → Model → Graph → Report` pipeline) is next and the whole point.

Windows: `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` (or `.venv\Scripts\python` if `python` is system python). Then `set PYTHONPATH=src && python -m blindspot.cli --help` to start.
Git Bash: `PYTHONPATH=src .venv/Scripts/python -m blindspot.cli --help`
