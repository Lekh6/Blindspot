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
  → 3 Filtering + Bounded Evidence (GENERIC_ENV_KEYS drop PORT/DEBUG, build one EvidencePackage per survivor: resolved_service/image/is_internal, related_config bounded, signals)
  → 4 LLM Judge (0 calls for noise + 1 call per survivor, structured verdict/confidence/reason, cache.json sha256, failsafe uncertain 0.5)
  → 5 Dependency Model (service-to-resource, evidence+verdict/confidence/reason, _model hidden externally, logged internally)
  → 6 Resource Graph (React Flow DATA {"nodes","edges"} bipartite Service ↔ Resource, dedup by resource_type, confidence preserved, model hidden, deterministic, JSON serializable)
  → 7 Report (report.json + report.md per finding: resource + evidence + verdict/confidence/reason + summary)
  → CLI out/<repo>/report.json + report.md + graph.json (+ report.log.json internal)
```

**Completed:** Stages 1–7, **61 tests passing**, 3 deliberately messy synthetic fixtures, one-command testing on any repo, provider-agnostic.

---

## Key Properties

* **Hybrid deterministic + LLM:** Static code finds candidates, LLM only interprets bounded evidence (`DB_HOST=postgres → postgres:16`). No unrestricted repo scanning.
* **Filtering before LLM:** `PORT 8000 vs 9000`, `DEBUG`, `LOG_LEVEL`, `TZ` filtered deterministically — obvious noise costs 0 LLM calls.
* **Evidence matters:** Every finding retains `evidence{resolved_service, resolved_image, is_internal, reference_type, related_config, filtering_signals, volume_targets}` + `reason`.
* **Confidence first-class:** `JudgeResult` → `Dependency` → `Graph` edge `data.confidence` → `Report` finding `confidence: 0.9` — never dropped.
* **Resource-based, not service-to-service:** `orders → DB_HOST=postgres ← reports`, `api → shared-data ← worker`. Never `orders — reports` (falsely implies a call). Distinct `service` vs `resource` nodes.
* **Provider-agnostic, model hidden:** Prompt `build_judge_prompt` is model-agnostic. `GeminiJudgeClient gemini-3.7-flash/3.1-flash-lite` (google-genai) and `OpenRouterJudgeClient nvidia/nemotron-3-ultra-550b-a55b` (openai SDK) are pluggable via `JudgeClient` protocol. `thinking` low `1024` / medium `4096` dynamically via `set_thinking_level()`. `model` stored privately (`_model`, `cache.json`, `report.log.json`) and omitted from external `Dependency.to_dict()`, `graph.json`, `report.json`.
* **Deterministic + cached:** Same `DependencyModel` → same `cache_key sha256` → same `graph {"nodes","edges"}` IDs + same `report` sorting. Re-runs reuse `cache.json`.

---

## Ground-Truth Fixtures (Deliberately Messy)

Fixtures prove parsing of real-world noise (`env_file` string vs list, `${VAR}` interpolation, `common.env`, `image`).

| Fixture | Discovery | Filtering | Judge (real) | Graph |
|---|---|---|---|---|
| **shared_env** `fixtures/shared_env/` (`env_file: common.env`, `${DB_HOST}`, `${DB_NAME:-orders}`, `postgres:15` + `.env DB_HOST=shared-db` + `common.env DB_NAME=orders`) | 3: `DB_HOST`/`DB_NAME`/`SHARED_EXTRA` | 2 kept (`DB_HOST`/`DB_NAME` external, `related_config` bounded, `same_value true`) | 2 `meaningful 0.90` (both providers) | 4 nodes (2 svc + 2 res), 4 edges |
| **shared_volume** `fixtures/shared_volume/` (`shared-data:/data` + `${DATA_PATH}`) | 2: `shared-data` + `DATA_PATH` | 1 kept (`shared-data` `named_volume` `is_internal true` `volume_targets /data`) | 1 `meaningful 0.95` | 3 nodes, 2 edges |
| **near_miss** `fixtures/near_miss/` (`PORT 8000≠9000`, `APP_ENV`, `SHARED_NOISE`) | 3: `PORT` (value None, different), `APP_ENV`, `SHARED_NOISE` | 0 kept (generic + different-values filtered) | 0 calls | 0 nodes, 0 edges |

---

## Installation & Keys

```bash
git clone <repo> && cd Blindspot
pip install -r requirements.txt   # pyyaml, python-dotenv, networkx, matplotlib, google-genai, openai
# .env is gitignored, fixtures/**/.env is tracked
echo GEMINI_API_KEY=AQ.Ab8... >> .env
echo OPENROUTER_API_KEY=sk-or-v1-... >> .env
# auto picks OPENROUTER if present else GEMINI; switch via --provider
```

---

## Usage — One Command on One or More Repos

**Single repo (fixture or any clone):**
```bash
PYTHONPATH=src python -m blindspot.cli fixtures/shared_env --out out --thinking low
# out/shared_env/report.json   (machine: summary{total, meaningful, services, resources} + findings[])
# out/shared_env/report.md     (human: ## 1. orders <-> reports through DB_HOST=shared-db -- confidence 0.90 meaningful + Resolution + Related + Filtering)
# out/shared_env/graph.json    (React Flow DATA {"nodes":[{"id":"service:orders","type":"service"}, {"id":"resource:env_var:DB_HOST=shared-db",...}], "edges":[{"source":"service:orders","target":"resource:...","data":{"confidence":0.9}}]} bipartite, dedup, model hidden)
# out/shared_env/report.log.json (internal: provider, model, cache_key)
# cache.json (verdict cache, hit? reuse : LLM -> store, key = sha256(cache_key_dict))
```

**Multiple repos (including real OSS clone):**
```bash
git clone https://github.com/<small-multi-service-repo> /tmp/real
PYTHONPATH=src python -m blindspot.cli /tmp/real --out out --provider openrouter --thinking low
PYTHONPATH=src python -m blindspot.cli fixtures/shared_env fixtures/shared_volume /tmp/real --out out --cache cache.json
# Summary table: repo  cand  pkgs  deps  mean  nodes  edges
```

**Options:**
```bash
PYTHONPATH=src python -m blindspot.cli --help
# --compose docker-compose.yml  explicit file (default: auto-find docker-compose.yml|compose.yml via rglob)
# --provider auto|openrouter|gemini
# --thinking none|low|medium|high  (low 512 tokens cheap, medium 1024)
# --cache cache.json  (use 'none' to disable)
# --all  include coincidental/uncertain in graph/report (default: meaningful_only)
# --out out  root -> out/<repo>/report.json+report.md+graph.json
```

**Reading results:**
```bash
cat out/shared_env/report.md
cat out/shared_env/report.json | head -n 40
cat out/shared_env/graph.json | head -n 40
cat out/shared_env/report.log.json   # internal model/provider
```

**Determinism & cost:** Same repo → same IDs (`sorted` + `sha256`). `near_miss` → 0 LLM calls. Interesting candidate → 1 call each, cached.

**Manual stages (without CLI):**
```bash
pytest -v   # 61 tests: test_parser 32 + test_discovery 8 + test_filtering 8 + test_graph 13
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([pkg.to_dict() for pkg in build_evidence_packages(discover_candidates(p), p)])"
```

---

## Graph DATA Contract — React Flow Ready

Stage 6 produces provider-agnostic data, not an image. Frontend handles layout/zoom/pan/selection/evidence panels.

```json
{
  "nodes": [
    {"id": "service:orders", "type": "service", "data": {"name": "orders"}},
    {"id": "resource:env_var:DB_HOST=postgres", "type": "resource", "data": {"name": "DB_HOST=postgres", "resource_type": "env_var", "value": "postgres"}}
  ],
  "edges": [
    {"id": "service:orders->resource:env_var:DB_HOST=postgres", "source": "service:orders", "target": "resource:env_var:DB_HOST=postgres", "data": {"confidence": 0.93}}
  ]
}
```

* Bipartite `Service ↔ Resource` only (`orders → DB_HOST=postgres ← reports`), never `service→service`.
* Dedup by `resource_type:resource[=value]` (`env_var:REDIS ≠ named_volume:REDIS`), multiple resources between same services kept separate, confidence preserved, model never in nodes/edges, deterministic `sorted` IDs, `networkx` optional internally.

---

## Report Format

`report.json`:
```json
{
  "summary": {"total": 2, "meaningful": 2, "coincidental": 0, "uncertain": 0, "reported": 2, "services": 2, "resources": 2},
  "graph_summary": {"nodes": 4, "edges": 4, "service_nodes": 2, "resource_nodes": 2},
  "generated_at": "2026-09-04T15:43:31Z",
  "findings": [{
    "service_a": "orders", "service_b": "reports", "resource": "DB_HOST", "resource_type": "env_var", "value": "shared-db",
    "evidence": {"resolved_service": null, "is_internal": false, "reference_type": "external", "related_config": {"orders": {"DB_HOST": "shared-db"}}, "filtering_signals": {"generic_variable": false, "same_value": true}},
    "verdict": "meaningful", "confidence": 0.9, "reason": "Both share same DB host + DB_NAME..."
  }]
}
```

`report.md` renders each finding as `## 1. orders <-> reports through DB_HOST=shared-db (env_var) -- confidence 0.90 meaningful` + `Reason` + `Resolution: 'shared-db' -> external` + `Related config (bounded): orders: ...` + `Filtering: generic_variable=false ...`.

Model hidden externally — `report.log.json` + `cache.json` retain provider for audit.

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
│   ├── filtering.py (GENERIC_ENV_KEYS, EvidencePackage, bounded resolution)
│   ├── judge.py (JudgeResult, GeminiJudgeClient, OpenRouterJudgeClient, build_judge_prompt, cache.json, failsafe)
│   ├── model.py (Dependency, DependencyModel, model hidden)
│   ├── graph.py (GraphNode/Edge/Data, build_graph DATA)
│   ├── report.py (ReportFinding/Data, build_report)
│   └── cli.py (one-command Parse->Report for one/many repos)
└── tests/ (test_parser 32, test_discovery 8, test_filtering 8, test_graph 13)
```

---

## Technology

Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` (optional), `google-genai==0.8.0`, `openai==1.102.0`. Docker optional (read compose as text). Thinking `low 1024 → 512 tokens` / `medium 4096 → 1024` via `set_thinking_level()`.

---

## Documentation

* `AGENTS.md` — hybrid architecture (§3 bounded evidence, §4 one call/candidate, §5 service-to-resource, §6 React Flow DATA, §7 Report)
* `STATE.md` — Stages 1–7 DONE (100% code), 61 tests
* `DECISIONS.md` — D-021 hybrid, D-022 image, D-023 bounded evidence, D-025 provider-agnostic judge, D-026 model hidden, D-027 Graph DATA, D-028 Report+CLI

This is the finished BlindSpot — run `PYTHONPATH=src python -m blindspot.cli --help` to start.
