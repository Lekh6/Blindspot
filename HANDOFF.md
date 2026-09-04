# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-09-04
**Current Phase:** Tier 1 — Stages 1–5 **DONE** (parser `image` + discovery + filtering with `EvidencePackage` + **LLM Judge real provider-agnostic** + **Dependency Model service-to-resource, model hidden from external output**) — **Stage 6 NEXT: Resource Graph**
**Current Branch:** `main` — working tree: Stage 5 complete

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence, §4 one call/candidate, confidence mandatory) + `PROJECT_PLAN.md` (hybrid diagram) + `STATE.md` §2, then this file.
2. **Stages 1–5 DONE:** `parser.py` 540 LOC, `discovery.py` 132 LOC, `filtering.py` 355 LOC (`EvidencePackage:70`), `judge.py` 687 LOC (`JudgeResult:40`, `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475`, `build_judge_prompt:81` provider-agnostic, `judge_evidence_packages:650` `cache.json:165`) + `model.py` 160 LOC (`Dependency:27` service-to-resource, `DependencyModel:108` sorted, `to_dict` hides `_model`, `to_log_dict` retains, `from_judgments:141`). **48 tests pass**. `shared_env` 3→2 pkgs→2 meaningful 0.9, `shared_volume` 2→1→meaningful, `near_miss` 3→0→0, artificial 3 pkgs all meaningful 0.9-0.95, external `to_dict` model leak `False`.
3. **Stages 4→5 now:** `List[Tuple[EvidencePackage,JudgeResult]]` → `DependencyModel.from_judgments()` → `Dependency{service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason, _model(hidden)}` service-to-resource, confidence first-class, model logged internally (`_model` + `cache_key` + `logging`) not in external `to_dict()` per user rule, provider-agnostic, `set_thinking_level()` low/medium.
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-025 provider-agnostic), `HANDOFF.md`.
5. `.env` gitignored, `!fixtures/**/.env` allowed, `cache.json` ignored.

---

## 2. Where We Left Off

- `AGENTS.md:1` 522 LOC + `PROJECT_PLAN.md:1` 301 LOC hybrid spec.
- **Parser:** `parser.py:45` `Service.image` + `parse_compose_file:488`/`505` + `_merge_projects:401` image override; `D-022`.
- **Filtering:** `filtering.py:70` `EvidencePackage` + `build_evidence_package:180` with HOST/URL-like guard, `host:port` split, `volume_targets`, `related_config` bounded; `D-023`.
- **Judge:** `judge.py:40` `JudgeResult` + `build_judge_prompt:81` (provider-agnostic) + `GEMINI_DEFAULT_MODEL`/`GEMINI_FAILSAFE_MODEL` + `OPENROUTER_DEFAULT_MODEL nvidia/nemotron-3-ultra-550b-a55b` + `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475` (regex for Nemotron `Here's a thinking...`) + `failsafe_result:226` + `judge_evidence_package:582` `cache.json:165` `0+1/candidate`; `.env` both keys; `google-genai==0.8.0`+`openai==1.102.0`; sampleruns meaningful 0.9-0.95; `D-025`.
- **Model:** `model.py:27` `Dependency{service_a/b, resource, resource_type, value, evidence: EvidencePackage, verdict, confidence, reason, _model(hidden), cache_key}` + `model.py:108` `DependencyModel{sorted, meaningful_only(), to_dict hides model, to_log_dict retains, from_judgments:141, build_dependency_model:158}`; `Stage 4 List[Tuple[EvidencePackage,JudgeResult]] → Stage 5 DependencyModel` service-to-resource, external output model-blind, internal logging via `logging` + `cache.json`; verified fixtures `shared_env 2`, `shared_volume 1`, `near_miss 0`, artificial 3; `__init__.py` exports `Dependency`/`DependencyModel`; `D-026`.
- Tests: 48 passed (Stage 5 manual: external leak `False`, log retains).

---

## 3. Immediate Next Steps (Do In Order)

**Stages 1–5 DONE — next is Stage 6 per `AGENTS.md §6` Resource Graph:**

1. **Resource Graph (Stage 6) NEXT** — `src/blindspot/graph.py`:
   - Input: `DependencyModel` from `model.py:108` (`Dependency` service-to-resource, `to_dict` hides `_model`).
   - Output: bipartite `networkx` graph `service → resource ← service` (e.g. `orders→DB_HOST=postgres←reports`, `api→shared-data←worker`) with distinct node styles (service vs resource), no `service→service` edge. `meaningful_only()` typically.

2. **Report (Stage 7)** — `src/blindspot/report.py`: human-readable findings per `Dependency` with `resource`/`evidence` (including resolved service/image/related config) + `verdict/confidence/reason` (confidence exposed, model **not** exposed per user rule — stays in logging).

3. **Real-world validation** — 1 small OSS multi-service repo (run full pipeline with chosen provider, check `DependencyModel` + graph).

4. **Tier 2 K8s** — blocked until Tier 1 demo (same pipeline, provider-agnostic).

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges filtered + bounded packages (one per package).
- **Shared names ≠ dependencies** — `PORT` filtered before LLM.
- **Evidence matters + bounded** — give LLM smallest machine-verified facts (required + resolved service/image/internal, related DB_* bounded, filtering signals). No unrelated config. Prompt `build_judge_prompt:81` is provider-agnostic.
- **Evidence resolution before LLM** — deterministically resolve `DB_HOST=postgres -> postgres:16` (only HOST/URL-like), `named_volume` internal.
- **One LLM call per survivor** — `0 for obvious noise + 1 per interesting candidate`; `uncertain` allowed; `cache.json` key = `sha256(cache_key_dict)` (not just value); model/version stored. Provider pluggable (Gemini or OpenRouter).
- **Provider-agnostic** — Do not tie prompt/architecture to Gemini; `DEFAULT_MODEL` = `nvidia/nemotron-3-ultra-550b-a55b`, `FAILSAFE_MODEL` = `gemini-3.1-flash-lite`; lazy `type: ignore` imports keep module importable without SDK. `OPENROUTER_MAX_TOKENS` maps thinking low/medium to max_tokens.
- **Confidence is first-class** — `JudgeResult` → `Dependency{verdict, confidence, reason, evidence}` → `Graph`/`Report` (confidence exposed, model hidden externally).
- **Model hidden** — `Dependency._model` stored privately, `to_dict()` omits it, `to_log_dict()`/`cache.json`/`logging` retain it. User never sees provider.
- **Resource graph** — `service → resource` (uses `Dependency` service-to-resource, not `EvidencePackage.value` alone).
- **Failsafe** — `failsafe_result:226` returns `uncertain 0.5` on missing key/SDK/API error/parse error, attributed to `FAILSAFE_MODEL` (logged, not external).
- **Stack** — `pyyaml`, `python-dotenv`, `google-genai`, `openai`, `networkx`, `matplotlib` (openai only for OpenRouter, google-genai only for Gemini).
- **Windows host** — `C:\Users\Lekha\Projects\Blindspot`, `bash`, `.env` gitignored.

---

## 5. Session Handoff Checklist

- [x] `STATE.md` §2 flipped (Stage 5 Dependency Model COMPLETE, model hidden, Stage 6 NEXT)
- [x] `STATE.md` §6 Recent Activity (Stage 5 `Dependency` + `DependencyModel`)
- [x] `DECISIONS.md` D-026 (model hidden, service-to-resource)
- [x] `HANDOFF.md` §§2–3 updated (Stage 5 done, Stage 6 next)
- [x] Tests run (48 passed, Stage 5 manual: external leak `False`, log retains)
- [x] `README.md` pending refresh for Stage 5 — updated below
- [ ] Commit — working tree dirty (model 160 LOC, .env keys gitignored)

**Next agent:** implement `graph.py` (bipartite `Service ↔ Resource` from `DependencyModel`), then `report.py`.

---

## 6. Useful Commands

```bash
git status
PYTHONPATH=src .venv/Scripts/python -m pytest -v
# judge with Gemini (low thinking)
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import GeminiJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, GeminiJudgeClient(thinking_level='low'), cache_path='cache.json'))"
# judge with Nemotron Ultra via OpenRouter (provider-agnostic, low=512 tokens)
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import OpenRouterJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, OpenRouterJudgeClient(thinking_level='low'), cache_path='cache.json'))"
PYTHONPATH=src .venv/Scripts/python -c "from blindspot.judge import JudgeResult, validate_judge_result; validate_judge_result(JudgeResult(verdict='meaningful', confidence=0.93, reason='ok', model='test'))"
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md` (§4 one call/candidate, §5 Dependency Model service-to-resource)
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md` (§4 hybrid diagram)
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md`
4. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/model.py` (`Dependency:27`, `DependencyModel:108`, `from_judgments:141`)
5. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/judge.py` (`JudgeResult:40`, `build_judge_prompt:81`)
