# DECISIONS.md — Architecture Decisions

> Why BlindSpot looks the way it does. Append-only log — never delete, only supercede with new entry.

**Last Updated:** 2026-08-27

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
