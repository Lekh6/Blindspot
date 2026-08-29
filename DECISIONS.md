# DECISIONS.md — Architecture Decisions

> Why BlindSpot looks the way it does. Append-only log — never delete, only supercede with new entry.

**Last Updated:** 2026-08-28

---

## D-001: Seven-Stage Pipeline

- **Date:** 2026-08-27 (from `AGENTS.md`)
- **Decision:** Structure BlindSpot as `Parse+Normalize → Candidate Discovery → Candidate Filtering → LLM Judge → Dependency Model → Graph → Report`.
- **Context:** Need to separate deterministic discovery from probabilistic judgment; each stage has single responsibility and testable output.
- **Consequence:** Enables independent testing of stages; forces clean contracts between stages (internal representation → candidates → evidence → judged dependencies → graph/report).

## D-002: Discovery ≠ Judgment

- **Date:** 2026-08-27
- **Decision:** Static analysis discovers candidates; LLM only judges pre-extracted candidates. LLM must NOT freely scan codebase and guess dependencies.
- **Context:** Unrestricted LLM discovery is non-repeatable, expensive, hallucination-prone.
- **Alternative Rejected:** End-to-end LLM scanning of repo/compose files.
- **Consequence:** Requires deterministic extractors for env vars / volumes (and later AST); LLM prompt stays narrow + evidence-grounded; must validate judgment consistency by running >1x.

## D-003: Tier 1 Focus — Compose + .env Coupling

- **Date:** 2026-08-27
- **Decision:** Tier 1 detects hidden coupling via shared environment variables and shared volumes/config in Docker Compose only.
- **Context:** These are the most common hidden microservice couplings without network calls; parsable as text without running containers.
- **Consequence:** Stage 1 must normalize `docker-compose.yml` + `.env`; explicitly out-of-scope for Tier 1 are network dependencies, DB table sharing (→ Tier 2).

## D-004: Evidence-Preserving Dependency Model

- **Date:** 2026-08-27
- **Decision:** Each dependency must store `service_a`, `service_b`, `resource`, `resource_type`, `evidence`, `judge_result`, `confidence`.
- **Context:** A finding that "A depends on B" is useless without *why* (which shared resource caused it).
- **Consequence:** Dependency Model is append-only with provenance; Graph and Report render `resource`/`evidence` not just edges.

## D-005: Shared Names ≠ Dependencies (Near-Miss Handling)

- **Date:** 2026-08-27
- **Decision:** Identical names/paths do NOT automatically imply dependency. Filter obvious coincidences before LLM; LLM judges coincidence vs coupling. Canonical example: shared `PORT` must not be flagged.
- **Context:** Naive shared-var detection would be noisy and lose trust.
- **Consequence:** Stage 3 (Candidate Filtering) is mandatory — builds evidence, reduces LLM cost, and encodes heuristics (common generic vars, path patterns). Requires deliberate near-miss synthetic test case.

## D-006: Graph as Primary Demo Artifact

- **Date:** 2026-08-27
- **Decision:** Use `networkx` + `matplotlib`; graph visualizes services + hidden dependencies + resource responsible for each edge.
- **Context:** Stakeholders need visual proof of hidden coupling.
- **Consequence:** Graph stage must accept Dependency Model output and label edges with `resource`/`resource_type`.

## D-007: Tier 2 Extensibility via Same Pipeline

- **Date:** 2026-08-27
- **Decision:** AST-based source analysis and DB table-name detection must feed into existing `Discovery → Filtering → LLM Judge → Model → Graph → Report` pipeline, not a parallel architecture.
- **Context:** Keeps codebase simple; allows adding new candidate sources without duplicating judgment/modeling.
- **Alternative Rejected:** Separate AST pipeline.
- **Consequence:** Candidate Discovery must be pluggable; candidate schema must include `resource_type = "db_table"` / `"code_reference"` etc.

## D-008: Technology Choices

- **Date:** 2026-08-27
- **Decision:** Python 3.10+, `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, stdlib `ast` for Tier 2. Docker optional (read compose as text).
- **Context:** Keeps dependencies minimal, matches AGENTS.md, avoids requiring running services for analysis.
- **Consequence:** No `docker` SDK needed at Tier 1; parsing must handle compose spec edge cases manually.

## D-009: Build Order

- **Date:** 2026-08-27
- **Decision:** Build in order: synthetic repos → parser → discovery → filtering → LLM judge → model → graph → real-world validation → Tier 2 AST.
- **Context:** Parser/discovery are foundations; synthetic fixtures enable TDD; Tier 2 must not block Tier 1 demo.
- **Consequence:** Do not start AST work until Tier 1 is demoable with synthetic + 1 real-world repo.

## D-010: Global Model Default

- **Date:** 2026-08-27
- **Decision:** Set opencode global default model to `opencode/muse-spark-1.2-contributor-free` in `~/.config/opencode/opencode.jsonc`.
- **Context:** User requested Muse Spark 1.2 free as startup default.
- **Consequence:** All sessions use Muse Spark unless project `opencode.jsonc` overrides `model`.

## D-011: Final Project Plan Committed — Pace and Guaranteed Core

- **Date:** 2026-08-28
- **Decision:** Commit final plan (`PROJECT_PLAN.md`) built for 1–2 hrs/day with guaranteed Tier 1 core and bonus Tier 2. Build order locked to 7 phases; Tier 1 demoable after Graph, before any stretch.
- **Context:** Prior plan left pace implicit and allowed AST to block Tier 1.
- **Consequence:** Tier 1 must be shippable alone (synthetic + 1 real repo); Tier 2 cannot be started until Tier 1 graph/report pass. Addresses hand-off risk if a bad week occurs.

## D-012: Tier 2 Scope Change — Kubernetes Replaces AST

- **Date:** 2026-08-28
- **Decision:** Tier 2 is Kubernetes manifest support (YAML parsing, workload normalization, shared ConfigMap/Secret/shared-volume detection) feeding existing pipeline; AST/source-code table-name detection removed from scope.
- **Context:** AST learning curve unpredictable; K8s uses same config-parsing skill as Tier 1, lower novel-concept risk, reuses pipeline.
- **Consequence:** No `ast` dependency; candidate source becomes K8s workloads instead of code references. Must not create separate downstream architecture for K8s findings.
- **Supercedes:** D-007 (AST extensibility), D-009 (Build Order with AST)

## D-013: Resource-Based Graph — Service-to-Resource, Not Service-to-Service

- **Date:** 2026-08-28
- **Decision:** Graph visualizes bipartite `service → resource ← service` (e.g. `orders → DB_HOST=postgres ← reports`) with distinct node styles; do not render hidden coupling as direct `orders — reports` edge.
- **Context:** Direct edge falsely implies network call; resource node explains mechanism.
- **Consequence:** Graph stage consumes dependency model with `resource`/`resource_type`; uses `networkx` + `matplotlib` with two node classes; demo artifact must label resource nodes.
- **Supercedes:** D-006 (graph as service-service edges)

## D-014: LLM Verdict Caching — Local cache.json with Evidence-Bound Keys

- **Date:** 2026-08-28
- **Decision:** Cache LLM judgments in `cache.json`; cache key = candidate + relevant evidence (not just variable/value); reuse valid verdicts across runs.
- **Context:** LLM calls expensive and non-deterministic; repeated analysis must be stable and cheap; same value can mean different things in different service contexts.
- **Consequence:** Judge stage must hash evidence; cache file gitignored; consistency validation still requires running judgment >1× before trusting cache.

## D-015: Parse + Normalize — env_file, Interpolation, and Messy-Fixture Contract

- **Date:** 2026-08-28
- **Decision:** Parser must support `env_file` (string or list, `str` or `{path, required}`), `${VAR_NAME}` interpolation with unresolved preserved, and (implemented 2026-08-28) multi-file `Union[Path,List[Path]]` deep-merge (env updated, volumes appended/unioned). Fixtures must be deliberately messy: comments, interpolation, `env_file` usage.
- **Context:** New `AGENTS.md` §1 and `PROJECT_PLAN.md` §7 Phase 1 require these for realistic coupling; prior fixtures were clean and ignored `env_file`.
- **Consequence:** `parser.py:84` `load_env_file` preserves `""` for `VAR=` (downstream LLM must treat `""` as intentional); `parser.py:352` `_load_service_env_files` merges env_file with explicit `environment:` overriding (Docker spec). Fixtures need refresh to satisfy ground truth; existing 32 tests remain valid but not sufficient.

## D-016: Dependency Model Clarification — Service-to-Resource

- **Date:** 2026-08-28
- **Decision:** Dependency records are service-to-resource relationships (with `service_a`, `service_b`, `resource`, `resource_type`, `evidence`, `judge_result`, `confidence`) explaining coupling through shared resource, not asserted direct service-to-service call.
- **Context:** Required for resource-based graph and honest reporting.
- **Consequence:** Model must carry provenance; report renders resource + evidence + confidence.
- **Supercedes:** D-004 (previous wording implied service-to-service edge)

## D-017: Deliberately Messy Fixtures + Fixture Env Tracking

- **Date:** 2026-08-28
- **Decision:** Refresh 3 fixtures to be deliberately messy per `PROJECT_PLAN.md:205` Phase 1: `shared_env` (`docker-compose.yml` + `.env:DB_HOST` + `common.env:DB_NAME` with comments/`${VAR}`/fallback/`env_file` string vs list), `shared_volume` (`+ .env:DATA_PATH` with `${DATA_PATH}`), `near_miss` (`+ .env`/`common.env` with `APP_ENV`/`SHARED_NOISE`, `PORT` different values). Patched `.gitignore:9` with `!fixtures/**/.env` + `!fixtures/**/common.env` so env files are tracked (otherwise `.env` ignored).
- **Context:** Final `AGENTS.md:31` requires `env_file` + `${VAR}` handling; messy fixtures prove parser handles real-world noise while keeping invariants (`DB_HOST=shared-db`/`DB_NAME=orders`, `shared-data:/data`, `PORT 8000≠9000`).
- **Consequence:** Fixtures now produce 3/2/3 candidates (extra `SHARED_EXTRA`, `DATA_PATH`, `SHARED_NOISE`/`APP_ENV` shared) — intentional noise for discovery/filtering. Existing 32 parser tests still pass; manual parse checks verify `SHARED_EXTRA=keep` etc. Fixtures are now tracked and deterministic.

## D-018: Candidate Discovery — Pairwise Shared Config/Volume

- **Date:** 2026-08-28
- **Decision:** `src/blindspot/discovery.py:19` `Candidate(service_a, service_b, resource, resource_type, evidence)` frozen + `discovery.py:35` `discover_candidates(Project)`: sorted service pairs via `itertools.combinations`, env `env_var` (same key → candidate; `resource=key=value` when same non-None value else `key`, evidence notes `different values (a=... vs b=...)`), volumes only `type=="named"` with `source` (ignore bind/anonymous), `resource=source` with evidence including `target` + type + targets-differ note, sorted by `(service_a, service_b, resource_type, resource)`.
- **Context:** Stage 2 must find possible couplings without deciding dependency (`AGENTS.md:52`) — filtering (Stage 3) and LLM (Stage 4) decide. Messy fixtures yield 3/2/3 candidates, correctly handling `${VAR}`-resolved values and `env_file`-merged envs.
- **Consequence:** `shared_env` yields `DB_HOST`/`DB_NAME` (+ extra), `shared_volume` yields `shared-data` (+ `DATA_PATH` env), `near_miss` yields `PORT` (different values evidence) etc — all discovered. `__init__.py` exports `Candidate`/`discover_candidates`. 8 new tests in `tests/test_discovery.py:1` (3 fixture + 5 unit: different-values, same-value, bind/anon ignored, named volume, 3-service pairs) — total 40 passed.

## D-019: Candidate `value` Split — Cleaner Downstream Pipeline

- **Date:** 2026-08-28
- **Decision:** Change `Candidate` to `Candidate(service_a, service_b, resource, resource_type, value, evidence)` where `resource` is bare key/name (`DB_HOST`, `shared-data`) and `value` is shared value (`postgres`) or `None` (mismatched env or volumes). Was `resource="DB_HOST=postgres"`.
- **Context:** Requested structural change to make filter→LLM→model→resource graph cleaner — downstream stages can use `resource` + `value` without parsing `resource` string. Volumes naturally have `value=None`.
- **Consequence:** `discovery.py:20` now `value` field, `discovery.py:65` sets `value=val_a` when equal else `None`, volumes `value=None`; `test_discovery.py` updated to check `resource`/`value` split (e.g. `DB_HOST` + `shared-db`); filtering can branch on `value is None` for `PORT` different-values case. Total still 40→48 after filtering stage, no behavior change except cleaner API.

## D-020: Candidate Filtering — Deterministic Generic-Key Heuristics

- **Date:** 2026-08-28
- **Decision:** `src/blindspot/filtering.py:12` `GENERIC_ENV_KEYS` (`PORT`, `HOST`, `DEBUG`, `LOG_LEVEL`, `APP_ENV`, `DATA_PATH`, `SHARED_EXTRA`/`SHARED_NOISE` etc) + `filtering.py:41` `_decide`: drop `different values` (same key `value is None` + evidence notes different values, e.g. `PORT 8000 vs 9000`), drop generic keys, keep `named_volume` always, keep specific env (`DB_HOST`/`DB_NAME`) with enriched evidence `filter: kept — …`.
- **Context:** Stage 3 must reduce obvious coincidences before expensive LLM calls (`AGENTS.md:65`), conservative — don't claim generic can never be coupling but filter obvious noise. Messy fixtures give 3/2/3 candidates, filtering yields 2/1/0 (shared_env 2, shared_volume 1 `shared-data`, near_miss 0).
- **Consequence:** `filter_candidates:22` returns kept list sorted, `filter_with_reasons:33` for reporting; `tests/test_filtering.py:1` 8 tests (fixture + generic/unit/bind) — total 48 passed; downstream LLM sees only likely-meaningful candidates (2+1 on fixtures).

## D-021: Hybrid Architecture Modification — Bounded Evidence

- **Date:** 2026-08-29
- **Decision:** Adopt hybrid deterministic + LLM with Stage 3 bounded evidence construction/resolution and Stage 4 one call per surviving candidate (0 for obvious noise). Update `AGENTS.md:1` ( hybrid diagram, §3 bounded package spec, §4 `verdict: meaningful|coincidental|uncertain` + `confidence` mandatory, `cache.json` candidate+evidence key, §5 `evidence` bounded + `verdict/confidence/reason`) and `PROJECT_PLAN.md:1` (301 LOC, evidence build order, bounded package contents). No multi-prompt per evidence item; `uncertain` allowed.
- **Context:** Previous Stage 3 only filtered generic keys without machine-verified resolution; LLM was expected to infer infrastructure from names alone (`DB_HOST=postgres` weak). New spec requires deterministic resolution (value → Compose service + image, internal/external, volume identity, related config bounded) before LLM interprets meaning.
- **Consequence:** `AGENTS.md` 522 LOC + `PROJECT_PLAN.md` 301 LOC; Stage 3 now defined as filter + evidence construction, Stage 4 cost model `0 + 1/candidate` with structured output.

## D-022: Parser Image Field for Evidence Resolution

- **Date:** 2026-08-29
- **Decision:** Add `Service.image: Optional[str]` to `src/blindspot/parser.py:45`, capture `image` in `parse_compose_file:487` and `parse_compose_string:505`, preserve in `to_dict` + merge in `_merge_projects:397` (later overrides). Required for Stage 3 evidence resolution `DB_HOST=postgres → postgres service postgres:16`.
- **Context:** Prior `Service` only had `environment` + `volumes`; bounded evidence requires image information to give LLM machine-verified facts.
- **Consequence:** `parser.py` 523→540 LOC; fixtures `shared_env` db `postgres:15` and `shared_volume` images now preserved; multi-file merge correct; 48 tests still pass.

## D-023: Stage 3 Bounded Evidence Package

- **Date:** 2026-08-29
- **Decision:** Extend `src/blindspot/filtering.py:70` with `EvidencePackage` dataclass + `build_evidence_package:180` (deterministic `value→service` resolution only for HOST/URL-like keys via `_is_host_like_resource`, `host:port` split, `volume_targets`, `related_config` prefix-bounded max 5/svc, filtering signals `generic_variable/same_value/resolved_reference`), `build_evidence_packages:210` (filter + one package per survivor), `filter_and_build_evidence`, `cache_key_dict:130` (service A/B, resource, type, value, resolved_service/image, related_config). Keep `filter_candidates` backward compatible.
- **Context:** Implements `AGENTS.md §3b` and `§4 Bounded evidence package` + `§7 Verdict Caching` key requirements without multi-LLM calls. Correctly handles `DB_HOST=postgres:5432 → postgres:16`, `DB_NAME=orders` not HOST-like → `external` (not false `compose_service` to `orders` app), named_volume `shared-data` internal with `volume_targets`.
- **Consequence:** `filtering.py` 110→340 LOC; manual verification: `shared_env` 2 pkgs (DB_HOST external + related DB_* bounded, DB_NAME external), `shared_volume` 1 pkg (named_volume internal), `near_miss` 0; 48 tests still pass; prepares Stage 4 `one package → one LLM call` interface.

## D-024: Stage 4 LLM Judge — One Call Per Package with cache.json

- **Date:** 2026-08-29
- **Decision:** Add `src/blindspot/judge.py:18` `JudgeResult{verdict: meaningful|coincidental|uncertain, confidence:0-1, reason, model}` + `judge.py:60` `build_judge_prompt` (A/B, SHARED CONFIG, VALUES, RESOLUTION, RELATED, FILTERING per mod §5) + `judge.py:85` `_cache_key_for_package` (`sha256(cache_key_dict)`) + `judge.py:270` `judge_evidence_package`/`judge_evidence_packages` (0+1/candidate, `cache.json` hit? reuse : LLM → store, mockable). Provide `MockJudgeClient:160` (named_volume/compose_service→meaningful, generic→coincidental, DB_* external→meaningful else uncertain) and `FixedJudgeClient:200` for tests; validate with spec §6 `confidence` mandatory.
- **Context:** Spec requires `cache.json` candidate+evidence-aware key (not just `value`), structured output with schema validation, single LLM call per evidence item, pluggable client so CI needs no API key. Prior stages now produce `EvidencePackage` ready for narrow prompt.
- **Consequence:** `judge.py` 361 LOC; manual mock: `shared_env` 2→2 meaningful (`DB_HOST/DB_NAME external` 0.78), `shared_volume` 1→meaningful (`named_volume` 0.92), `near_miss` 0→0 calls, second run with different client served from cache (mock model retained), cache key changes when value changes; `.gitignore:39` `cache.json`, `__init__.py:1` exports `JudgeResult`; 48 tests still pass; real LLM (OpenAI/Claude) can replace `MockJudgeClient` without changing pipeline.

---

### Template for Next Entry

```md
## D-0XX: Title
- **Date:** YYYY-MM-DD
- **Decision:** ...
- **Context:** ...
- **Consequence:** ...
- **Supercedes:** D-00Y (if any)
```
