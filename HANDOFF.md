# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-08-28
**Current Phase:** Tier 1 In Progress — final plan/architecture committed, parser with env_file done, stages 3–7 pending
**Current Branch:** `main` — 1 commit (`3859ca1`), uncommitted `AGENTS.md`/`PROJECT_PLAN.md`/`parser.py` updates

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (final architecture — resource-based graph, K8s Tier 2, verdict caching), then `PROJECT_PLAN.md` (pace 1–2h/day + 7-phase build order), then `STATE.md` §2 pipeline table, then this file.
2. Parser is done at `src/blindspot/parser.py:424` — supports `.env`, `env_file` (string/list + `{path,required}`), `${VAR}` interpolation, multi-file `Union[Path,List[Path]]` merge (`parser.py:397`). 32 tests pass.
3. **Ground truth changed 2026-08-28** — Tier 2 is **Kubernetes** (ConfigMap/Secret/volumes), **not AST**; graph is **service→resource←service** bipartite; LLM needs **local `cache.json`** with **candidate+evidence key**; fixtures must be **deliberately messy** (comments, `${VAR}`, `env_file`).
4. Keep these updated every session: `STATE.md` (§1 snapshot, §2 statuses, §6 activity), `DECISIONS.md` (append ADR), `HANDOFF.md` (§§2–3).
5. Global model stays `opencode/muse-spark-1.2-contributor-free` — do not change.

---

## 2. Where We Left Off

- `AGENTS.md` committed from initial paste — 7-stage pipeline `Parse→Discovery→Filtering→LLM Judge→Dependency Model→Graph→Report`.
- `3859ca1` (2026-08-28): Stage 1 `.venv` (py 3.14.6), `requirements.txt` (`pyyaml`, `python-dotenv`, `networkx`, `matplotlib`), fixtures `shared_env`/`shared_volume`/`near_miss` (clean), `src/blindspot/parser.py` 415 LOC (5 layers: YAML, .env, env normalize, volume normalize, Project).
- **2026-08-28 (uncommitted):** applied final `PROJECT_PLAN.md` + final `AGENTS.md` per user paste — resource-based graph (`orders→DB_HOST=postgres←reports`), `cache.json` verdict caching, K8s Tier 2 replaces AST, `env_file` + `${VAR}` required, messy fixtures required.
- **2026-08-28 (uncommitted):** `parser.py` extended to 523 LOC — `_load_service_env_files:352` (string/list/dict, relative resolution, later-file overrides), `merged_env` explicit-over-file (`parser.py:487`), `""` preserved (`parser.py:93` comment fix), multi-file `Union[Path,List[Path]]` deep-merge (`_merge_projects:397` — env `.update()`, volumes appended/unioned deduped).
- 32 tests `tests/test_parser.py` still pass; manual checks for env_file override, list order, `{path,required:false}`, multi-file merge, `VAR=` empty-string all passed.
- `git status` shows modified `AGENTS.md`, `src/blindspot/parser.py`, untracked `PROJECT_PLAN.md`; `STATE.md`/`DECISIONS.md`/`HANDOFF.md` now updated this session but not yet committed.
- Fixtures are **still clean** — not yet refreshed to messy ground truth (needed before Candidate Discovery is tested realistically).

---

## 3. Immediate Next Steps (Do In Order — Per Final Plan)

**Do not skip or reorder — per `AGENTS.md` Development Priorities and `PROJECT_PLAN.md` §7:**

1. **Refresh synthetic fixtures (Phase 1 remaining)** — make `fixtures/{shared_env,shared_volume,near_miss}` deliberately messy: add ` # comments`, `${VAR_NAME}` interpolation referencing `.env`/`env_file`, and at least one service using `env_file:` (e.g. `common.env`). Keep invariants: `shared_env` = true positive (shared `DB_HOST=shared-db` etc), `shared_volume` = true positive (`shared-data:/data`), `near_miss` = both define `PORT` `8000` vs `9000` must NOT be flagged.
   - Then re-run `python -m pytest -v` and add 2–3 new parser tests for env_file + interpolation.
2. **Candidate Discovery (Stage 2)** — `src/blindspot/discovery.py`: scan normalized `Project` for shared env keys (where value equality or config coupling matters) + shared named volumes → `Candidate{service_a, service_b, resource, resource_type, evidence}`. Do NOT decide dependency yet.
3. **Candidate Filtering (Stage 3)** — `src/blindspot/filtering.py`: deterministic heuristics to filter/deprioritize `PORT`, `DEBUG`, `LOG_LEVEL` etc conservatively + build evidence strings for LLM.
4. **LLM Judge (Stage 4)** — `src/blindspot/judge.py`: narrow prompt on single candidate + evidence, returns `{is_dependency, confidence, reasoning}`; cache in `cache.json` (key = hash(candidate+evidence)); run >1× in validation to check consistency.
5. **Dependency Model (Stage 5)** — `src/blindspot/model.py`: `Dependency(service_a, service_b, resource, resource_type, evidence, judge_result, confidence)` service-to-resource provenance.
6. **Resource Graph (Stage 6)** — `src/blindspot/graph.py`: `networkx`+`matplotlib`, bipartite nodes (service vs resource), edges `service→resource`; distinct colors/shapes.
7. **Report (Stage 7)** — human-readable findings with resource/evidence/judgment/confidence.
8. **Real-world validation (Tier 1)** — pre-scout 10–15 min, pick 1 small OSS multi-service repo (e.g. `dockersamples/example-voting-app`), run pipeline, write up.
9. **Tier 2 Kubernetes only if time allows** — `src/blindspot/k8s.py` parsing manifests for shared ConfigMap/Secret/volumes → same pipeline `Discovery→Filtering→Judge→Model→Graph→Report`. **Do NOT do AST.**

**Tier 2 (K8s) is `Blocked` until Tier 1 graph+report demo passes.**

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges pre-extracted candidates, never scans codebase freely.
- **Shared names ≠ dependencies** — `PORT` near-miss must not be flagged; all shared names go through filtering+LLM.
- **Evidence matters** — every dependency carries `evidence` + `judge_result` + `confidence` into Model/Graph/Report.
- **Filtering before LLM** — heuristics run first to reduce cost; LLM reserved for semantic ambiguity.
- **Verdict caching** — `cache.json` key = candidate + evidence; same value in different contexts must not share verdict.
- **Resource-based graph** — edges are `service → resource`, not `service ↔ service`; avoids implying direct call.
- **Extensibility** — K8s findings reuse same pipeline, no parallel architecture.
- **Parser contract** — preserves unresolved `${VAR}`, preserves `""` for `VAR=` (`load_env_file` filters only `None`), explicit `environment:` overrides `env_file:`.
- **Stack** — `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` only; no `ast` needed; Python 3.10+.
- **Docker not required** — parse compose as text.
- **Windows host** — `C:\Users\Lekha\Projects\Blindspot`, `bash` maps `~` → `C:\Users\Lekha`, no `powershell.exe`.
- **Ground truth docs** — `AGENTS.md` + `PROJECT_PLAN.md` are committed; if they conflict, `AGENTS.md` (§1–§7, Scope, Principles) is canonical for build.

---

## 5. Session Handoff Checklist (Update Before You Leave)

Copy and check in final message:

- [ ] `STATE.md` §2 pipeline statuses flipped if stage completed
- [ ] `STATE.md` §6 Recent Activity appended with date + summary
- [ ] `DECISIONS.md` appended if any new ADR (e.g., filtering heuristics, cache key design, K8s schema)
- [ ] `HANDOFF.md` §§2–3 updated to reflect new next step
- [ ] Tests run and noted (synthetic + near-miss + messy fixtures)
- [ ] Commit created? (pending: `docs: commit final plan + resource graph + K8s Tier 2` + `feat(parser): env_file + multi-file merge` — currently 1 commit only, working tree has 3+ files dirty)

---

## 6. Useful Commands

```bash
git status
git log --oneline -10
git diff
git diff --stat
ls -R
cat AGENTS.md
cat PROJECT_PLAN.md
cat STATE.md
cat DECISIONS.md
cat HANDOFF.md
# after init:
python -m venv .venv && source .venv/Scripts/activate  # Windows git-bash
pip install -r requirements.txt
pytest -v
PYTHONPATH=src python -m blindspot.parser  # if CLI exists
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md`
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md`
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md`
4. `C:\Users\Lekha\Projects\Blindspot\DECISIONS.md`
5. `C:\Users\Lekha\Projects\Blindspot\src\blindspot\parser.py`
6. `C:\Users\Lekha\.config\opencode\opencode.jsonc` (global model)
