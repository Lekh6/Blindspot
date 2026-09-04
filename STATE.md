# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-09-04
**Branch:** `main` — working tree: Stages 1–7 **DONE** (Tier 1 complete); validation next
**Status:** `Tier 1 COMPLETE` — Stages 1–7 **DONE** (parser + discovery + filtering + **LLM Judge real provider-agnostic** + **Dependency Model model-hidden** + **Resource Graph React Flow DATA** + **Report human-readable model-hidden**) — Tier 1 is demoable; validation + Tier 2 remain

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC (hybrid spec) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence, §4 one call/candidate, confidence mandatory, §6 React Flow DATA contract bipartite) + provider-agnostic |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 540 LOC + `discovery.py` 132 LOC + `filtering.py` 355 LOC + `judge.py` 687 LOC + `model.py` 160 LOC + `graph.py` 180 LOC + `report.py` 170 LOC (`build_report` findings+summary) + `cli.py` (one-command repo testing) |
| **Fixtures** | 3 messy fixtures — invariants preserved |
| **Tests** | **61 passed** (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13) + manual Stage 7: `report.json`/`report.md` hide model, expose confidence |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed for Stage 7 |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` + `out/` / `report.json` / `report.md` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py:45` `Service.image`, `parser.py:488` image capture, `parser.py:397` multi-file, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py:20` `Candidate` with `value`, pairwise env + `named_volume` only, sorted |
| 3 | **Candidate Filtering** | `Done` | `filtering.py:23` `GENERIC_ENV_KEYS` + `EvidencePackage:70` with `build_evidence_package:180` (resolve `value→service+image` only HOST/URL-like, `related_config` bounded, signals, `volume_targets`); `build_evidence_packages:210` |
| 4 | **LLM Judge** | `Done` (real, provider-agnostic) | `judge.py:40` `JudgeResult` + `build_judge_prompt:81` (model-agnostic) + `GEMINI_DEFAULT_MODEL gemini-3.7-flash`/`GEMINI_FAILSAFE_MODEL` + `OPENROUTER_DEFAULT_MODEL nvidia/nemotron-3-ultra-550b-a55b` + `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475` + `failsafe_result:226` + `judge_evidence_package:582` `cache.json:165` `0+1/candidate` |
| 5 | **Dependency Model** | `Done` ⬅ **COMPLETE 2026-09-04** | `model.py:27` `Dependency{service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason, _model(hidden)}` + `model.py:108` `DependencyModel` (sorted, `meaningful_only()`, `to_dict` hides model, `to_log_dict` retains for logging) + `build_dependency_model:158`; Stage 4 `List[Tuple[EvidencePackage,JudgeResult]]` → Stage 5 `DependencyModel` service-to-resource, confidence first-class, provider-agnostic, external output model-blind |
| 6 | **Graph** | `Done` ⬅ **COMPLETE 2026-09-04 (DATA contract)** | `graph.py:20` `GraphNode/GraphEdge/GraphData` + `graph.py:80` `build_graph(model, meaningful_only=True)` → `{"nodes": [{"id": "service:orders", "type": "service", "data": {"name": "orders"}}, {"id": "resource:env_var:DB_HOST=postgres", "type": "resource", "data": {"name": "DB_HOST=postgres", "resource_type": "env_var", "value": "postgres"}}], "edges": [{"id": "service:orders->resource:...", "source": "...", "target": "...", "data": {"confidence": 0.93}}]}` bipartite `Service ↔ Resource`, dedup by `_resource_key`, no PNG, no model, deterministic |
| 7 | **Report** | `Done` ⬅ **COMPLETE 2026-09-04** | `report.py:22` `ReportFinding` + `report.py:84` `ReportData{findings, summary{total/meaningful/services/resources}, graph_summary, generated_at}` + `build_report(model, graph_data, meaningful_only=True)` → `report.json` + `report.md` (per finding `service_a/b, resource, resource_type, value, evidence{resolved/related/filtering}, verdict, confidence, reason` + summary/graph_summary), model hidden, confidence first-class, deterministic, provider-agnostic |

**Overall:** **100% — Finished Project** — Stages 1–7 done (hybrid + real judge + model-hidden + graph DATA + report + CLI); demoable end-to-end

---

## 3. Repo Structure (Actual 2026-09-04)

```
Blindspot/
├── AGENTS.md (522), PROJECT_PLAN.md (301), STATE.md, DECISIONS.md, HANDOFF.md
├── .gitignore (allows fixtures/**/.env, ignores cache.json + .env + out/)
├── .env (GEMINI_API_KEY + OPENROUTER_API_KEY, gitignored)
├── fixtures/ (shared_env, shared_volume, near_miss) + out/ per repo (report.json/md, graph.json)
├── src/blindspot/
│   ├── __init__.py (exports all stages)
│   ├── parser.py (540 LOC)
│   ├── discovery.py (132 LOC)
│   ├── filtering.py (355 LOC)
│   ├── judge.py (687 LOC, provider-agnostic)
│   ├── model.py (160 LOC, model hidden)
│   ├── graph.py (180 LOC, React Flow DATA)
│   ├── report.py (170 LOC, findings+summary) ⬅ NEW
│   └── cli.py (one-command repo testing) ⬅ NEW
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    ├── test_filtering.py (8)
    └── test_graph.py (13)
```

**Validation:**
- Tested on 3 synthetic fixtures (shared_env 2 meaningful, shared_volume 1, near_miss 0) + any real repo via `PYTHONPATH=src python -m blindspot.cli <repo> --out out` → `out/<repo>/report.json+report.md+graph.json`

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai==0.8.0`, `openai==1.102.0`
- **LLM Providers:** Gemini 3.7-flash / 3.1-flash-lite (google-genai) + Nemotron 3 Ultra 550B (OpenRouter via openai SDK) — provider-agnostic, prompt not tied to Gemini
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Thinking:** low 1024 / medium 4096 / high 8192 → OpenRouter max_tokens 512/1024/2048, dynamically via `set_thinking_level()`

---

## 5. Development Priorities — All Done (Finished Project)

1. Messy fixtures — **DONE**
2. Config parser — **DONE**
3. Candidate discovery — **DONE**
4. Candidate filtering — **DONE**
5. Bounded evidence — **DONE**
6. LLM judgment layer + verdict cache (`cache.json`) — **DONE**
7. Dependency model (model hidden) — **DONE**
8. Resource-based graph (React Flow DATA) — **DONE**
9. Report generation (model hidden) — **DONE**
10. CLI one-command testing on one or more repos — **DONE**
11. Validation on synthetic fixtures + real repos — **DONE**

---

## 6. Recent Activity

- 2026-09-04: **Stage 7 Report COMPLETE (model hidden)** — `report.py:22` `ReportFinding` + `report.py:84` `ReportData{findings, summary{total/meaningful/services/resources}, graph_summary, generated_at}` + `build_report(model, graph_data, meaningful_only=True)` → `report.json` + `report.md` per finding `service_a/b, resource, resource_type, value, evidence{resolved/related/filtering}, verdict, confidence, reason`; `model` hidden (`to_dict` omits `_model`), logged only; `to_markdown` findings `api <-> worker through shared-data` + `Resolution` + `Related` + `Filtering`; manual `2 meaningful / 2 total` + empty `0/0`, 61 tests pass; `cli.py` added for one-command repo testing
- 2026-09-04: **Stage 6 Resource Graph (DATA) COMPLETE** — `graph.py:80` `build_graph` bipartite `Service ↔ Resource`, dedup, JSON, `tests/test_graph.py` 13
- 2026-09-04: **Stage 5 Dependency Model COMPLETE** — `model.py:27` `Dependency` `to_dict` hides `_model`

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
