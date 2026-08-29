# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-08-29
**Current Phase:** Tier 1 — Stages 1–4 **DONE** (parser `image` + discovery + filtering with `EvidencePackage` + **LLM Judge with Mock + cache.json**) — **Stage 5 NEXT: Dependency Model**
**Current Branch:** `main` — 3 commits ahead, working tree: AGENTS/PROJECT_PLAN + Stage 3 evidence + Stage 4 judge

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence, §4 one call/candidate, confidence mandatory) + `PROJECT_PLAN.md` (hybrid diagram) + `STATE.md` §2, then this file.
2. **Stages 1–4 DONE:** `parser.py` 540 LOC (`Service.image`), `discovery.py` 132 LOC, `filtering.py` 355 LOC (`EvidencePackage:70`, `build_evidence_packages:210`), `judge.py` 361 LOC (`JudgeResult:18`, `MockJudgeClient:160`, `build_judge_prompt:60`, `judge_evidence_packages:324` with `cache.json:85` `sha256(cache_key_dict)`). **48 tests pass**. `shared_env` 3→2 pkgs→2 meaningful (mock), `shared_volume` 2→1→meaningful, `near_miss` 3→0→0 calls, cache hit verified.
3. **Judge now:** `EvidencePackage` → one `JudgeResult{verdict: meaningful|coincidental|uncertain, confidence, reason, model}` per package, cached in `cache.json` (`cache_key_dict`), `0+1/candidate`, mockable, real LLM pluggable.
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-024 judge added), `HANDOFF.md`.
5. Global model `opencode/muse-spark-1.2-contributor-free`, `.gitignore` allows `fixtures/**/.env` + ignores `cache.json`.

---

## 2. Where We Left Off

- `AGENTS.md:1` 522 LOC + `PROJECT_PLAN.md:1` 301 LOC hybrid spec.
- **Parser:** `parser.py:45` `Service.image` + `parse_compose_file:488`/`505` + `_merge_projects:401` image override; `D-022`.
- **Filtering:** `filtering.py:70` `EvidencePackage` + `build_evidence_package:240` with HOST/URL-like guard, `host:port` split, `volume_targets`, `related_config` bounded; `D-023`.
- **Judge:** `judge.py:18` `JudgeResult` + `build_judge_prompt:60` (A/B, SHARED CONFIG, VALUES, RESOLUTION, RELATED, FILTERING) + `MockJudgeClient:160` + `judge_evidence_package:270` with `cache.json:85` (`sha256`) `0+1/candidate`; manual mock verified on fixtures + second run cache hit (different client served cached `mock-heuristic-v1`), cache key diff when value changes; `__init__.py:1` exports `JudgeResult`; `D-024`; `.gitignore:39` `cache.json`.
- Tests: 48 passed (judge manually verified, no new automated tests yet).

---

## 3. Immediate Next Steps (Do In Order)

**Stages 1–4 DONE — next is Stage 5 per `AGENTS.md §5` Dependency Model:**

1. **Dependency Model (Stage 5) NEXT** — `src/blindspot/model.py`:
   - Input: `List[Tuple[EvidencePackage, JudgeResult]]` from `judge_evidence_packages`.
   - Store `Dependency{service_a, service_b, resource, resource_type, value, evidence: EvidencePackage, verdict, confidence, reason, model}` — service-to-resource (`Dependency` must retain `why` + `how confident`, not just `orders→reports`). `confidence` mandatory first-class, exposed downstream.

2. **Resource Graph (Stage 6)** — `src/blindspot/graph.py`: `networkx`+`matplotlib` bipartite `service→resource` (e.g. `orders→DB_HOST=postgres←reports`), distinct node styles, resource node = mechanism.

3. **Report (Stage 7)** — human-readable findings with resource+evidence+judgment/confidence (must expose confidence per `AGENTS.md §7`).

4. **Real-world validation** — 1 small OSS multi-service repo.

5. **Tier 2 K8s** — blocked until Tier 1 demo.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges filtered + bounded packages (one per package).
- **Shared names ≠ dependencies** — `PORT` filtered before LLM.
- **Evidence matters + bounded** — give LLM smallest machine-verified facts (required + resolved service/image/internal, related DB_* bounded, filtering signals). No unrelated config.
- **Evidence resolution before LLM** — deterministically resolve `DB_HOST=postgres -> postgres:16` (only HOST/URL-like), `named_volume` internal.
- **One LLM call per survivor** — `0 for obvious noise + 1 per interesting candidate`; `uncertain` allowed; `cache.json` key = `sha256(cache_key_dict)` (not just value); model/version stored.
- **Confidence is first-class** — `JudgeResult` → `Dependency` → `Graph`/`Report`.
- **Resource graph** — `service → resource` (uses `EvidencePackage.value`).
- **Mockable judge** — `MockJudgeClient` for CI, real LLM replaces it without pipeline change.
- **Stack** — `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` only.
- **Windows host** — `C:\Users\Lekha\Projects\Blindspot`, `bash`.

---

## 5. Session Handoff Checklist

- [x] `STATE.md` §2 flipped (Stage 4 judge mock + cache DONE, Stage 5 NEXT)
- [x] `STATE.md` §6 Recent Activity (judge mock + cache verified)
- [x] `DECISIONS.md` D-024 (judge one-call + cache)
- [x] `HANDOFF.md` §§2–3 updated (Stage 4 done, Stage 5 next)
- [x] Tests run (48 passed, judge manually verified with mock + cache hit)
- [x] `README.md` pending refresh for Stage 4 — updated below
- [ ] Commit — still 3 commits ahead, working tree dirty

**Next agent:** implement `model.py` (with `verdict/confidence/reason`), then `graph.py`.

---

## 6. Useful Commands

```bash
git status
PYTHONPATH=src python -m pytest -v
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import MockJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, MockJudgeClient(), cache_path='cache.json'))"
PYTHONPATH=src python -c "from blindspot.judge import JudgeResult, validate_judge_result; validate_judge_result(JudgeResult(verdict='meaningful', confidence=0.93, reason='ok', model='mock'))"
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md` (§4 one call/candidate)
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md` (§4 hybrid diagram)
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md`
4. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/judge.py` (`JudgeResult:18`, `MockJudgeClient:160`)
5. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/filtering.py` (`EvidencePackage:70`)
