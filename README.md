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

## Pipeline — 7 Stages, End-to-End

```
Input (docker-compose.yml + .env + env_file)
  → 1 Parse+Normalize (image, env_file, ${VAR}, ${VAR:-default}, unresolved preserved)
  → 2 Candidate Discovery (broad, deterministic: shared env_var + named_volume, value split)
  → 3 Filtering + Bounded Evidence + Resource Identity (drop generic PORT/DEBUG, bounded chain/cycle/depth, normalized postgresql|host|port|db stripped, states internal/external_confirmed/partial/unresolved, strength exact/config/unknown)
  → 3b Resource-Centric Aggregation (group by normalized resource identity — one bounded grouped evidence per shared resource, observations preserved, deterministic, no repo scan)
  → 4 LLM Judge (0 for noise + 1 call per resource group — not per pair, structured verdict/confidence/reason, cached, failsafe uncertain 0.5)
  → 5 Coupling Model (resource-centric groups: identity/protocol/status/strength + services[] + observations + verdict/confidence/reason)
  → 6 Resource Graph (React Flow DATA {"nodes","edges"} bipartite Service → Resource, one node per group, one edge per service in group, confidence preserved, deterministic, JSON serializable)
  → 7 Report (human-readable: conclusion → evidence → technical details, summary distinguishes services/resource groups/observations)
  → CLI out/<repo>/report.json + report.md + graph.json (+ report.log.json internal)
```

---

## Key Properties

* **Hybrid deterministic + LLM:** Static code finds candidates, LLM only interprets bounded grouped evidence (`calcom+calcom-api+studio → postgresql|${database_host}||${POSTGRES_DB}` config) — one judgment per shared resource, not per pair. No unrestricted repo scanning.
* **Filtering before LLM:** `PORT 8000 vs 9000`, `DEBUG`, `LOG_LEVEL`, `TZ` filtered deterministically — obvious noise costs 0 LLM calls. Different raw values that normalize to same physical resource (e.g. `postgresql://user1:pass@db:5432/calcom` vs `user2:pass2` → `postgresql|db|5432|calcom`) are kept and grouped.
* **Resource-centric aggregation:** Pairwise observations grouped by `normalized_identity` (primary key) into one bounded `GroupedEvidencePackage` per shared resource. Cal.com `6 observations → 1 group (3 services, 2 variable names)` → `1 LLM call` → `1 finding` → `1 resource node + 3 edges`. Unknown `CUSTOM` not over-merged; separate `normalized` → separate groups.
* **Evidence matters:** Every finding retains grouped `evidence{resource_identity, protocol, resolution_status, identity_strength, services[], configuration_evidence{service->[vars]}, unresolved_vars, representative_chain, evidence_count}` + `reason`. States `internal`/`external_confirmed`/`partial`/`unresolved` never silently `external`.
* **Normalized resource identity:** Value-structure parsing (`postgresql://`, `postgres://`, `mysql://`, `mongodb://`, `mongodb+srv://`, `redis://`) strips credentials, normalizes to `protocol|host|port|db`. `CUSTOM_RESOURCE=abc://...` stays unknown. `same configuration` vs `proven same physical` via `identity_strength` (`exact`/`config`/`unknown`).
* **Confidence first-class (group-level):** `JudgeResult` → `CouplingGroup` → `Graph` edge `data.confidence` → `Report` finding `confidence: 0.8` — never averaged across pairs; produced for the group directly. Prompt guides `exact→0.85-1.0`, `config→0.6-0.85`, `unknown→0.0-0.6`.
* **Resource-based, not service-to-service:** `calcom, calcom-api, studio → postgresql|${database_host}||${POSTGRES_DB}`. Never `calcom — calcom-api`. Distinct `service` vs `resource` nodes. Graph consumes grouped model: one node per group, one edge per service in group.
* **Provider-agnostic, model hidden:** Prompts (`build_judge_prompt`, `build_grouped_judge_prompt`) are model-agnostic. Clients pluggable; `thinking` low/medium/high via `set_thinking_level()`. `model` stored privately (`_model`, `cache.json`, `report.log.json`) and omitted from external `report.json`/`graph.json`.
* **Deterministic + cached (grouped):** Same `CouplingModel` → same grouped `cache_key sha256` (`grouping_key`, `resource_identity`, `services`, `configuration_evidence`, `unresolved_vars`) → same graph/report. Bounded chain (`MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup).
* **Input transparency & accounting:** Every run records `application.root`, `inputs.sources_used` (relative), `analysis.parsed.services/named_volumes`, `discovery.raw_candidates/observations`, `aggregation.resource_groups`, `judgment.groups_judged/llm_calls/cache_hits`, `graph.nodes/edges` — same numbers in CLI, `report.json` (`application`/`inputs`/`analysis`), and `report.md` (`Analysis input`/`Pipeline summary`). `0 candidates` with `5 services` is now diagnosable as *no Tier-1 evidence* not *no services*.

---

## Ground-Truth Fixtures (Deliberately Messy)

Fixtures prove parsing of real-world noise (`env_file` string vs list, `${VAR}` interpolation, `common.env`, `image`). They are for regression, not CLI demos.

| Fixture | Discovery | Filtering | Judge (real) | Graph |
|---|---|---|---|---|
| **shared_env** `fixtures/shared_env/` (`env_file: common.env`, `${DB_HOST}`, `${DB_NAME:-orders}`, `postgres:15` + `.env DB_HOST=shared-db`) | 3: `DB_HOST`/`DB_NAME`/`SHARED_EXTRA` | 2 kept (`DB_HOST`/`DB_NAME` `unresolved` `config`, `related_config` bounded) | 2 `meaningful` | 4 nodes (2 svc + 2 res), 4 edges |
| **shared_volume** `fixtures/shared_volume/` (`shared-data:/data` + `${DATA_PATH}`) | 2: `shared-data` + `DATA_PATH` | 1 kept (`shared-data` `internal` `named_volume`) | 1 `meaningful` | 3 nodes, 2 edges |
| **near_miss** `fixtures/near_miss/` (`PORT 8000≠9000`, `APP_ENV`, `SHARED_NOISE`) | 3: `PORT` (different), `APP_ENV`, `SHARED_NOISE` | 0 kept (generic + different-values filtered) | 0 calls | 0 nodes, 0 edges |

---

## First Time Setup (one-time)

Do this once after cloning. Installs dependencies and prepares the environment. You do **not** need to repeat this to run the service later.

**1. Get the code**

```bash
git clone <your-repo-url> BlindSpot
cd BlindSpot
```

**2. Create a virtual environment & install dependencies**

*Windows (cmd.exe):*

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

*macOS / Linux / Git Bash:*

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This installs `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai`, `openai`. The `.env` file is gitignored; `fixtures/**/.env` is tracked for tests.

> **Why a venv?** System `python` often does not see `PyYAML` (`ModuleNotFoundError: No module named 'yaml'`). Always run BlindSpot with the venv activated (or use `python run.py` which handles it).

**3. LLM API key (optional, recommended)**

BlindSpot works best with an LLM for semantic judgment (`meaningful` vs `coincidental`). **You do not need to edit `.env` manually.** On your first run, if no key is found, BlindSpot will prompt you:

```
No LLM API key found in .env
Would you like to enter an API key? [Y/n]: Y
Paste your API key (OpenRouter sk-or-... or Gemini AIza...): sk-or-v1-...
Saved OPENROUTER_API_KEY to .env — will be used for LLM analysis.
```

- Answer **Y** → paste your key (OpenRouter `sk-or-...` or Gemini `AIza...`). It is saved to `.env` for future runs.
- Answer **n** → runs in **deterministic-only mode**: only structural JSONs (`graph.json`, `report.json`) are produced, without AI reasoning (`verdict`/`confidence`/`reason`). Output will be less accurate and harder to interpret. You will be asked again on the next run.

You can also create `.env` manually if you prefer (`OPENROUTER_API_KEY=...` or `GEMINI_API_KEY=...`), but the prompt is the simplest path.

---

## Running BlindSpot (every time)

After the one-time setup above, starting the service is a single command. No `pip install`, no `PYTHONPATH`, no flags needed.

**Simple start — interactive menu:**

*Windows:*

```cmd
python run.py
REM or double-click run.bat
```

*macOS / Linux / Git Bash:*

```bash
python run.py
# or: bash run.sh
# or: ./run.sh
```

`run.py` / `run.bat` / `run.sh` handle the `PYTHONPATH` and venv selection automatically. Use whichever launcher fits your OS.

**What you will be asked (2 questions):**

```
========================================================
  BlindSpot — Implicit Cross-Service Coupling Detector
========================================================
  Interactive setup — answer 2 questions to run analysis.

  Enter absolute application path (e.g. C:\path\to\YourApp): C:\path\to\YourApp
  Select AI thinking level [low / medium / high] (default: low): low

--------------------------------------------------------
  Application : C:\path\to\YourApp
  Thinking    : low
  Output      : out/YourApp/
--------------------------------------------------------
  Running BlindSpot pipeline...
```

*   **1. Application path** — absolute path **from the C drive root** (e.g. `C:\path\to\YourApp`). Keep quotes if the path contains spaces: `"C:\My Projects\App"`. The CLI validates that the path is absolute, exists, is a directory, and contains a `docker-compose.yml`/`compose.yml` (searched recursively). If none is found, it warns and asks for confirmation.
*   **2. AI thinking** — `low` (fast/cheap), `medium` (balanced), or `high` (thorough). Only `low`/`medium`/`high` are accepted; empty defaults to `low`. Case-insensitive.

If no API key is present, a third prompt appears (see First Time Setup §3) — **Y** to enter a key, **n** for deterministic-only JSONs.

Edge cases are handled inline: empty path, relative path, non-existent directory, file instead of directory, missing compose file, invalid thinking keyword, and `Ctrl+C` exits cleanly without a traceback.

**What you will see (pipeline accounting — same as `report.json`/`report.md`):**

```
Application : C:\path\to\YourApp
Thinking    : low
Output      : out/YourApp/
...
Analysis complete

Input
  Compose sources used : 1 (docker-compose.yml)

Parsed
  Services             : 5
  Named volumes        : 1

Analysis
  Candidates generated : 0
  Observations         : 0
  Resource groups      : 0
  Groups judged        : 0
  Meaningful couplings : 0

Graph
  Nodes                : 0
  Edges                : 0
```

`0 candidates` with `5 services` now clearly means *“parsed successfully, but no Tier-1 shared-resource evidence was found”* — not *“0 services discovered.”* See `report.md` `Analysis input` + `Pipeline summary` for the same numbers and `## Result` explanations.

**Outputs per run (versioned history, not overwrites):**

```
out/<app>/report.json      (1st run)
out/<app>/report_1.json    (2nd run on same app — history kept, not overwritten)
out/<app>/report_2.json    (3rd run, etc.)
out/<app>/report.md        → report_1.md, report_2.md ...
out/<app>/graph.json       → graph_1.json, graph_2.json ...
out/<app>/report.log.json  → report_1.log.json ...
cache.json                 (verdict cache, key = sha256(cache_key_dict with normalized_identity))
```

First analysis creates `report.json`; re-analyzing the same `C:\path\to\YourApp` keeps previous files and writes `report_1.json` / `report_1.md` / `graph_1.json` / `report_1.log.json`, then `report_2.json` etc. All runs stay in `out/<app>/` for history.

*Deterministic-only note:* If you chose **n** at the API-key prompt, only structural JSONs are produced without AI reasoning. `report.md` will contain a banner stating deterministic mode and findings will show `verdict: uncertain (0.0)` with reason `Deterministic-only mode — no LLM analysis`.

**Reading results (any OS):**

```cmd
type out\YourApp\report.md
type out\YourApp\report.json
type out\YourApp\graph.json
```

```bash
cat out/YourApp/report.md
cat out/YourApp/report.json
cat out/YourApp/graph.json
```

**Determinism & cost:** Same repo → same IDs (`sorted` + `sha256`). `near_miss` → 0 LLM calls. Interesting candidate → 1 call per resource group, cached.

**Advanced — flags for scripting / tests (optional):**

```cmd
python run.py "C:\path\to\repo1" "C:\path\to\repo2" --thinking low
python run.py "C:\path\to\repo" --thinking medium --provider openrouter --out out --cache cache.json
python run.py --interactive   REM force menu even when flags are present
python run.py --help
```

```
--compose docker-compose.yml  explicit file (default: auto-find docker-compose.yml|compose.yml via rglob)
--provider auto|openrouter|gemini
--thinking low|medium|high    (low=cheap, medium=balanced, high=thorough; default: low)
--cache cache.json            (use 'none' to disable)
--all                         include coincidental/uncertain in graph/report (default: meaningful_only)
--out out                     root -> out/<repo>/report.json+report.md+graph.json
--interactive                 force interactive menu
--list-fixtures               list bundled fixtures and exit
```

*General paths:* On Windows, paths in advanced mode must be absolute from `C:\` drive (e.g. `C:\path\to\repo`). On macOS/Linux/Git Bash, absolute paths like `/path/to/repo` are accepted.

**Manual stages (without CLI — for development):**

```bash
# Git Bash / macOS / Linux
.venv/bin/python -m pytest -v
PYTHONPATH=src .venv/bin/python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([pkg.to_dict() for pkg in build_evidence_packages(discover_candidates(p), p)])"

# Windows (cmd.exe) — with venv activated
python -m pytest -v
```

---

## Graph DATA Contract — React Flow Ready

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

## Report Format

`report.json` (now self-explanatory with `application`/`inputs`/`analysis` + `summary` for compat):
```json
{
  "application": {"root": "C:\\path\\to\\YourApp"},
  "inputs": {"sources_used": ["docker-compose.yml"]},
  "analysis": {
    "parsed": {"services": 5, "named_volumes": 1},
    "discovery": {"raw_candidates": 6, "observations": 6, "filtered_out": 0},
    "aggregation": {"resource_groups": 1, "observations": 6},
    "judgment": {"groups_judged": 1, "meaningful": 1, "coincidental": 0, "uncertain": 0, "llm_calls": 1, "cache_hits": 0},
    "graph": {"nodes": 4, "edges": 3, "service_nodes": 3, "resource_nodes": 1}
  },
  "summary": {"services_analyzed": 5, "resource_groups": 1, "observations": 6, "meaningful_groups": 1, "coincidental_groups": 0, "uncertain_groups": 0, "resources": 1},
  "graph_summary": {"nodes": 4, "edges": 3, "service_nodes": 3, "resource_nodes": 1},
  "generated_at": "2026-09-07T...",
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

Zero-result example (`celery-docker-example` — 5 services, no Tier-1 candidates):
```json
{
  "application": {"root": "C:\\path\\to\\celery"},
  "inputs": {"sources_used": ["docker-compose.yml"]},
  "analysis": {
    "parsed": {"services": 5, "named_volumes": 1},
    "discovery": {"raw_candidates": 0, "observations": 0, "filtered_out": 0},
    "aggregation": {"resource_groups": 0, "observations": 0},
    "judgment": {"groups_judged": 0, "meaningful": 0, "coincidental": 0, "uncertain": 0, "llm_calls": 0, "cache_hits": 0},
    "graph": {"nodes": 0, "edges": 0}
  },
  "findings": []
}
```

`report.md` (now with `Analysis input` + `Pipeline summary` + `Result` explanation):
```
# BlindSpot Report
Generated: 2026-09-07T...

## Analysis input
Application root:
C:\path\to\YourApp
Compose configuration used:
- docker-compose.yml

## Pipeline summary
Configuration parsed:
- Services discovered: 5
- Named volumes discovered: 1
Dependency analysis:
- Candidates generated: 6
- Observations: 6
- Shared resource groups: 1
- Groups judged: 1
- Meaningful couplings: 1
Graph:
- Nodes: 4
- Edges: 3

## 1. Shared PostgreSQL Database Configuration
Services involved:
- calcom
- calcom-api
- studio
Assessment: Meaningful implicit coupling
Confidence: Medium (0.80)
...
```

For `0 candidates` (legitimate, not parsing failure):
```
## Result
BlindSpot successfully parsed 5 services and 1 named volume.
No Tier 1 dependency candidates were generated from the supported configuration signals...
This does not mean the services have no dependencies.
```

Conclusion first, evidence second, technical internals last. No `generic_variable=false` in body — retained only in JSON. Model hidden externally — `report.log.json` + `cache.json` retain provider for audit. `report.json` keeps `summary` for backward compat while new `analysis` is the primary accounting.

---

## Project Structure

```
Blindspot/
├── AGENTS.md, PROJECT_PLAN.md, STATE.md, DECISIONS.md, HANDOFF.md
├── .env (keys, gitignored), cache.json (gitignored), out/<repo>/ (reports, gitignored)
├── fixtures/ (shared_env, shared_volume, near_miss)  # !fixtures/**/.env tracked
├── src/blindspot/
│   ├── parser.py (Service.image, env_file, ${VAR}, count_named_volumes)
│   ├── discovery.py (Candidate resource+value split, pairwise)
│   ├── filtering.py (GENERIC_ENV_KEYS, EvidencePackage, bounded resolution, _decide_with_project)
│   ├── resolution.py (bounded_resolve, ResolutionResult/Step, MAX_RESOLUTION_DEPTH=10, cycle, normalize postgresql|host|port|db)
│   ├── aggregation.py (aggregate_evidence_packages, GroupedEvidencePackage, grouping by normalized_identity)
│   ├── coupling.py (CouplingGroup, CouplingModel — resource-centric, one per shared resource)
│   ├── judge.py (JudgeResult, Gemini/OpenRouter, build_judge_prompt + build_grouped_judge_prompt, cache.json grouped, llm_calls/cache_hits)
│   ├── model.py (Dependency, DependencyModel — pairwise kept for tests, model hidden)
│   ├── graph.py (GraphNode/Edge/Data, build_graph + build_graph_from_groups, dedup by normalized_identity/grouping_key)
│   ├── report.py (ReportFinding/Data + GroupedReportFinding/Data, build_report + build_grouped_report — now with application/inputs/analysis + Analysis input/Pipeline summary + zero-result explanations)
│   └── cli.py (interactive: absolute C:\ + low/medium/high + input source tracking + full pipeline accounting + versioned history)
└── tests/ (test_parser 32, test_discovery 8, test_filtering 8, test_graph 13, test_resolution 17, test_grouping 14, test_accounting 6)
```

---

## Technology

Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` (optional), `google-genai==0.8.0`, `openai==1.102.0`. Docker optional (read compose as text). Thinking `low 1024 → 512 tokens` / `medium 4096 → 1024` / `high 8192 → 2048` via `set_thinking_level()`. Resolution `MAX_RESOLUTION_DEPTH=10`. Cache `cache.json` is written atomically via `mkstemp` + `replace`.

---

## Documentation

* `AGENTS.md` — architecture and pipeline design
* `STATE.md` — current project state
* `DECISIONS.md` — architecture decisions
* `HANDOFF.md` — handoff notes
* `PROJECT_PLAN.md` — project plan

Run `python run.py` (or double-click `run.bat` on Windows) — it prompts for absolute `C:\` path + `low/medium/high` thinking (and API key if missing) — or `python run.py --help` to see flags.
