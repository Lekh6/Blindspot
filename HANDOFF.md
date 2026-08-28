# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-08-28
**Current Phase:** Tier 1 — Stages 1–2 **DONE** (messy fixtures + parser + discovery done), **Stage 3 NEXT: Candidate Filtering**
**Current Branch:** `main` — 1 commit (`3859ca1`), working tree: 5 modified + 6 untracked + 2 new tracked files

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (resource graph `orders→resource←reports`, K8s Tier 2, `cache.json`), then `PROJECT_PLAN.md` (§7), then `STATE.md` §2, then this file.
2. **Stages 1–2 DONE 2026-08-28:** fixtures messy (comments/`${VAR}`/`env_file`), `parser.py` 523 LOC (`_load_service_env_files:352`, `_merge_projects:397`), `discovery.py` 108 LOC (`Candidate:19`, `discover_candidates:35` pairwise env+`named_volume` only). **40 tests pass** (32 parser + 8 discovery) on messy fixtures.
3. **Discovery output:** `Candidate{service_a, service_b, resource, resource_type, evidence}` sorted deterministic — `shared_env` 3 (DB_HOST/DB_NAME/SHARED_EXTRA), `shared_volume` 2 (DATA_PATH + shared-data), `near_miss` 3 (PORT different values + APP_ENV + SHARED_NOISE). Filtering will handle `PORT`.
4. Keep these updated: `STATE.md`, `DECISIONS.md`, `HANDOFF.md` every session.
5. Global model `opencode/muse-spark-1.2-contributor-free`, `.gitignore:9` allows `fixtures/**/.env`.

---

## 2. Where We Left Off

- `AGENTS.md` final (7-stage) + `PROJECT_PLAN.md` final.
- `3859ca1` baseline.
- **2026-08-28 messy fixtures + parser restore:** 3 `docker-compose.yml` + 5 env files (`.env`/`common.env`), comments/`${VAR:-default}`/`env_file` string vs list, invariants kept (`DB_HOST=shared-db`/`DB_NAME=orders`, `shared-data:/data`, `PORT 8000≠9000`); `.gitignore` patched; parser 523 LOC.
- **2026-08-28 discovery:** `src/blindspot/discovery.py:1` — `Candidate` frozen dataclass + `discover_candidates`:
  - Env: intersection of keys, `resource=key=value` if same non-None value else `key`, evidence notes equality vs `different values (a=... vs b=...)`
  - Volumes: only `type=="named"` with `source`, shared `source` → candidate `resource=source`, evidence with `target` + type, targets-differ note.
  - Sorted by `(service_a, service_b, resource_type, resource)`.
  - `src/blindspot/__init__.py` now exports `Candidate`/`discover_candidates`.
  - `tests/test_discovery.py:1` 8 tests (3 messy fixture + 5 unit: same-key-different-values, same-value, bind/anon ignored, named volume, 3-service pairs) — all pass; total 40.
- `git status`: `M AGENTS.md`, `M .gitignore`, `M fixtures/*/*.yml`, `M src/blindspot/parser.py`, `M src/blindspot/__init__.py`, `?? PROJECT_PLAN.md`, `?? fixtures/**/.env`, `?? fixtures/**/common.env`, `?? src/blindspot/discovery.py`, `?? tests/test_discovery.py`, `M STATE.md`/`HANDOFF.md` updated.
- **Not yet done:** `DECISIONS.md` D-017/018 for messy fixtures + discovery, `README.md` still old.

---

## 3. Immediate Next Steps (Do In Order)

**Stages 1–2 DONE — do not redo. Next is Stage 3 per `AGENTS.md:233`:**

1. **Candidate Filtering (Stage 3) NEXT** — `src/blindspot/filtering.py`:
   - Input: `List[Candidate]`.
   - Deterministic heuristics: filter/deprioritize `PORT`, `HOST`, `DEBUG`, `LOG_LEVEL`, `SHARED_EXTRA`/`SHARED_NOISE` etc conservatively — reduce obvious noise but **don't claim it can never be coupling** (`AGENTS.md:65`). Keep `DB_HOST`/`DB_NAME` and `shared-data` volume.
   - Build `evidence` strings for remaining candidates to feed LLM.
   - Output: `List[Candidate]` filtered + enriched evidence (or `FilteredCandidate`).
   - Test against messy fixtures: `near_miss`'s `PORT` (different values) should be filtered/deprioritized, `APP_ENV`/`SHARED_NOISE` may be filtered as generic; `shared_env`/`shared_volume` should keep real candidates.

2. **LLM Judge (Stage 4)** — `src/blindspot/judge.py`: narrow prompt on single candidate + evidence → `{is_dependency, confidence, reasoning}`; cache in `cache.json` with key = hash(candidate+evidence); run >1× for consistency.

3. **Dependency Model (Stage 5)** — `src/blindspot/model.py`: `Dependency(service_a, service_b, resource, resource_type, evidence, judge_result, confidence)` service-to-resource.

4. **Resource Graph (Stage 6)** — `src/blindspot/graph.py`: `networkx`+`matplotlib` bipartite `service→resource`.

5. **Report (Stage 7)** — human-readable findings.

6. **Real-world validation** — 1 small OSS multi-service repo.

7. **Tier 2 K8s** — blocked until Tier 1 demo.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges pre-extracted candidates.
- **Shared names ≠ dependencies** — `PORT` near-miss must be filtered, not flagged.
- **Evidence matters** — every dependency carries `evidence` + `judge_result` + `confidence`.
- **Filtering before LLM** — heuristics first, LLM for semantic ambiguity.
- **Verdict caching** — `cache.json` key = candidate + evidence.
- **Resource graph** — `service → resource`, not `service ↔ service`.
- **Extensibility** — K8s reuses same pipeline.
- **Parser contract** — preserves `${VAR}`, `""` for `VAR=`, explicit overrides `env_file`.
- **Fixture contract** — messy fixtures now produce 3/2/3 candidates; downstream must handle that.
- **Stack** — `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` only.
- **Windows host** — `C:\Users\Lekha\Projects\Blindspot`, `bash`.

---

## 5. Session Handoff Checklist (Update Before You Leave)

- [x] `STATE.md` §2 flipped (Stage 2 → Done, Stage 3 → NEXT)
- [x] `STATE.md` §6 Recent Activity appended (discovery)
- [ ] `DECISIONS.md` D-017/018 (messy fixtures + discovery) — TODO
- [x] `HANDOFF.md` §§2–3 updated (stages 1–2 done, next = filtering)
- [x] Tests run (40 passed: 32 parser + 8 discovery)
- [ ] `README.md` refresh — TODO
- [ ] Commit — still 1 commit, working tree has 10+ dirty/untracked

**Next agent:** add D-017/018 + README, then `filtering.py`.

---

## 6. Useful Commands

```bash
git status
git log --oneline -10
git diff --stat
pytest -v
pytest tests/test_discovery.py -v
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; print(discover_candidates(parse_compose_file('fixtures/shared_env/docker-compose.yml')))"
ls -R fixtures
cat src/blindspot/discovery.py
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md`
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md`
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md`
4. `C:\Users\Lekha\Projects\Blindspot\DECISIONS.md`
5. `C:\Users\Lekha\Projects\Blindspot\HANDOFF.md`
6. `C:\Users\Lekha\Projects\Blindspot\src\blindspot/discovery.py`
7. `C:\Users\Lekha\Projects\Blindspot\tests/test_discovery.py`
