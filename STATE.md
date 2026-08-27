# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-08-27
**Branch:** `main` (no commits yet)
**Status:** `Initialization` — architecture defined, no code implemented

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git init` done, no commits, untracked `AGENTS.md` + `.opencode/` |
| **Architecture Doc** | `AGENTS.md` created 2026-08-27, defines 7-stage pipeline + Tier 1/2 scope |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model set to `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | Empty — no `src/`, `requirements.txt`, `pyproject.toml` yet |
| **Tests** | No synthetic repos, no near-miss test case yet |
| **Docs** | `STATE.md`, `DECISIONS.md`, `HANDOFF.md` initialized (this file) |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** (`docker-compose.yml` + `.env` → internal model) | `Not Started` | Needs `pyyaml` + `python-dotenv` parser. First code priority. |
| 2 | **Candidate Discovery** (shared env vars, shared volumes) | `Not Started` | Depends on Stage 1 |
| 3 | **Candidate Filtering** (evidence + near-miss filtering, e.g. `PORT`) | `Not Started` | Depends on Stage 2 |
| 4 | **LLM Judge** (judge pre-extracted candidates only) | `Not Started` | Keep input narrow, test consistency (run >1x) |
| 5 | **Dependency Model** (`service_a`, `service_b`, `resource`, `resource_type`, `evidence`, `judge_result`, `confidence`) | `Not Started` | Schema to be defined |
| 6 | **Graph** (`networkx` + `matplotlib`) | `Not Started` | Primary demo artifact |
| 7 | **Report** (human-readable explanations) | `Not Started` | Depends on Stage 5 |

**Overall Tier 1:** `0%` — not started
**Tier 2 (AST + DB table detection):** `Blocked` — do not start until Tier 1 demoable

---

## 3. Repo Structure (Actual)

```
Blindspot/
├── AGENTS.md              # architecture — 7 stages, principles
├── STATE.md               # this file
├── DECISIONS.md           # architectural decisions
├── HANDOFF.md             # next-agent handoff
├── .git/                  # no commits yet
└── .opencode/
    ├── package.json       # @opencode-ai/plugin 1.18.23
    └── skills/
```

**Missing / Expected Next:**
- `src/blindspot/` or `blindspot/` package
- `requirements.txt` / `pyproject.toml` (`pyyaml`, `python-dotenv`, `networkx`, `matplotlib`)
- `tests/` + `tests/synthetic/` + near-miss fixtures
- `README.md`
- `.gitignore` (Python + venv)

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `ast` (Tier 2 only)
- **Docker:** Not required for tool (reads compose as text)
- **Model:** `opencode/muse-spark-1.2-contributor-free` (global default)

---

## 5. Development Priorities (from AGENTS.md) — Order Matters

1. Synthetic test repositories ⬅ **NEXT**
2. Config parser
3. Candidate discovery
4. Candidate filtering
5. LLM judgment layer
6. Dependency model
7. Graph output
8. Real-world repo validation (1 small OSS multi-service repo)
9. Tier 2 AST analysis only if time allows

---

## 6. Recent Activity

- 2026-08-27: Initialized `AGENTS.md` with full architecture
- 2026-08-27: Set global opencode model to `opencode/muse-spark-1.2-contributor-free`
- 2026-08-27: Created `STATE.md` / `DECISIONS.md` / `HANDOFF.md`

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
