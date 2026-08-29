# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-08-29
**Branch:** `main` — 3 commits ahead, working tree: Stage 3 evidence + Stage 4 judge (mock)
**Status:** `Tier 1 In Progress` — Stages 1–4 **DONE** (parser `image` + discovery + filtering with bounded evidence + **LLM Judge with mock + cache.json**); Stage 5 Dependency Model next

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, 3 commits; `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC (hybrid spec) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence, §4 one call/candidate, confidence mandatory, cache hit/miss) |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 540 LOC (`Service.image`) + `discovery.py` 132 LOC + `filtering.py` 355 LOC (`EvidencePackage` + `build_evidence_packages`) + `judge.py` 361 LOC (`JudgeResult`, `MockJudgeClient`, `build_judge_prompt`, `judge_evidence_packages` with `cache.json`) |
| **Fixtures** | 3 messy fixtures (`.env`/`common.env`, `${VAR}`/`env_file`, `image: postgres:15`) — invariants preserved |
| **Tests** | **48 passed**: `test_parser.py` 32 + `test_discovery.py` 8 + `test_filtering.py` 8 (judge validated manually via mock: shared_env 2 → 2 meaningful, shared_volume 1 → meaningful, near_miss 0 → 0 calls, cache hit verified) |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed for Stage 4 |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py:45` `Service.image`, `parser.py:488` image capture, `parser.py:397` multi-file, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py:20` `Candidate` with `value`, pairwise env + `named_volume` only, sorted |
| 3 | **Candidate Filtering** | `Done` | `filtering.py:23` `GENERIC_ENV_KEYS` + `EvidencePackage:70` with `build_evidence_package:180` (resolve `value→service+image` only HOST/URL-like, `related_config` bounded, signals, `volume_targets`); `build_evidence_packages:210` |
| 4 | **LLM Judge** | `Done` (mock) ⬅ **REFINED 2026-08-29** | `judge.py:18` `JudgeResult{verdict: meaningful|coincidental|uncertain, confidence, reason, model}` + `judge.py:60` `build_judge_prompt` (A/B, SHARED CONFIG, VALUES, RESOLUTION, RELATED, FILTERING) + `judge.py:160` `MockJudgeClient` + `judge.py:270` `judge_evidence_package` with `cache.json:85` (`sha256(cache_key_dict)`) `0+1/candidate`, validated mock on fixtures + cache hit, real LLM pluggable |
| 5 | **Dependency Model** | `Not Started` ⬅ **NEXT** | Must store `verdict/confidence/reason` + `EvidencePackage` |
| 6 | **Graph** | `Not Started` | Resource-based `Service ↔ Resource` |
| 7 | **Report** | `Not Started` | Expose evidence + confidence |

**Overall Tier 1:** ~70% — Stages 1–4 done (hybrid bounded evidence + mock judge cached); stages 5–7 + real-world validation remain
**Tier 2 (Kubernetes):** `Blocked` — same pipeline, after Tier 1

---

## 3. Repo Structure (Actual 2026-08-29)

```
Blindspot/
├── AGENTS.md (522), PROJECT_PLAN.md (301), STATE.md, DECISIONS.md, HANDOFF.md
├── .gitignore (allows fixtures/**/.env, ignores cache.json)
├── fixtures/
│   ├── shared_env/ (yml + .env + common.env, image postgres:15) # 3 → 2 pkgs → 2 meaningful (mock)
│   ├── shared_volume/ (yml + .env)          # 2 → 1 pkg → 1 meaningful
│   └── near_miss/ (yml + .env + common.env) # 3 → 0 pkgs → 0 calls
├── src/blindspot/
│   ├── __init__.py (exports Candidate/EvidencePackage/JudgeResult/MockJudgeClient)
│   ├── parser.py (540 LOC, +image)
│   ├── discovery.py (132 LOC)
│   ├── filtering.py (355 LOC, EvidencePackage + filtering)
│   └── judge.py (361 LOC, Judge + cache) ⬅ NEW
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    └── test_filtering.py (8)
```

**Missing / Expected Next:**
- `src/blindspot/model.py` ⬅ NEXT (Dependency with verdict/confidence), `graph.py`, `report.py`
- Tests for `judge.py` (EvidencePackage → verdict) and `EvidencePackage` resolution (DB_HOST=postgres → postgres:16)

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Model:** `opencode/muse-spark-1.2-contributor-free` (mock used, real LLM pluggable)

---

## 5. Development Priorities

1. Messy fixtures — **DONE**
2. Config parser — **DONE** (with `image`)
3. Candidate discovery — **DONE**
4. Candidate filtering — **DONE** (bounded evidence)
5. Bounded evidence validated — **DONE**
6. LLM judgment layer + verdict cache (`cache.json`) — **DONE (mock, cache verified)** ⬅ **JUST DONE**
7. Dependency model (verdict/confidence/reason) ⬅ **NEXT**
8. Resource-based graph
9. Report generation (evidence + confidence)
10. Real-world validation
11. Tier 2 Kubernetes

---

## 6. Recent Activity

- 2026-08-29: **Stage 4 LLM Judge (mock)** — `judge.py:18` `JudgeResult` (`meaningful|coincidental|uncertain` + `confidence` mandatory + `reason`) + `judge.py:60` `build_judge_prompt` (A/B, SHARED CONFIG, VALUES, RESOLUTION, RELATED, FILTERING per §5) + `judge.py:85` `_cache_key_for_package` (`sha256(cache_key_dict)`) + `judge.py:270` `judge_evidence_package` (0+1/candidate, `cache.json` hit? reuse : LLM → store) + `MockJudgeClient:160` (named_volume/compose_service→meaningful, generic→coincidental); manual mock: `shared_env` 2→2 meaningful, `shared_volume` 1→meaningful, `near_miss` 0→0, second run with `FixedJudgeClient` hit cache (mock model retained), cache key diff verified; `.gitignore:39` `cache.json`, `__init__.py:1` exports `JudgeResult`; 48 tests still pass
- 2026-08-29: **Architecture modification** — `AGENTS.md:1` 522 LOC + `PROJECT_PLAN.md:1` 301 LOC hybrid
- 2026-08-29: **Stage 3 refinement** — `Service.image` + `EvidencePackage` with HOST/URL-like resolution, `host:port` split, bounded `DB_*` related

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
