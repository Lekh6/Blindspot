# DECISIONS.md — Architecture Decisions

> Why BlindSpot looks the way it does. Append-only log — never delete, only supercede with new entry.

**Last Updated:** 2026-09-07

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
- **Superceded by D-025 (real provider-agnostic, mocks removed)**

## D-025: Stage 4 LLM Judge — Real Provider-Agnostic (Gemini + OpenRouter Nemotron Ultra)

- **Date:** 2026-09-04
- **Decision:** Replace mocks with real provider-agnostic judge: `src/blindspot/judge.py:31` `GEMINI_DEFAULT_MODEL gemini-3.7-flash`/`GEMINI_FAILSAFE_MODEL gemini-3.1-flash-lite` + `judge.py:36` `OPENROUTER_DEFAULT_MODEL nvidia/nemotron-3-ultra-550b-a55b` + `DEFAULT_MODEL` = ultra + `judge.py:259` `GeminiJudgeClient` (google-genai, `GenerateContentConfig` with `ThinkingConfig(thinking_budget)` low1024/medium4096, `response_mime_type application/json`, lazy `type: ignore` import, fallback to flash-lite) + `judge.py:475` `OpenRouterJudgeClient` (openai SDK, `base_url https://openrouter.ai/api/v1`, `model nvidia/nemotron-3-ultra-550b-a55b`, `response_format json_object`, `OPENROUTER_MAX_TOKENS` low512/medium1024, regex JSON extraction for Nemotron `Here's a thinking process` prefix) + `judge.py:226` `failsafe_result` (`uncertain 0.5`, `FAILSAFE_MODEL`) + `judge.py:81` `build_judge_prompt` remains provider-agnostic + `judge.py:582` `judge_evidence_package` (`0+1/candidate`, `cache.json` `sha256`). Remove `MockJudgeClient`/`FixedJudgeClient`; add `placeholder_future_judge`. Store keys in `.env` (`GEMINI_API_KEY` + `OPENROUTER_API_KEY`, gitignored), `requirements.txt` `google-genai==0.8.0` + `openai==1.102.0`.
- **Context:** Prior D-024 was mock-only; spec requires real LLM judgment with `uncertain` allowed and `confidence` mandatory. User requires Gemini not privileged — prompt/architecture must remain model-agnostic, providers pluggable. Nemotron Lightning free failed `json_object` (returned reasoning text), fixed via regex extraction. Testing needs low/medium thinking dynamically via `set_thinking_level()`.
- **Consequence:** `judge.py` 361→687 LOC; `__init__.py` exports `GeminiJudgeClient` + `OpenRouterJudgeClient`; sampleruns: artificial 3 pkgs all `meaningful 0.9-0.95` on both Gemini 3.7 and Nemotron Ultra (low), fixtures `shared_env 2→2 meaningful 0.9 (Ultra)`, `shared_volume 1→0.95`, `near_miss 0`; cache hit verified; 48 tests still pass; LSP `type: ignore` silences `google.genai`/`openai` missing stubs but runtime imports ok; real LLM replaces mock without pipeline change, provider switch via `DEFAULT_MODEL` or client choice.
- **Supercedes:** D-024 (mock judge)

## D-026: Stage 5 Dependency Model — Service-to-Resource with Model Hidden

- **Date:** 2026-09-04
- **Decision:** Add `src/blindspot/model.py:27` `Dependency{service_a/b, resource, resource_type, value, evidence: EvidencePackage, verdict, confidence, reason, _model(hidden), cache_key, created_at}` frozen + `model.py:108` `DependencyModel{dependencies: List[Dependency], sorted (service_a, service_b, resource_type, resource), meaningful_only(), to_list()/to_log_list(), to_json(), save(), from_judgments:141, from_list, build_dependency_model:158}`. Pipeline `Stage 4 List[Tuple[EvidencePackage,JudgeResult]] → Stage 5 DependencyModel` via `Dependency.from_evidence_judgment:52` (validates `JudgeResult`, `hashlib.sha256(cache_key_dict)`, `logging.debug` with model). External `to_dict:67` omits `_model` (`field(repr=False, compare=False)`) — user never sees provider; internal `to_log_dict:77` adds `{"_log": {model, cache_key, created_at}}` for audit (`cache.json` + `logging.getLogger("blindspot.model")`). `__init__.py` exports `Dependency`/`DependencyModel`/`build_dependency_model`.
- **Context:** `AGENTS.md §5` requires service-to-resource with evidence + verdict/confidence/reason preserved for Stage 6 Graph (bipartite, no service→service edge) and Stage 7 Report. User instruction: do not expose `model` in external dependency output — log internally only. Prior `Dependency` spec implied `model` external; this corrects to model-blind external, model-audited internal, preserving provider-agnostic prompt/architecture.
- **Consequence:** `model.py` 160 LOC; verified fixtures `shared_env 2→2 deps`, `shared_volume 1`, `near_miss 0`, artificial 3 pkgs, `external to_dict` `model` leak `False`, `to_log_dict` retains `nvidia/nemotron-3-ultra-550b-a55b`/`gemini-3.1-flash-lite`; `DependencyModel` sorted deterministically; 48 tests still pass; Stage 6 Graph will consume `DependencyModel` (not raw `JudgeResult`), Stage 7 Report will expose confidence without model.

## D-027: Stage 6 Re-Architecture — React Flow DATA Contract, Not PNG

- **Date:** 2026-09-04
- **Decision:** Modify `AGENTS.md §6` from `networkx+matplotlib` PNG primary to **React Flow DATA contract**: Stage 6 `src/blindspot/graph.py` consumes `DependencyModel` (normally `meaningful_only()`) via `build_graph(model, meaningful_only=True)` and produces deterministic, JSON-serializable, provider-agnostic `{"nodes": [{"id": "service:orders", "type": "service", "data": {"name": "orders"}}, {"id": "resource:env_var:DB_HOST=postgres", "type": "resource", "data": {"name": "DB_HOST=postgres", "resource_type": "env_var", "value": "postgres"}}], "edges": [{"id": "service:orders->resource:env_var:DB_HOST=postgres", "source": "service:orders", "target": "resource:env_var:DB_HOST=postgres", "data": {"confidence": 0.93}}]}` bipartite `Service ↔ Resource` (`orders → DB_HOST=postgres ← reports`, never `orders—reports`). Resource deduplication by deterministic `resource_key` helper (`resource_type:resource[=value]` so `env_var:REDIS ≠ named_volume:REDIS`); multiple resources between same services kept separate; confidence preserved from Stage 4/5, never calculated/modified; model/provider never exposed in nodes/edges; `networkx` optional internally only, not the contract; `matplotlib`/`graph.png` not primary; `STATE.md`/`HANDOFF.md`/`README.md` updated; future `data` extensible with `directory`, `source_locations:[{file,line}]` without changing architecture.
- **Context:** Original `AGENTS.md §6` specified `networkx+matplotlib` `graph.png` as primary demo artifact. Final BlindSpot application will be interactive React Flow frontend (Obsidian-like exploration) — graph must be correct DATA contract from the beginning: `DependencyModel → Stage 6 Graph Builder → Graph JSON → Future API → React Flow` not `DependencyModel → Matplotlib → PNG`. Prompt/architecture already provider-agnostic after D-025; graph must also be provider-agnostic and hide model per D-026. Edge cases (empty model, duplicate resources, same name different types, multiple resources, no meaningful) and tests (bipartite, no service-service edges, dedup, confidence, model hidden, determinism, JSON serializable, extensibility) are now explicit requirements. No new filtering/LLM/layout/React code is added — scope limited to DATA contract.
- **Consequence:** `AGENTS.md` §6 rewritten (522 LOC, bipartite + JSON example + dedup + confidence + model + determinism + React Flow direction); `STATE.md` §2 Stage 6 re-arched to `{"nodes","edges"}` DATA, `§3` `graph.py` spec with `build_graph`; `HANDOFF.md` §3 Stage 6 DATA spec (flexible `meaningful_only`), `§4` `Resource graph (RE-ARCHED)` gotcha; `README.md` pipeline `→ Resource Graph (DATA, React Flow)` + DATA example + graph quick start `build_graph(m, meaningful_only=True)`; implementation of `graph.py` and Stage 6 tests is next; PNG generation becomes optional non-primary; frontend will handle layout/zoom/pan/selection/evidence panels via clean data.
- **Supercedes:** Prior `AGENTS.md §6` PNG primary (supersedes D-013 resource-based graph as PNG and D-006 PNG generation)

## D-028: Stage 7 Report + One-Command CLI for Repo Testing

- **Date:** 2026-09-04
- **Decision:** Add `src/blindspot/report.py:22` `ReportFinding{service_a/b, resource, resource_type, value, evidence, verdict, confidence, reason}` + `report.py:84` `ReportData{findings, summary{total/meaningful/coincidental/uncertain/reported/services/resources}, graph_summary{nodes/edges/service_nodes/resource_nodes}, generated_at}` + `build_report(model, graph_data, meaningful_only=True)` → `to_dict()/to_json()/to_markdown()` (findings `service_a/b, resource, resource_type, value, evidence{resolved/related/filtering}, verdict, confidence, reason` per `AGENTS.md §7`, model hidden) + `src/blindspot/cli.py:1` `blindspot` CLI — one-command full pipeline for one/many repos: `parse_compose_file` → `discover_candidates` → `build_evidence_packages` → `judge_evidence_packages` (0+1/candidate, cached) → `DependencyModel.from_judgments` → `build_graph(meaningful_only)` → `build_report` → `out/<repo>/report.json+report.md+graph.json+report.log.json`. CLI args `--compose --out out --provider auto|openrouter|gemini --thinking none|low|medium|high --cache cache.json --all --list-fixtures`, `find_compose` auto-finds `docker-compose.yml/compose.yml`, `out/<repo>/report.log.json` holds internal `model+provider` log, `report.json`/`graph.json` hide model, deterministic, provider-agnostic, ASCII-safe output, `.env` keys, `.gitignore` `out/`+`report.json`.
- **Context:** `AGENTS.md §7` requires report exposes `evidence (including resolution + related) + dependency type + verdict/reason + confidence` without model; prior priority was Stage 7 Report next then real-world validation on 1 OSS repo. User requested user-friendly way for most people to test one or more repos — need no code edits, just `pip install -r requirements.txt` + `.env` + one command, with multiple repos and summary table.
- **Consequence:** `report.py` 170 LOC + `cli.py` 250 LOC; `__init__.py` exports `ReportData/ReportFinding/build_report`; `README.md` Quick Start rewritten for `blindspot` CLI (single, multiple, options, reading results, determinism/cost); `STATE.md` Tier 1 100% (code) Stages 1–7 done, validation next, `HANDOFF.md` documents CLI usage; manual `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` → `2 meaningful /2 total`, `shared_volume 1`, `near_miss 0` with `report.md`/`graph.json`; `61 tests` still pass; Tier 1 demoable without editing code.

## D-029: Tier 1 Redesign — Bounded Resolution with Distinct States + Normalized Resource Identity

- **Date:** 2026-09-06
- **Decision:** Replace `external/unknown` conflation with distinct `internal` / `external_confirmed` / `partial` / `unresolved` via new `src/blindspot/resolution.py:1` (`ResolutionResult`/`ResolutionStep`, `bounded_resolve:270`, `MAX_RESOLUTION_DEPTH=10`, cycle detection, deterministic lookup from `Compose/.env/env_file` sorted, `_normalize_connection_identity` for `postgresql/postgres/mysql/mongodb/mongodb+srv/redis/rediss` stripping credentials to `protocol|host|port|db`, `identity_strength` `exact/config/unknown`). Extend `src/blindspot/filtering.py:68` `EvidencePackage` with `resolution_status/normalized_identity/resource_protocol/identity_strength/chain/final_value/unresolved_vars/is_cyclic/depth`, `_decide_with_project:386` keeps different raw that normalize same, update `judge.py:96` prompt to render chain/status/identity + confidence guidance `exact 0.85-1.0 / config 0.6-0.85`, update `graph.py:76` dedup by `normalized_identity` else legacy, update `report.py:105` chain/identity markdown, update `model.py:218` rehydration, update `cache_key_dict` to include `normalized_identity/resolution_status/final_value`. Add `tests/test_resolution.py` 17 tests.
- **Context:** Tier 1 redesign spec requires tracing `${DATABASE_URL} → postgresql://...` chains bounded, not treating unresolved as external, value-structure not variable-name dictionary, distinguishing `same configuration` vs `proven same physical` (`exact`/`config`/`unknown`), stronger evidence before LLM so confidence reflects evidence strength. Prior `HOST/URL-like` guard insufficient for `DATABASE_URL=postgresql://...` external confirmed and `DB_NAME=orders` false internal. Need Cal.com validation (`DATABASE_DIRECT_URL=${DATABASE_URL} → database` image).
- **Consequence:** `resolution.py` 607 LOC + `filtering.py` 530 LOC + `judge.py` 750 LOC + `graph.py` 230 LOC + `report.py` 210 LOC; fixtures now honest `shared_env` `unresolved config` (not `external`) with `config` strength, `shared_volume` `internal`, `calcom` chain `internal exact postgresql|database||calcom` with 5-step chain; graph dedup strips credentials (`user1:pass@db` ≡ `user2:pass@db`); `cache.json` keys rotated (old entries coexist but new keys include normalized); 78 tests pass (32+8+8+13+17); `README.md`/`STATE.md`/`HANDOFF.md` updated with Windows absolute-path quoted command `set PYTHONPATH=src && python -m blindspot.cli "C:\Users\Lekha\Projects\Docker" --out out\calcom --thinking low` (venv note for `ModuleNotFoundError: No module named 'yaml'`); docs now reflect `MAX_RESOLUTION_DEPTH`, `normalized_identity`, `identity_strength`.
- **Supercedes:** D-023 (HOST/URL-like bounded evidence only)

---

## D-030: Prompt 2 — Resource-Centric Aggregation, Grouped LLM Judgment, Graph/Report Alignment

- **Date:** 2026-09-06
- **Decision:** Move from pairwise `Candidate → LLM → pairwise finding` to `observations → deterministic resolution → normalized resource identity → resource-centric aggregation → one bounded GroupedEvidencePackage per shared resource → one LLM judgment per group → one CouplingGroup → Graph + Report`. Add `src/blindspot/aggregation.py:1` (`GroupedEvidencePackage`, `aggregate_evidence_packages` grouping by `normalized_identity` primary, `raw:resource:value` fallback for unknown, never merge unrelated unknowns, deterministic, observations preserved as evidence) + `src/blindspot/coupling.py:1` (`CouplingGroup{CouplingGroup, resource_identity, protocol, status, strength, services[], config_evidence, verdict, confidence, reason, _model, cache_key}`, `CouplingModel`) as first-class grouped model before Graph/Report + `judge.py` `build_grouped_judge_prompt`/`judge_grouped_packages` (`0+1/group`, cache key `grouping_key/services/config/unresolved`, group-level verdict/confidence) + `graph.py` `build_graph_from_groups` (one node per group, one edge per service in group, bipartite, deterministic, provider hidden; Cal.com 3 svcs →1 node+3 edges) + `report.py` `GroupedReportData` redesign (Summary `services_analyzed/resource_groups/observations/meaningful_groups`, finding title `Shared PostgreSQL Database Configuration` not `postgresql|...`, conclusion→evidence→technical, no `generic_variable` in body, boundary statement) + `cli.py` grouped pipeline (`candidates→packages→grouped→judge→CouplingModel→graph→grouped_report`, minimal `Provider/Thinking/Out` output). Keep `DependencyModel` for backward tests.
- **Context:** Cal.com validation exposed `6 candidate observations →6 LLM judgments →6 meaningful findings` but `3 services →1 normalized identity →1 resource node +3 edges` — Graph correctly deduped but model/report still pairwise. Need resource-centric aggregation before LLM so user sees one coupling finding per shared resource, not six pairwise duplicates. Must preserve observations as evidence inside group, distinguish `Observation` vs `Resource Group` vs `Coupling Finding`, not merely hide duplicates in report.
- **Consequence:** `aggregation.py` 200 LOC + `coupling.py` 150 LOC + `judge.py` +150 LOC (grouped) + `graph.py` +120 LOC + `report.py` +190 LOC (grouped) + `cli.py` grouped pipeline + `tests/test_grouping.py` 14 tests (multiple vars same identity→one group, 3 services same resource→one group, different vars same identity grouped, same var different identity not grouped, unknown not over-merged, named volume group, graph counts from grouped, report counts distinguish, cache deterministic, empty, near-miss, deterministic ordering, config evidence grouped by service, prompt contains group info); fixtures `shared_env` 2 groups, `shared_volume` 1 group, `near_miss` 0, Cal.com 6 obs→1 group (3 svcs, DATABASE_URL/DIRECT_URL) →1 finding →1 node+3 edges (vs before 6 findings/1 node), `report.json` summary now `services_analyzed/resource_groups/observations/meaningful_groups`, `report.md` human-readable per spec §13-19; old pairwise `DependencyModel`/`build_graph`/`build_report` retained for tests; 92 tests pass.
- **Supercedes:** D-028 pairwise finding model for user-facing analysis (kept internally for tests)

## D-031: Interactive CLI Menu — Absolute C:\ Path + Thinking Validation

- **Date:** 2026-09-07
- **Decision:** Replace one-command README section with polished interactive menu as default: `src/blindspot/cli.py` shows banner `BlindSpot — Implicit Cross-Service Coupling Detector` and prompts for (1) absolute application path from `C:\` drive (quote-stripped, `is_absolute` + `drive C:` + `exists` + `is_dir` + `find_compose` warning with confirm, re-prompts with `[error]` on empty/relative/missing) and (2) AI thinking `low/medium/high` only (empty→`low`, `none` rejected, case-insensitive, `Ctrl+C` clean exit). On success prints summary `Application/Thinking/Output` and runs `run_one_repo` with `auto` provider. Keep advanced batch flags (`repos` absolute-path validated, `--thinking` limited to `low/medium/high`, `--interactive` to force menu, `--list-fixtures`) for scripting/tests. One-prompt section removed from `README.md:99` and replaced with `Quick Start — Interactive Menu` + `Advanced — flags` subsection.
- **Context:** User requested way simpler run: no memorizing `set PYTHONPATH=src && python -m blindspot.cli "C:\...\" --out ... --thinking low`; just run script and answer questions. Path must be absolute from `C:\` root (Windows) and thinking only `low/medium/high`. CLI must be polished/neat with proper error/edge-case handling.
- **Consequence:** `cli.py` 237→~360 LOC (`_print_banner`, `_strip_quotes`, `_is_absolute_windows_path`, `_prompt_absolute_path`, `_prompt_thinking`, `_run_interactive`, `main` detects `len(sys.argv)==1` → interactive); `README.md` installation unchanged, `Quick Start` now shows interactive session example + `Advanced` collapsed; `STATE.md`/`HANDOFF.md` updated; 92 tests still pass; batch `python -m blindspot.cli "C:\path" --thinking low` still works but now validates absolute `C:\` path.

## D-032: Repository Sweep — Simple Errors & Future Edge Cases

- **Date:** 2026-09-07
- **Decision:** Audit all 10 source modules for simple errors / future edge cases and apply low-risk defensive fixes without changing pipeline semantics.
- **Context:** Pre-Tier 2 sweep requested to catch cheap bugs before they compound. Systematic read of `parser.py:1`, `discovery.py:1`, `resolution.py:1`, `filtering.py:1`, `aggregation.py:1`, `coupling.py:1`, `judge.py:1`, `model.py:1`, `graph.py:1`, `report.py:1`, `cli.py:1`, `__init__.py:1`.
- **Findings & Fixes (done):**
  - `__init__.py:1` `__all__` listed `placeholder_future_judge` but import missing → added import so `from blindspot import placeholder_future_judge` works.
  - `cli.py:224` `out_dir = (out_root/repo_name) if is_dir else parent` + `if len(sys.argv)>2` hack fragile, plus `Path("C:\\").name == ""` → empty out dir. Fixed to deterministic `out_root.suffix` check and `repo_name or "repo"` fallback `cli.py:225`.
  - `cli.py:250` no API-key warning → silent failsafe `uncertain 0.5` confusing. Added visible `[warning]` when `auto` finds no `OPENROUTER_API_KEY`/`GEMINI_API_KEY`.
  - `parser.py:75` `_load_yaml` no `YAMLError`/`UnicodeDecodeError` context. Wrapped with `ValueError(... not valid YAML/UTF-8)` `parser.py:79`.
  - `parser.py:356` `_load_service_env_files` silently dropped missing `required:true` env_file. Now logs `logging.warning` for both required and optional missing `parser.py:385`.
  - `resolution.py:335` dead variables `progressed`/`next_value` left from refactor. Removed `resolution.py:339`.
  - `judge.py:632` `_parse_or_failsafe` regex `\{[^{}]*"verdict"[^{}]*\}` fails when `reason` contains braces. Added balanced-brace extractor as primary, regex fallback `judge.py:646`; same for grouped `judge.py:976` `OpenRouter` path — prevents malformed-JSON failsafe on nested reason.
  - `judge.py:294` `_save_cache` direct `write_text` risks corruption on crash/concurrent runs. Now atomic via `tempfile.mkstemp` + `Path.replace` with fallback `judge.py:305`.
  - `report.py:448` `GroupedReportData.to_markdown` returned early without boundary when `findings` empty, inconsistent with non-empty. Added boundary `report.py:450`.
  - `aggregation.py:190` capped `obs_list` at 20 silently. Now logs `warning` with group key and original count `aggregation.py:192`.
  - `cli.py:195` `find_compose` called `rglob` 4 times per repo. Optimized to top-level check first then single `rglob` scan sorted shallowest-first `cli.py:198`.
  - `cli.py:246` `parse_compose_file` exception bubbled as traceback in interactive mode. Wrapped in `try/except` → returns error `report.json/md/graph.json` empty graph and `result["error"]` `cli.py:246`.
- **Findings & Not Fixed (documented for future, low risk / Tier 2 relevant):**
  - `resolution.py:170` `mongodb://host1,host2/db` multi-host cluster only captures first host via `parsed.hostname`; full cluster identity would need comma-split handling.
  - `filtering.py:40` dual `_decide` vs `_decide_with_project` duplication — keep for backward compat but risk drift; future should unify.
  - `judge.py:THINKING_BUDGETS` still contains `"none":0` while CLI only allows `low/medium/high`; kept for backward API but unused in CLI.
  - `cli.py:57` `_is_absolute_windows_path` on non-Windows falls back to `is_absolute` only — cross-platform tests pass but Windows `C:` semantic not enforced on Linux CI.
  - `parser.py:303` Windows volume `C:\host\path:/container` colon-splitting edge — not in Tier 1 fixture scope.
- **Consequence:** 12 low-risk fixes applied, 5 documented non-fixes. `92 tests` still pass; manual edge-case repro (relative path, missing key, `C:\` root, required env_file warning, unbalanced JSON reason) verified. Pipeline semantics unchanged; Tier 2 can start from clean baseline.

## D-033: General README + Deterministic Fallback + Simple Start (`run.py`)

- **Date:** 2026-09-07
- **Decision:** Make instructions general-purpose (no `C:\Users\Lekha\...` paths) and split `README.md` into **First Time Setup (one-time: `venv` + `pip install`)** vs **Running (every time: `python run.py`)**; remove explicit `echo OPENROUTER_API_KEY`/`GEMINI_API_KEY` commands — instead, if no API key is present in `.env`/`environ`, prompt **every run** with `Would you like to enter an API key? [Y/n]`: Y → paste `sk-or-...`/`AIza...` (detected, saved to `.env` + `os.environ`), n → deterministic-only mode (no LLM, `0` calls, `uncertain 0.0` via `_deterministic_pairs`, banner `Deterministic-Only Mode` in `report.md`, only structural JSONs, re-prompted next run). Add simple launchers `run.py` (`sys.path` insert `src`, calls `blindspot.cli:main`), `run.bat` (prefers `.venv\Scripts\python`), `run.sh` (prefers `.venv/bin/python`) so daily command is `python run.py` not `set PYTHONPATH=src && python -m blindspot.cli ...`. Update `src/blindspot/cli.py:30` (`_has_api_key`, `_prompt_for_api_key`, `_deterministic_pairs`, `deterministic_only` branch in `run_one_repo`, `run.log` `deterministic_only` flag, `_run_interactive` deterministic summary).
- **Context:** Previous README pointed to Lekha's absolute paths and required manual `echo` of API keys — not general. Pip/venv were mixed into everyday run instructions. Per request, service start must be a simple script, and API-key absence must be handled via Yes/No prompt with deterministic fallback (JSONs only, no AI reasoning) and re-prompt every time. `pip install`/`venv` must live only in First Time Setup.
- **Consequence:** `README.md` now general (`C:\path\to\YourApp`, `<path\to\Blindspot>`, `python run.py`/`run.bat`, First Time Setup vs Running split); `cli.py` ~440→~520 LOC with new helpers; `run.py`/`run.bat`/`run.sh` added; `STATE.md`/`HANDOFF.md` updated; 92 tests still pass; `python run.py` is now the primary documented entry point, `python -m blindspot.cli` remains as alternative.
- **Supercedes:** Prior README `Installation & Keys` + `Quick Start` user-specific sections

## D-034: Windows `input()` Fix — `run.py` `os.execv` → `subprocess.call`

- **Date:** 2026-09-07
- **Decision:** Replace `run.py:28` `os.execv(venv_python, ...)` (which on Windows does not preserve console handles for `input()` → typed `C:\...\docker` went to `cmd` as `'C:\...\docker' is not recognized as an internal or external command`) with `subprocess.call([venv_python, run.py] + argv)` + `SystemExit` preserving console; add graceful `ModuleNotFoundError: yaml` hint (use `run.bat` / activate venv) and keep `src` path insertion. On Unix, `subprocess.call` is also safe.
- **Context:** User ran `python run.py` (system `python` → auto-relaunch to `.venv\Scripts\python.exe` via `os.execv`), saw banner, typed `C:\Users\Lekha\Projects\docker` at `Enter absolute application path` prompt, but got cmd error instead of CLI validation — classic Windows `execv` console inheritance bug. Non-interactive `--help` still worked (no `input()` needed), but interactive `input()` failed.
- **Consequence:** `run.py` now correctly preserves console for `input()` on Windows; `python run.py` and `run.bat` both work interactively. Verified via `python run.py --help` (system python) and piped `C:\path\to\YourApp` + `low` flows (deterministic and with real key → 2 meaningful). `92 tests` still pass; docs updated to recommend `run.bat` on Windows as most robust.

## D-035: Fix `.env file not found` Spam (4×) — Dedup + Debug Level

- **Date:** 2026-09-07
- **Decision:** Change `src/blindspot/parser.py:362` `_load_service_env_files` to deduplicate missing `env_file` warnings via module-level `_warned_env_files: set[Path]` and lower generic `env_file: .env` missing from `WARNING` to `DEBUG` (so `C:\...\docker\docker-compose.yaml` with 5 services each `env_file: .env` no longer prints 4× `env_file not found: C:/.../.env` before output). Keep `required: true` missing as `WARNING` but deduped to once. Generic string-path missing now `debug` (invisible at default WARNING level).
- **Context:** User ran `python run.py` → `C:\Users\Lekha\Projects\docker` (which has `docker-compose.yaml` with services `database, calcom, calcom-api, studio` each `env_file: .env` and no `.env` present) and saw `.env file not found` 4 times before output. Each service triggered `logging.warning` for the same missing file, spamming the interactive banner.
- **Consequence:** `parser.py:355` now has `_warned_env_files` + `if ef_path not in _warned...` + `debug` for generic, `warning` (deduped) for `required:true`. Verified with `docker-compose.yaml` (5 services, same `.env`) → 0 visible warnings at `WARNING` level, 1 at `DEBUG`; `92 tests` still pass; `python run.py` on `C:\...\docker` now shows clean banner → `6 candidates → 1 group → 1 meaningful` with `0` env_file warnings.
- **Supercedes:** D-032 warning-spam behavior (4×)

## D-036: Versioned History Instead of Overwrites (`report_1.json` etc.)

- **Date:** 2026-09-07
- **Decision:** Replace overwriting `out/<app>/report.json` (and `.md`/`.log.json`/`graph.json`) on re-analysis with versioned history via `src/blindspot/cli.py:340` `_versioned_path(base)` — if `report.json` exists, next is `report_1.json` (then `_2`, `_3`...), `report.md` → `report_1.md`, `graph.json` → `graph_1.json`, `report.log.json` → `report_1.log.json` (special handling for double suffix). First run stays `report.json`; re-analyzing same `C:\path\to\YourApp` keeps previous files and writes new versioned set, not overwriting. Handles both error-path and success-path writes (`cli.py:389`/`403`/`487`).
- **Context:** User asked what happens on re-analysis with same folder name — previously it overwrote (`write_text` truncates). Requested simple file-name extension history, default `report.json` then `_1`, `_2` etc., instead of lossy overwrites.
- **Consequence:** `cli.py` ~620 LOC with `_versioned_path`; `run_one_repo` now returns `report.json`/`report.md`/`graph.json`/`report.log.json` versioned paths and prints `Out: .../report_1.json + ... (history kept)`; `README.md` Outputs section updated to show versioned history; verified with temp `out` (3 runs → `report.json`, `report_1.json`, `report_2.json` etc. all preserved); `92 tests` still pass.
- **Supercedes:** Overwrite behavior in `D-033`/`D-034`

## D-037: Input Transparency & Analysis Accounting (Prompt)

- **Date:** 2026-09-07
- **Decision:** Make pipeline observability first-class without changing detection semantics (`depends_on` still not Tier-1 evidence). Added `src/blindspot/parser.py:62` `Project.count_named_volumes()` (distinct `type=="named"`), `src/blindspot/cli.py:340` helpers `_discover_compose_sources`/`_relative_to_root` and full accounting dict (`application_root`, `sources.discovered/used`, `parsed.services/named_volumes`, `discovery.raw_candidates/observations/filtered_out`, `aggregation.resource_groups`, `judgment.groups_judged/llm_calls/cache_hits/meaningful`, `graph.nodes/edges`) computed at each stage in `run_one_repo` and passed to `src/blindspot/report.py:641` `build_grouped_report(..., accounting)` which now populates `GroupedReportData.application`/`inputs`/`analysis` and renders `report.json` top-level `application`/`inputs`/`analysis` + `summary` (compat) and `report.md` `Analysis input`/`Pipeline summary` with separate `Services discovered` vs `Candidates generated` and explanations for legitimate zero-result runs (`No Tier 1 candidates generated` vs `No services discovered`, `Candidates filtered`, `6 obs → 1 group`). CLI interactive/batch now same accounting (prompt §10).
- **Context:** `celery-docker-example` produced `Services analyzed : 0 candidates scanned` (ambiguous `0` could mean no services vs no candidates). Prompt requires distinguishing `No services discovered` from `5 services, 0 candidates → no supported Tier-1 evidence`. Must not change filtering/aggregation/graph/LLM behavior.
- **Consequence:** `report.json` now self-explanatory (example `celery` → `application.root`, `inputs.sources_used: ["docker-compose.yml"]`, `analysis.parsed.services:5, named_volumes:1, discovery.raw_candidates:0, observations:0, judgment.groups_judged:0`), `report.md` now `Analysis input` + `Pipeline summary` + `Result` explanations, CLI now `Input / Parsed / Analysis / Graph` sections with `llm_calls`/`cache_hits` when available. `98 tests` (92 + 6 `test_accounting.py` Cases A-F) pass; `celery` 5→0 now diagnosable, `docker` 5→6→6→1→1 still consistent; no detection semantics changed.

<<<<<<< HEAD
### Template for Next Entry

```md
## D-0XX: Title
- **Date:** YYYY-MM-DD
- **Decision:** ...
- **Context:** ...
- **Consequence:** ...
- **Supercedes:** D-00Y (if any)
```
=======
## D-038: Tier 1 Frozen + Honest Claims
- **Date:** 2026-09-27
- **Decision:** Tier 1 (Stages 1–7, Compose/.env shared-env + named-volume pipeline) is frozen; change only for concrete bugs/validation issues. Findings are **potential shared-resource coupling signals**, not proof of application-level read/write or runtime behavior. Reports/graphs keep `Service ↔ Resource` (never direct service edges) with evidence + confidence + provenance.
- **Context:** New direction requires preserving Tier 1 and not overstating findings; prior wording ("discovers couplings/dependencies") risked implying proven runtime dependency.
- **Consequence:** No `src/blindspot/*.py` changes under this direction-update; wording in future reports must use evidence tiers (see D-040).

## D-039: Tier 2 Reframed — Kubernetes-Backed Discovery, Proposal-First (No Implementation Yet)
- **Date:** 2026-09-27
- **Decision:** Kubernetes is central to the vision, not a minor stretch; but **no K8s adapter, dependency, or Tier 1 redesign until a concrete, testable Tier 2 capability is approved**. Mere K8s YAML parsing or "two workloads use the same database" is **not** a sufficient differentiator. The proposal below is the approval gate.
- **Context:** Current docs (`AGENTS.md` Tier 2, `PROJECT_PLAN.md` Phase 6, `STATE.md`/`HANDOFF.md` "implement K8s ConfigMap/Secret/volumes → same pipeline") treat Tier 2 as a straightforward re-skin of Tier 1 shared-config detection. New direction requires demonstrating what K8s reveals that Compose cannot.
- **Consequence:** `STATE.md`/`HANDOFF.md` next step is proposal review, not implementation. Preferred Tier 2 inputs: manifests and/or read-only K8s API; no eBPF/tracing/privileged agents. Secret values never exposed.

### Tier 2 proposal (concise, approval gate)
1. **Tier 1 gap:** Tier 1 discovers candidates by **identical env-var name within one Compose file** (`discovery.py` pairwise same-key). It is blind when (a) two workloads consume the **same underlying value under different env-var names** (e.g. `ORDER_TABLE` vs `BILLING_SOURCE_TABLE`), (b) references span **files/namespaces**, or (c) coupling is indirect via **ConfigMap/Secret key refs, Service DNS → Endpoints → StatefulSet, PVC/volumeClaimTemplates**. Different surface names + indirection ⇒ Tier 1 yields 0 candidates.
2. **Concrete K8s example (new relationship, not re-skinned config):** `orders-api` (ns `sales`) sets `ORDER_TABLE` from `ConfigMap/app-schema` key `orders.table` and `PGPASSWORD` from `Secret/pg-creds` key `password`; `billing-worker` (ns `finance`) sets `BILLING_SOURCE_TABLE` from the **same** ConfigMap key and `DB_PASS` from the **same** Secret key, under different env names. Both resolve to `Service/postgres.data` → `StatefulSet/postgres` (+ PVC). Tier 1 sees different var names ⇒ nothing. K8s sees **shared ConfigMap-key identity + shared Secret-key identity + shared Service DNS** ⇒ one resource group ⇒ potential hidden coupling on application-level state (`orders` table) across namespaces. A near-miss companion (same ConfigMap, **different** unrelated key) must judge `coincidental`.
3. **K8s objects/evidence needed:** `Deployment/StatefulSet/CronJob/Job` (env, `envFrom`, `valueFrom.configMapKeyRef/secretKeyRef`, volume mounts), `ConfigMap` (names + keys only), `Secret` (**names + keys only, never values**), `Service` + `Endpoints/EndpointSlice` (DNS → backing workloads), `PersistentVolumeClaim`/volumes (`volumeClaimTemplates`, storage refs), `Namespace` (scope for identity). Identity is `namespace/name/key` (or DNS), not bare var name.
4. **Source-code role: optional, not necessary.** Detection works from config refs alone (different env names → same key is already machine-verified). Source evidence (both repos reference the same table constant) may **strengthen/distinguish** but is not required; no query-level mapping, call graphs, or execution. Reasoning: requiring source would make Tier 2 a code-analysis project and block the K8s differentiator; making it optional preserves the mission while allowing stronger claims where available.
5. **Pipeline flow (reuse, not rewrite):** new K8s normalize/parse (future) → `Candidate(resource_type ∈ {configmap_key, secret_key, k8s_service, pvc, ...})` → deterministic filtering (generic keys, `kube-system` noise, standard ports) + bounded resolution (ConfigMap→workloads+keys; Secret name/key only; Service→Endpoints→workload; namespace scoping) → aggregation by **normalized K8s identity** → LLM judge (1/group, cached, evidence-tier-aware prompt) → Dependency/Coupling model (+ evidence tier) → resource-based graph (new K8s resource node kinds, still bipartite) → report (evidence tier + limits). No direct service-service edges; confidence + provenance preserved.
6. **Bounded PoC + fixture (proposed, NOT built):** `fixtures/k8s_schema_share/` — `configmap.yaml` (`app-schema`, keys `orders.table` + unrelated `feature.flag`), `secret.yaml` (placeholder `pg-creds`, key `password` only), `orders-api-deployment.yaml` (ns `sales`), `billing-worker-deployment.yaml` (ns `finance`), `postgres-service+statefulset.yaml`, `near-miss-deployment.yaml` (same ConfigMap, only `feature.flag`). Ground truth: **1 meaningful group** (shared `orders.table` key + shared service), **1 coincidental** (unrelated key), Secret asserted by reference only. Tests: K8s discovery finds key-level candidate despite different env names; Tier 1 on equivalent env dump finds 0; filtering drops generic; aggregation yields 1 group; report labels `configuration-confirmed` with no secret values.
7. **Explicit non-claims:** no read/write direction proven; no runtime/execution proof; no query→request mapping; DNS/Service refs may be stale; Secret values never read or displayed; same ConfigMap/Secret ≠ same data use (near-miss proves it); confidence capped at configuration-confirmed/statically-inferred, never runtime-observed. Every finding must state its evidence tier.
- **Supercedes:** Prior "implement Tier 2 next" directives in `STATE.md`/`HANDOFF.md` (implementation deferred to post-approval); narrows `AGENTS.md` Tier 2 scope (same-ConfigMap detection alone insufficient).

## D-040: Selective Source Analysis + Evidence Tiers
- **Date:** 2026-09-27
- **Decision:** Source-code analysis is **selective/optional strengthener**, never mandatory per finding and never the primary mission. All findings carry an evidence tier: **configuration-confirmed** (deterministic refs) vs **statically inferred** (likely use, unproven) vs **runtime-observed** (out of scope without tracing). No runtime claims from static evidence.
- **Context:** `AGENTS.md` ("AST/source-code analysis is no longer part of scope") contradicts the new direction's selective-source role; Tier 2 must not become query-level analysis.
- **Consequence:** Future prompts/reports must render the tier; judge cache keys must include tier-relevant evidence. No code changes in this update.
- **Supercedes:** D-012 (K8s replaces AST) in part — K8s stays primary, source returns only as optional corroboration.

## D-041: Validate-First Roadmap — Tier 1 Audit + Real-World Evaluation Before Extensions
- **Date:** 2026-09-27
- **Decision:** Prioritize Tier 1 verification and real-world validation (audit → multi-repo evaluation + ground truth → evidence-based fixes → consolidate/docs) before any Kubernetes or source-level work. K8s/source are deferred stretch directions behind a future concrete-capability decision gate, not conditions for Tier 1 completeness. Every change must improve detection quality, evidence, correctness, usability, or validation — no feature-count expansion.
- **Context:** Independent assessment found the architecture defensible and Tier 1 deep enough as a standalone project, with real-world effectiveness unproven (precision/recall, false positives/misses, filtering robustness, LLM reliability, usability). Prior docs framed Tier 2 as "proposal review next"; this reframes next work as validation.
- **Consequence:** `MISSION.md` focus, `AGENTS.md` Tier 2 + priorities, `PROJECT_PLAN.md` Phases 5–6 updated. `STATE.md`/`HANDOFF.md` next steps become audit + validation. No `src/` changes under this decision.
- **Supercedes (scheduling only):** D-039 "proposal review next" ordering; D-039 proposal content retained as reference for a future gate.

## D-042: Tier 1 Audit + Loose-End Closure (Workstream A Done)
- **Date:** 2026-09-28
- **Decision:** Close Workstream A with evidence-backed fixes only; no architectural change. Three fixes, all verified by new regression tests (`tests/test_audit.py`, 21 tests; suite 98 → 119 green, hermetic, no network):
  - **F1 — Windows drive-letter binds misparsed (false positive):** `normalize_volume("C:\data:/app")` split on `:` → named volume `C`, so two services with unrelated Windows binds produced a shared-volume candidate on resource `C`. Fixed in `parser.py` (`_WINDOWS_DRIVE_RE` strips the drive prefix before colon-splitting, re-attaches to source; `_is_bind_source` recognizes drive paths). Now `bind` with full source; discovery (named-only) yields no candidate. Interpolated drive paths (`${D}:/data` with `D=C:\x`) also covered.
  - **F2 — Judge prompt/schema wording mismatch:** pairwise + grouped prompts listed option 3 as bare `insufficient (evidence)` while `validate_judge_result` only accepts `meaningful|coincidental|uncertain` — a literal LLM would failsafe. Both prompts now read `uncertain (insufficient evidence)`.
  - **F4 — Test hermeticity:** `run_one_repo` intentionally loads the developer's real `.env`; under pytest (CWD = repo root) this leaked live keys across tests and let Case F make real network LLM calls (suite 20s with SDKs). Fixed via `conftest.py` autouse API-key env snapshot/restore + Case F key-block (`delenv` + stubbed `load_dotenv`) + explicit key-scrub in the no-key failsafe test. Suite now 0.35s, no network, order-independent.
- **Context:** Audit verified all 7 stages end-to-end (docs vs implementation vs tests + deterministic e2e on 3 fixtures and `tmp_calcom2` Cal.com-like: 3 svc → 6 obs → 1 group). Discovery-misses-different-var-names is the documented Tier 1 gap (D-039 differentiator), not a defect. Shared secret values reaching LLM prompts/cache is by-design Tier 1 behavior (shared secrets are coupling signals); artifacts are gitignored — noted as limitation, no change. `.venv` was broken (base Python 3.14 deleted) and rebuilt on Python 3.12.10; `python run.py --help` verified.
- **Observation (no code change):** with live keys, fixture groups judged `uncertain` where README shows `meaningful` — LLM judgment variance. Referred to Workstream B/C (multi-repo validation + consistency review), not fixed by code.
- **Consequence:** Workstream A closed; next is Workstream B multi-repo validation + ground truth (D-041). Tier 1 remains frozen except evidence-based fixes.

## D-043: Deepening Direction — AI Micro-Verifier, Grouped Prompts, Weighted Bands, Depth Cap at Table
- **Date:** 2026-09-28
- **Decision (directional, part of the build path — NOT a final spec):** After Tier 1 validation, deepen BlindSpot toward table-level findings with AI used strictly as a *verifier of small bounded tasks*, plus a dependency taxonomy and weighted (non-binary) judgments. Details remain revisitable; this entry locks direction only.
  - **AI as micro-verifier, never discoverer:** deterministic code proposes tiny evidence bundles (e.g. a snippet mentioning table `orders` next to `UPDATE`); the LLM answers one schema-locked micro-question (`{entity, access: read|write|none, confidence}` or same-entity check). No repo access, no free discovery, low temperature, cached per snippet+question. Deterministic hits skip the LLM entirely.
  - **One prompt per resource group (not per question, not per repo):** each prompt carries the discovery map (all groups, compact) + relevant compose slice + bounded per-service file tree + ID-tagged question block (`Q1`, `Q2`…); response must be a JSON array echoing IDs, validated per item with per-item failsafe. Rationale: shared memory within a decision unit (cross-checks, contradiction-spotting) without whole-repo blast radius or whole-cache invalidation.
  - **Weighted combiner, not true/false:** LLM outputs are *signals*; deterministic code combines them with explicit versioned weights (shared normalized identity strong +, same table both sides strong +, read/write direction medium +, ambiguous snippet weak + capped, generic names/values penalty −, unresolved placeholders uncertainty penalty). Score maps to bands (`strong / likely / possible / no-evidence`) with a visible breakdown in the report.
  - **Pointer chains:** every finding carries service → variable → value → store → table → snippet (file:line) → micro-verdict links, each link labeled machine-made vs AI-judged.
  - **Depth cap at L2 (table):** taxonomy is L0 shared infrastructure → L1 shared store → L2 shared table, each labeled visible or **hidden** (hidden = implicit, orthogonal to depth). L3 (access-pattern/row inference) and L4 (runtime same-row proof) are explicitly out of scope: the job is finding hidden dependencies, not mapping every connection.
  - **Defaults pending validation:** weights hand-set initially, calibrated against the ground-truth set later; prompt-unit and band thresholds tunable during Workstream B/C.
- **Context:** Audit (D-042) showed discovery is name-only (misses same-resource-different-names; can't distinguish declared vs used config) and the LLM judges paperwork, not reality. K8s remains deferred; this deepening is Compose-first and needs no new platform.
- **Consequence:** `AGENTS.md`/`STATE.md`/`HANDOFF.md` note the direction; no `src/` changes under this entry. Next proposal/plan will sequence: taxonomy lock → value-based discovery → bounded table extractor → micro-verifier + combiner → layered graph/report.
>>>>>>> 8d28c21 (Working tier 1)
