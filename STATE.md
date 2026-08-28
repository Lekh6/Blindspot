# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-08-28
**Branch:** `main` — 1 commit (`3859ca1`), working tree has uncommitted updates (parser env_file/multi-file + new plan)
**Status:** `Tier 1 In Progress` — Stage 1 fixtures + Stage 2 parser done (with env_file and multi-file merge), stages 3-7 not started

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, 1 commit; `AGENTS.md` updated to final architecture 2026-08-28 |
| **Architecture Doc** | `AGENTS.md` = final 7-stage pipeline (resource-based graph, verdict caching, K8s Tier 2); `PROJECT_PLAN.md` added (final pace + pitch) |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `src/blindspot/parser.py` (523 LOC) — 5 layers, env mapping/list, `${VAR}`/`$VAR`/`:-default` preserved, volumes named/bind/anonymous, `env_file` (string/list, `{path,required}`), multi-file `Union[Path,List[Path]]` deep-merge |
| **Fixtures** | `fixtures/shared_env`, `fixtures/shared_volume`, `fixtures/near_miss` — valid but **not yet deliberately messy** (need comments, `${VAR}` interpolation, `env_file` usage per new plan §7 Phase 1) |
| **Tests** | `tests/test_parser.py` 32 passed; no candidate/filter/judge/graph tests yet |
| **Docs** | `STATE.md`, `DECISIONS.md`, `HANDOFF.md` need catch-up; `README.md` still describes old Stage 1 fixtures |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** (`docker-compose.yml` + `.env` + supported `env_file` + `${VAR}`) | `Done` (needs messy-fixture refresh) | `parser.py:85` `load_env_file` preserves `""` for `VAR=`, `parser.py:352` `_load_service_env_files` merges env_file (explicit env overrides per Docker spec), `parser.py:108` `_resolve_value`, multi-file merge `parser.py:397` |
| 2 | **Candidate Discovery** (shared env config, shared named volumes) | `Not Started` | Depends on Stage 1; Tier 1 only, K8s ConfigMap/Secret candidates are Tier 2 |
| 3 | **Candidate Filtering** (deterministic heuristics, evidence, conservative near-miss e.g. `PORT`) | `Not Started` | Must filter `PORT`/`DEBUG`/logging noise before LLM |
| 4 | **LLM Judge** (narrow pre-extracted candidate, consistency >1 run, `cache.json`) | `Not Started` | Cache key = candidate+evidence, not just var/value |
| 5 | **Dependency Model** (`service_a`, `service_b`, `resource`, `resource_type`, `evidence`, `judge_result`, `confidence`) + service-to-resource (not direct service-service edge) | `Not Started` | Schema to preserve provenance |
| 6 | **Graph** (`networkx` + `matplotlib`, **resource nodes** bipartite `orders→DB_HOST←reports`) | `Not Started` | Primary demo artifact, distinct visual treatment |
| 7 | **Report** (human-readable, explains resource + evidence + judgment/confidence) | `Not Started` | Depends on Stage 5 |

**Overall Tier 1:** ~25% — parser + clean fixtures done; filtering/judge/model/graph/report + messy fixtures + real-world validation remain
**Tier 2 (Kubernetes ConfigMap/Secret/shared volumes):** `Blocked` — do not start until Tier 1 demoable; **AST discontinued** per new architecture

---

## 3. Repo Structure (Actual 2026-08-28)

```
Blindspot/
├── AGENTS.md              # final architecture — 7 stages, resource graph, K8s Tier 2
├── PROJECT_PLAN.md        # final project plan — pace 1-2h/day, scope tiers, build order
├── STATE.md               # this file
├── DECISIONS.md           # architectural decisions (needs D-011.. superseding AST)
├── HANDOFF.md             # next-agent handoff (needs refresh)
├── .git/                  # main @ 3859ca1 + uncommitted AGENTS.md/parser.py/PROJECT_PLAN.md
├── fixtures/
│   ├── shared_env/docker-compose.yml
│   ├── shared_volume/docker-compose.yml
│   └── near_miss/docker-compose.yml
├── src/blindspot/
│   ├── __init__.py
│   └── parser.py          # 523 LOC, env_file + multi-file merge
├── tests/
│   ├── conftest.py
│   └── test_parser.py     # 32 tests
├── requirements.txt       # pyyaml, python-dotenv, networkx, matplotlib
└── .opencode/
```

**Missing / Expected Next:**
- Messy fixture refresh (comments, `${VAR}`, `env_file` in fixtures)
- `src/blindspot/discovery.py`, `filtering.py`, `judge.py`, `model.py`, `graph.py`, `report.py`
- `cache.json` (LLM verdict cache, gitignored)
- Real-world repo clone + validation

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`
- **No AST dependency** — Tier 2 uses YAML parsing for Kubernetes manifests (per AGENTS.md Current Technology)
- **Docker:** Not required (reads compose as text)
- **Model:** `opencode/muse-spark-1.2-contributor-free` (global default)

---

## 5. Development Priorities (from AGENTS.md — Order Matters)

1. Deliberately messy synthetic test repositories (refresh fixtures) ⬅ **NEXT**
2. Config parser — done, but needs re-validation against messy fixtures
3. Candidate discovery
4. Candidate filtering and evidence construction
5. LLM judgment layer + verdict cache (`cache.json`)
6. Dependency model (service-to-resource)
7. Resource-based graph output
8. Report generation
9. Real-world repository validation (1 small OSS multi-service repo)
10. Tier 2 Kubernetes support only if time allows

---

## 6. Recent Activity

- 2026-08-28: Applied final `PROJECT_PLAN.md` + final `AGENTS.md` (committed ground truths) — resource-based graph, verdict caching, K8s Tier 2 replaces AST, env_file + interpolation required, messy fixtures required
- 2026-08-28: `parser.py` updated — `env_file` (string/list + `{path,required}`), explicit env overrides, `""` preserved, multi-file `Union[Path,List[Path]]` deep-merge (env updated, volumes appended/unioned); comment clarified for LLM layer
- 2026-08-28: Prior commit `3859ca1` — Stage 1 .venv + fixtures + Stage 2 parser (yaml/.env/env normalize/volume normalize/Project model), 32 tests passing
- 2026-08-27: Initialized `AGENTS.md` / `STATE.md` / `DECISIONS.md` / `HANDOFF.md`, set global model

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
