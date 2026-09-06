# RESOURCES.md

- **Internal primary (filtering):** `src/blindspot/filtering.py:12` (`GENERIC_ENV_KEYS`) and `src/blindspot/filtering.py:41` (`_decide`) + `src/blindspot/filtering.py:386` (`_decide_with_project` with normalized-identity convergence) — canonical heuristic implementation.
- **Internal primary (resolution):** `src/blindspot/resolution.py:270` (`bounded_resolve`, `MAX_RESOLUTION_DEPTH=10`, `_normalize_connection_identity` for `postgresql/mysql/mongodb/redis` stripping credentials) — bounded chain, cycle/depth, `internal/external_confirmed/partial/unresolved`, `exact/config/unknown`.
- **Internal upstream:** `src/blindspot/discovery.py:20` (`Candidate` with `resource` + `value` split) and `src/blindspot/discovery.py:40` (pairwise discovery) — defines what filtering receives. `src/blindspot/resolution.py:180` (`build_lookup` from `Compose/.env/env_file`).
- **Internal docs:** `AGENTS.md:65` (Filtering Before LLM), `AGENTS.md:52` (Shared Names ≠ Dependencies), `DECISIONS.md:D-020` + `D-029` (redesign) — architectural rationale.
- **Docker Compose env_file spec:** https://docs.docker.com/compose/compose-file/05-services/#env_file — defines `env_file` string/list and override order implemented in `src/blindspot/parser.py:352`.
- **Docker Compose variable substitution:** https://docs.docker.com/compose/environment-variables/envvars/#substitute-environment-variables-in-compose-files — defines `${VAR}` / `${VAR:-default}` behavior preserved in `src/blindspot/parser.py:106`.
- **Heuristics / noisy-neighbor problem (generic motivation):** https://en.wikipedia.org/wiki/Heuristic_(computer_science) — deterministic rules to prune expensive search before probabilistic judgment.
