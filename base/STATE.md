# BASE STATE — Fast-Track Status (base branch only)

> LOCAL-ONLY, gitignored. `STATE.md` / `HANDOFF.md` describe the full-vision track.

**Branch:** `base` (fast finish) vs `main` (full potential). Both at `cd6fa56 Split` on 2026-10-07; no divergence yet except upcoming BASE work + doc hiding.
**Baseline:** D-042 Tier 1 frozen/audited. `src/blindspot/` 12 modules (~586 parser / 526 filtering / 616 resolution / 1089 judge lines). Tests: 8 files (`test_parser`, `test_discovery`, `test_filtering`, `test_graph`, `test_grouping`, `test_resolution`, `test_accounting`, `test_audit`).

## Done

- [x] Branch split (`base` + `main` at `cd6fa56`)
- [x] `base/MISSION.md` + `base/PLAN.md` + this file created (isolated, gitignored)
- [x] `.gitignore` hides internal docs, keeps `README.md` public (staged, `git rm --cached` done, files still local)
- [x] Baseline verified 2026-10-07: `119 passed in 0.45s` + fixed leftover conflict in `tests/test_accounting.py:230` (kept hermetic `monkeypatch` side)
- [x] BASE implemented 2026-10-07: `context.py` + `context_judge.py` (Q1-Q4, JSON-array, per-item failsafe, `ctx:` cache) + `scoring.py` (`base-score-v1`, bands strong/likely/possible/uncertain, `verdict_from_scoring`) + minimal wiring (`coupling.py` classification/score fields + `with_scoring`, `report.py` classification display + potential-vs-proven wording, `cli.py` contextual-primary with legacy fallback, deterministic-only still scored)
- [x] Tests: `130 passed` (119 existing untouched + 11 new in `test_base_context.py`/`test_base_scoring.py`)
- [x] Validation runs 2026-10-07 (deterministic, no network) + stubbed-meaningful review (below)

## Validation log (deterministic execution, no LLM — verdicts uncertain by design)

| Repo | Exec | Svc | Raw/Cand | Obs | Groups | Meaningful | Notes |
|------|------|-----|----------|-----|--------|------------|-------|
| fixtures/shared_env | ok | 3 | 3 | 2 | 2 | 0 (uncertain) | 2 unresolved-config groups; needs LLM to confirm |
| fixtures/shared_volume | ok | 2 | 2 | 1 | 1 | 0 (uncertain) | named-volume internal group found structurally |
| fixtures/near_miss | ok | 2 | 3 | 0 | 0 | 0 | correctly filtered (generic + different values), 0 LLM calls |
| tmp_calcom2 (Cal.com-like) | ok | 3 | 6 | 6 | 1 | 0 (uncertain) | 6 obs → 1 group, as D-042 |
| celery-docker-example (real) | ok | 5 | 0 | 0 | 0 | 0 | no Tier-1 shared-resource evidence, not a parse failure |
| docker/docker-compose.yaml (Cal.com-like, real) | ok | 5 | 6 | 6 | 1 | 0 (uncertain) | `postgresql\|${database_host}\|\|${POSTGRES_DB}` partial/config |

Stubbed-meaningful review (proves the demo path, not a precision claim):

| Repo | Group | Classification / Score | Verdict / Conf | Graph | Manual note |
|------|-------|------------------------|----------------|-------|-------------|
| docker | `postgresql\|${database_host}\|\|${POSTGRES_DB}` (3 svc) | likely / +3.35 | meaningful / 0.58 | 4 nodes / 3 edges | Plausible shared-DB coupling; still partial/config — report says potential, not proven; table (L2) = none |
| shared_env | `DB_HOST=shared-db`, `DB_NAME=orders` | likely / +3.35 each | meaningful / 0.60 | 4 nodes / 4 edges | Unresolved templates scoring likely on LLM-yes may be generous; uncertainty preserved (≈0.8); honest limit, not a defect fix now |

## Limitations (honest, BASE scope)

- Discovery is name-only: same-value-different-var-names missed (known Tier-1 gap, cf. D-039 — not fixed on BASE).
- Unresolved-template groups can reach `likely` when LLM answers yes; uncertainty is preserved but band may read generous — weights tunable in `scoring.py` (`base-score-v1`).
- No live-LLM validation run on BASE yet (deterministic + stub only); D-042 noted live-key variance (`uncertain` vs README `meaningful`) — still open, needs Workstream-B style consistency check before any accuracy claim.
- Source context is cheap heuristic grep (bounded, may be empty); L2 table=yes only when snippet match — otherwise `none` + uncertainty preserved. No SQL/ORM/AST.
- `depends_on`, networks, ports ignored by design (not Tier-1 signals).
