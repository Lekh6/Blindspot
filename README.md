# BlindSpot

BlindSpot detects hidden dependencies between microservices that do not appear as direct network calls, focusing on shared configuration such as environment variables and volumes in Docker Compose projects. It uses a **hybrid deterministic + LLM** pipeline: deterministic filtering + bounded evidence construction before one LLM call per surviving candidate (confidence mandatory, cached).

## Pipeline

```
Input → Parse+Normalize → Candidate Discovery → Candidate Filtering (+ bounded evidence) → LLM Judge (1 call/candidate, cached) → Dependency Model → Resource Graph (Service↔Resource) → Report
```

Current: **Stages 1–4 DONE** — messy fixtures + parser (`env_file`, `${VAR}`, `image: postgres:15`) + discovery (`resource` + `value` split) + filtering with **bounded evidence** (`EvidencePackage` with deterministic `value→service+image` only HOST/URL-like, bounded `DB_*`, signals) + **LLM Judge** (`JudgeResult{verdict: meaningful|coincidental|uncertain, confidence, reason}`, `build_judge_prompt`, `MockJudgeClient`, `cache.json` `sha256(cache_key_dict)`, 0+1/candidate) — 48 tests passed.

Evidence example: `DB_HOST=postgres` deterministically resolves to `postgres` service `postgres:16` → one LLM call with narrow prompt → `meaningful 0.95` cached.

## Stage 1 — Ground-Truth Fixtures (Deliberately Messy)

Fixtures are in `fixtures/` and include `docker-compose.yml` + `.env`/`common.env` with comments, `${VAR_NAME}`/`:-default` interpolation, `image`, and `env_file` (string vs list) to prove parser handles real-world noise. `.gitignore` allows `fixtures/**/.env`.

| Fixture | Path | Files | Expected Discovery (Stage 2) | Parser Invariant | Expected Evidence Packages (Stage 3) |
|---|---|---|---|---|---|
| **shared_env** | `fixtures/shared_env/` | `docker-compose.yml` (`env_file: common.env`, `${DB_HOST}`, `${DB_NAME:-orders}`, `image` ) + `.env` (`DB_HOST=shared-db`) + `common.env` (`DB_NAME=orders`, `SHARED_EXTRA=keep`) | **Discovery** 3: `DB_HOST`/`DB_NAME`/`SHARED_EXTRA`; **Filtering** 2 kept | `orders`/`reports` `DB_HOST=shared-db`, `DB_NAME=orders`, `image` preserved | **2 pkgs:** `DB_HOST` external + `related_config` `DB_HOST/DB_NAME` bounded, `DB_NAME` external (not HOST-like → no false `orders` service), `generic_variable:false, same_value:true, resolved_reference:external` |
| **shared_volume** | `fixtures/shared_volume/` | `docker-compose.yml` (`shared-data:/data` + `DATA_PATH=${DATA_PATH}`) + `.env` (`DATA_PATH=/data`) | **Discovery** 2: `shared-data` (`named_volume`) + `DATA_PATH`; **Filtering** 1 kept | Both mount `shared-data:/data` (`named`, `volume_targets`) | **1 pkg:** `shared-data` `reference_type:named_volume` `is_internal:true` `volume_targets` `{/data}` |
| **near_miss** | `fixtures/near_miss/` | `docker-compose.yml` (`env_file: common.env`, `PORT` 8000≠9000, `APP_ENV=${APP_ENV}`) + `.env` + `common.env` (`APP_ENV=development`, `SHARED_NOISE=1`) | **Discovery** 3: `PORT` (`value None`, different values), `APP_ENV`, `SHARED_NOISE`; **Filtering** 0 kept | `PORT 8000≠9000`, no volumes | **0 pkgs** (different-values + generic filtered, 0 LLM calls) |

Discovery is broad; Filtering drops generic/`different values`, builds one bounded package per survivor (required + resolved service/image/internal-external + related bounded + signals); Judge will see `DB_HOST=postgres → postgres:16` with `is_internal:true`.

## Quick Start

```bash
pip install -r requirements.txt
pytest -v                          # 48 tests (32 parser + 8 discovery + 8 filtering)
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); print([pkg.to_dict() for pkg in build_evidence_packages(discover_candidates(p), p)])"
# resolution demo: DB_HOST=postgres → postgres:16
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_string; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; p=parse_compose_string('services:\n  orders:\n    environment: {DB_HOST: postgres}\n  reports:\n    environment: {DB_HOST: postgres}\n  postgres:\n    image: postgres:16\n'); print(build_evidence_packages(discover_candidates(p), p)[0].to_dict())"
# judge with mock (no API key, cached)
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import MockJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, MockJudgeClient(), cache_path='cache.json'))"
```

## Docs

- `AGENTS.md` — hybrid architecture (§3 bounded evidence, §4 one call/candidate, confidence mandatory, 522 LOC)
- `PROJECT_PLAN.md` — pace 1–2h/day, 7 phases (301 LOC)
- `STATE.md` — current pipeline status (Stages 1–4 done, Stage 5 next)
- `DECISIONS.md` — D-021 hybrid, D-022 parser image, D-023 bounded evidence, D-024 judge with cache
