# BlindSpot

BlindSpot detects hidden dependencies between microservices that do not appear as direct network calls, focusing on shared configuration such as environment variables and volumes in Docker Compose projects.

## Pipeline

```
Input → Parse+Normalize → Candidate Discovery → Candidate Filtering → LLM Judge → Dependency Model → Graph → Report
```

Current: **Stages 1–2 DONE** — messy fixtures + parser (`env_file`, `${VAR}`, multi-file merge) + candidate discovery (pairwise shared env + named volumes) — 40 tests passed.

## Stage 1 — Ground-Truth Fixtures (Deliberately Messy)

Fixtures are in `fixtures/` and include `docker-compose.yml` + `.env`/`common.env` with comments, `${VAR_NAME}`/`:-default` interpolation, and `env_file` (string vs list) to prove parser handles real-world noise. ` .gitignore` allows `fixtures/**/.env`.

| Fixture | Path | Files | Expected Discovery (Stage 2) | Parser Invariant |
|---|---|---|---|---|
| **shared_env** | `fixtures/shared_env/` | `docker-compose.yml` (`env_file: common.env`, `${DB_HOST}`, `${DB_NAME:-orders}`) + `.env` (`DB_HOST=shared-db`) + `common.env` (`DB_NAME=orders`, `SHARED_EXTRA=keep`) | `orders ↔ reports` 3 candidates: `DB_HOST=shared-db`, `DB_NAME=orders`, `SHARED_EXTRA=keep` (first two are true hidden coupling) | `orders`/`reports` `DB_HOST=shared-db`, `DB_NAME=orders` |
| **shared_volume** | `fixtures/shared_volume/` | `docker-compose.yml` (`shared-data:/data` + `DATA_PATH=${DATA_PATH}`) + `.env` (`DATA_PATH=/data`) | `orders ↔ reports` 2 candidates: `shared-data` (`named_volume`) + `DATA_PATH=/data` (`env_var` via interpolation) | Both mount `shared-data:/data` (`named`) |
| **near_miss** | `fixtures/near_miss/` | `docker-compose.yml` (`env_file: common.env`, `PORT` 8000≠9000, `APP_ENV=${APP_ENV}`) + `.env` + `common.env` (`APP_ENV=development`, `SHARED_NOISE=1`) | `orders ↔ reports` 3 candidates: `PORT` (different values evidence), `APP_ENV=development`, `SHARED_NOISE=1` — `PORT` must be filtered as coincidence in Stage 3 | `PORT 8000≠9000`, no volumes |

Discovery is conservative — same key with different values still yields a candidate (e.g. `PORT`), with evidence `different values (8000 vs 9000)`. Filtering (Stage 3) will deprioritize generic keys.

## Quick Start

```bash
pip install -r requirements.txt
pytest -v                          # 40 tests (32 parser + 8 discovery)
PYTHONPATH=src python -c "from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; print(discover_candidates(parse_compose_file('fixtures/shared_env/docker-compose.yml')))"
```

## Docs

- `AGENTS.md` — final architecture (7 stages, resource graph, K8s Tier 2)
- `PROJECT_PLAN.md` — pace 1–2h/day, 7 phases
- `STATE.md` — current pipeline status
- `DECISIONS.md` — D-017 messy fixtures, D-018 discovery
