# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-08-28
**Branch:** `main` — 1 commit (`3859ca1`), working tree: 4 modified + 5 untracked + 2 new files (`discovery.py`, `test_discovery.py`)
**Status:** `Tier 1 In Progress` — Stages 1–2 **DONE** (messy fixtures + parser + candidate discovery), Stage 3 filtering next

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, 1 commit; `AGENTS.md` final, `PROJECT_PLAN.md` added |
| **Architecture Doc** | `AGENTS.md` = final 7-stage pipeline (resource graph, `cache.json`, K8s Tier 2); `PROJECT_PLAN.md` = pace 1–2h/day |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 523 LOC + `discovery.py` 108 LOC (`Candidate` + `discover_candidates`) — env `env_file`+`Union[List]`+`${VAR}`, volumes, pairwise env+`named_volume` discovery |
| **Fixtures** | 3 messy fixtures with `.env`/`common.env`, comments, `${VAR}`/`env_file` — invariants preserved |
| **Tests** | **40 passed**: `test_parser.py` 32 + `test_discovery.py` 8 (messy fixture checks for `DB_HOST`/`shared-data`/`PORT` plus unit pairs); all deterministic |
| **Docs** | `STATE.md`/`HANDOFF.md` refreshed; `DECISIONS.md` needs D-017/018; `README.md` still old |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` added |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** (`docker-compose.yml` + `.env` + supported `env_file` + `${VAR}`) | `Done` | `parser.py:85` `""` preserved, `parser.py:352` env_file, `parser.py:108` resolve, `parser.py:397` multi-file |
| 2 | **Candidate Discovery** (shared env config, shared named volumes) | `Done` | `discovery.py:19` `Candidate` (`service_a/b`, `resource`, `resource_type`, `evidence`) + `discovery.py:35` `discover_candidates`: pairwise sorted, env (same key→candidate, evidence notes value equality) + `named_volume` only (bind/anon ignored); 8 tests |
| 3 | **Candidate Filtering** (deterministic heuristics, conservative) | `Not Started` ⬅ **NEXT** | Filter `PORT`/`DEBUG`/`LOG_LEVEL` before LLM, build evidence |
| 4 | **LLM Judge** (narrow candidate, `cache.json` `candidate+evidence` key) | `Not Started` | |
| 5 | **Dependency Model** (service-to-resource `evidence`/`judge_result`/`confidence`) | `Not Started` | |
| 6 | **Graph** (`networkx` + `matplotlib`, resource nodes) | `Not Started` | |
| 7 | **Report** (human-readable) | `Not Started` | |

**Overall Tier 1:** ~40% — Stages 1–2 done; stages 3–7 + real-world validation remain
**Tier 2 (Kubernetes):** `Blocked` — do not start until Tier 1 demoable

---

## 3. Repo Structure (Actual 2026-08-28)

```
Blindspot/
├── AGENTS.md              # final architecture
├── PROJECT_PLAN.md        # final plan
├── STATE.md               # this file
├── DECISIONS.md
├── HANDOFF.md
├── .gitignore             # allows fixtures/**/.env
├── fixtures/
│   ├── shared_env/ (yml + .env + common.env) # 3 messy, 3 candidates
│   ├── shared_volume/ (yml + .env)          # 2 candidates (1 vol + 1 env)
│   └── near_miss/ (yml + .env + common.env) # 3 candidates, PORT different values
├── src/blindspot/
│   ├── __init__.py        # exports Candidate/discover_candidates
│   ├── parser.py          # 523 LOC
│   └── discovery.py       # 108 LOC ⬅ NEW
├── tests/
│   ├── conftest.py
│   ├── test_parser.py     # 32
│   └── test_discovery.py  # 8 ⬅ NEW
└── requirements.txt
```

**Missing / Expected Next:**
- `src/blindspot/filtering.py` ⬅ NEXT, `judge.py`, `model.py`, `graph.py`, `report.py`
- `cache.json`, real-world repo, `README.md` refresh

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Model:** `opencode/muse-spark-1.2-contributor-free`

---

## 5. Development Priorities (from AGENTS.md — Order Matters)

1. Deliberately messy synthetic test repositories — **DONE**
2. Config parser — **DONE**
3. Candidate discovery — **DONE** (8 tests)
4. Candidate filtering and evidence construction ⬅ **NEXT**
5. LLM judgment layer + verdict cache (`cache.json`)
6. Dependency model (service-to-resource)
7. Resource-based graph output
8. Report generation
9. Real-world repository validation
10. Tier 2 Kubernetes support only if time allows

---

## 6. Recent Activity

- 2026-08-28: **Stage 2 Candidate Discovery** — `discovery.py:19` `Candidate` + `discovery.py:35` pairwise env (`env_var`, resource `key=value` when equal else `key`, evidence with values) + `named_volume` (`source` only, bind/anon ignored), sorted deterministic; `test_discovery.py` 8 tests (3 messy fixture + 5 unit); 40 total passed; `__init__.py` exports
- 2026-08-28: Phase 1 messy fixtures (comments/`${VAR}`/`env_file`, 5 env files, `.gitignore` fix, parser 523 LOC)
- 2026-08-28: Final `PROJECT_PLAN.md` + `AGENTS.md` (resource graph, caching, K8s)
- 2026-08-28: Commit `3859ca1` baseline
- 2026-08-27: Initialized docs, set global model

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
