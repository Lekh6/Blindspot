# RESOURCES.md

- **Internal primary:** `src/blindspot/filtering.py:12` (`GENERIC_ENV_KEYS`) and `src/blindspot/filtering.py:41` (`_decide`) — canonical heuristic implementation.
- **Internal upstream:** `src/blindspot/discovery.py:20` (`Candidate` with `resource` + `value` split) and `src/blindspot/discovery.py:40` (pairwise discovery) — defines what filtering receives.
- **Internal docs:** `AGENTS.md:65` (Filtering Before LLM), `AGENTS.md:52` (Shared Names ≠ Dependencies), `DECISIONS.md:D-020` — architectural rationale.
- **Docker Compose env_file spec:** https://docs.docker.com/compose/compose-file/05-services/#env_file — defines `env_file` string/list and override order implemented in `src/blindspot/parser.py:352`.
- **Docker Compose variable substitution:** https://docs.docker.com/compose/environment-variables/envvars/#substitute-environment-variables-in-compose-files — defines `${VAR}` / `${VAR:-default}` behavior preserved in `src/blindspot/parser.py:106`.
- **Heuristics / noisy-neighbor problem (generic motivation):** https://en.wikipedia.org/wiki/Heuristic_(computer_science) — deterministic rules to prune expensive search before probabilistic judgment.
