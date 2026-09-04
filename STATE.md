# STATE.md — Current Project State

> Single source of truth for where BlindSpot stands. Update this file on every meaningful change.

**Last Updated:** 2026-09-04
**Branch:** `main` — working tree: Stages 1–5 **DONE**; Stage 6 Graph next
**Status:** `Tier 1 In Progress` — Stages 1–5 **DONE** (parser `image` + discovery + filtering with bounded evidence + **LLM Judge real provider-agnostic** + **Dependency Model service-to-resource, model hidden from external output**); Stages 6–7 + real-world validation remain

---

## 1. Snapshot

| Area | State |
|------|-------|
| **Repo Init** | `git` on `main`, `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC (hybrid spec) |
| **Architecture Doc** | `AGENTS.md` = hybrid deterministic + LLM (§3 bounded evidence, §4 one call/candidate, confidence mandatory, cache hit/miss) + provider-agnostic |
| **Global Config** | `~/.config/opencode/opencode.jsonc` model `opencode/muse-spark-1.2-contributor-free` |
| **Codebase** | `parser.py` 540 LOC + `discovery.py` 132 LOC + `filtering.py` 355 LOC + `judge.py` 687 LOC (provider-agnostic) + `model.py` 160 LOC (`Dependency` + `DependencyModel`, model hidden) |
| **Fixtures** | 3 messy fixtures (`.env`/`common.env`, `${VAR}`/`env_file`, `image: postgres:15`) — invariants preserved |
| **Tests** | **48 passed** + manual Stage 4/5: shared_env 2→2 meaningful 0.9, shared_volume 1→meaningful, near_miss 0, external `to_dict` hides `model`, `to_log_dict` retains, 48 still pass |
| **Docs** | `STATE.md`/`HANDOFF.md`/`DECISIONS.md`/`README.md` refreshed for Stage 5 |
| **Gitignore** | `!fixtures/**/.env` + `!fixtures/**/common.env` + `cache.json` + `.env` (keys) ignored |

---

## 2. Seven-Stage Pipeline — Progress

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | **Parse + Normalize** | `Done` | `parser.py:45` `Service.image`, `parser.py:488` image capture, `parser.py:397` multi-file, traceable refs |
| 2 | **Candidate Discovery** | `Done` | `discovery.py:20` `Candidate` with `value`, pairwise env + `named_volume` only, sorted |
| 3 | **Candidate Filtering** | `Done` | `filtering.py:23` `GENERIC_ENV_KEYS` + `EvidencePackage:70` with `build_evidence_package:180` (resolve `value→service+image` only HOST/URL-like, `related_config` bounded, signals, `volume_targets`); `build_evidence_packages:210` |
| 4 | **LLM Judge** | `Done` (real, provider-agnostic) | `judge.py:40` `JudgeResult` + `build_judge_prompt:81` (model-agnostic) + `GEMINI_DEFAULT_MODEL gemini-3.7-flash`/`GEMINI_FAILSAFE_MODEL` + `OPENROUTER_DEFAULT_MODEL nvidia/nemotron-3-ultra-550b-a55b` + `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475` + `failsafe_result:226` + `judge_evidence_package:582` `cache.json:165` `0+1/candidate` |
| 5 | **Dependency Model** | `Done` ⬅ **COMPLETE 2026-09-04** | `model.py:27` `Dependency{service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason, _model(hidden)}` + `model.py:108` `DependencyModel` (sorted, `meaningful_only()`, `to_dict` hides model, `to_log_dict` retains for logging) + `build_dependency_model:158`; Stage 4 `List[Tuple[EvidencePackage,JudgeResult]]` → Stage 5 `DependencyModel` service-to-resource, confidence first-class, provider-agnostic, external output model-blind |
| 6 | **Graph** | `Not Started` ⬅ **NEXT** | Resource-based `Service ↔ Resource` |
| 7 | **Report** | `Not Started` | Expose evidence + confidence |

**Overall Tier 1:** ~85% — Stages 1–5 done (hybrid + real judge + dependency model model-blind); stages 6–7 + real-world validation remain
**Tier 2 (Kubernetes):** `Blocked` — same pipeline, after Tier 1

---

## 3. Repo Structure (Actual 2026-09-04)

```
Blindspot/
├── AGENTS.md (522), PROJECT_PLAN.md (301), STATE.md, DECISIONS.md, HANDOFF.md
├── .gitignore (allows fixtures/**/.env, ignores cache.json + .env keys)
├── .env (GEMINI_API_KEY + OPENROUTER_API_KEY, gitignored)
├── fixtures/
│   ├── shared_env/ (yml + .env + common.env, image postgres:15) # 3 → 2 pkgs → 2 meaningful 0.9
│   ├── shared_volume/ (yml + .env)          # 2 → 1 pkg → 1 meaningful 0.95
│   └── near_miss/ (yml + .env + common.env) # 3 → 0 pkgs → 0 calls
├── src/blindspot/
│   ├── __init__.py (exports Candidate/EvidencePackage/JudgeResult/Gemini+OpenRouter/Dependency/DependencyModel)
│   ├── parser.py (540 LOC)
│   ├── discovery.py (132 LOC)
│   ├── filtering.py (355 LOC)
│   ├── judge.py (687 LOC, provider-agnostic)
│   └── model.py (160 LOC, Dependency + DependencyModel, model hidden) ⬅ NEW
└── tests/
    ├── test_parser.py (32)
    ├── test_discovery.py (8)
    └── test_filtering.py (8)
```

**Missing / Expected Next:**
- `src/blindspot/graph.py` ⬅ NEXT (Resource-based `Service ↔ Resource`), `report.py`
- Tests for `model.py` (Stage 5 hides model) and `EvidencePackage` resolution

---

## 4. Technology

- **Required:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, `google-genai==0.8.0`, `openai==1.102.0`
- **LLM Providers:** Gemini 3.7-flash / 3.1-flash-lite (google-genai) + Nemotron 3 Ultra 550B (OpenRouter via openai SDK) — provider-agnostic, prompt not tied to Gemini
- **No AST** — Tier 2 K8s via YAML
- **Docker:** Not required
- **Thinking:** low 1024 / medium 4096 / high 8192 → OpenRouter max_tokens 512/1024/2048, dynamically via `set_thinking_level()`

---

## 5. Development Priorities

1. Messy fixtures — **DONE**
2. Config parser — **DONE** (with `image`)
3. Candidate discovery — **DONE**
4. Candidate filtering — **DONE** (bounded evidence)
5. Bounded evidence validated — **DONE**
6. LLM judgment layer + verdict cache (`cache.json`) — **DONE (real, provider-agnostic, Gemini + Nemotron Ultra, failsafe, cache verified)**
7. Dependency model (verdict/confidence/reason, model hidden) — **DONE** ⬅ **COMPLETE 2026-09-04**
8. Resource-based graph ⬅ **NEXT**
9. Report generation (evidence + confidence)
10. Real-world validation
11. Tier 2 Kubernetes

---

## 6. Recent Activity

- 2026-09-04: **Stage 5 Dependency Model COMPLETE (model hidden)** — `model.py:27` `Dependency{service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason, _model(hidden), cache_key}` + `model.py:108` `DependencyModel{sorted, meaningful_only(), to_dict hides model, to_log_dict retains, from_judgments}` + `build_dependency_model:158`; `Stage 4 List[Tuple[EvidencePackage,JudgeResult]] → Stage 5 DependencyModel` service-to-resource, `model` stored privately, logged via `logging` + `cache.json`, omitted from external `to_dict` per user rule; manual: artificial DB_HOST/named_volume/REDIS all `meaningful`, fixtures `shared_env 2→2`, `shared_volume 1`, `near_miss 0`, external `to_dict` model leak `False`, `to_log_dict` retains; `__init__.py` exports `Dependency`/`DependencyModel`; 48 tests still pass
- 2026-09-04: **Stage 4 LLM Judge (real, provider-agnostic) COMPLETE** — `judge.py:31` `gemini-3.7-flash`/`3.1-flash-lite` + `judge.py:36` `nvidia/nemotron-3-ultra-550b-a55b` + `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475` (regex JSON for Nemotron) + `failsafe_result:226` + `judge_evidence_package:582`; `.env` keys gitignored; `google-genai==0.8.0`+`openai==1.102.0`; sampleruns meaningful 0.9-0.95
- 2026-08-29: **Architecture modification** — `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC hybrid

---

## 7. How to Update This File

- After each feature/stage completion, flip the status in §2 and update §1 snapshot
- Log activity in §6 with date + what changed
- Keep this file < 100 lines — details go in `HANDOFF.md` or code
