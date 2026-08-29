# BlindSpot — Project Architecture

## Project Purpose

BlindSpot is a tool for discovering implicit cross-service couplings in microservices.

It targets relationships that may exist between services without being represented as direct service-to-service network communication.

The initial implementation focuses on hidden coupling through shared environment variables and shared volumes/configuration in Docker Compose projects.

---

## Core Architecture

BlindSpot uses a seven-stage pipeline:

1. Parse + Normalize
2. Candidate Discovery
3. Candidate Filtering
4. LLM Judge
5. Dependency Model
6. Graph
7. Report

The pipeline intentionally separates deterministic discovery from LLM judgment and uses a **hybrid deterministic + LLM approach**:

- **Stage 3** performs deterministic filtering **plus bounded evidence construction/resolution**.
- **Stage 4** normally makes **one LLM judgment per surviving candidate**. Obvious/common coincidences cost **0 LLM calls**; interesting candidates cost **1 LLM call** each (cached reuse for unchanged candidate/evidence).

```text
                    Compose / .env
                         │
                         ▼
                1. Parse + Normalize
                         │
                         ▼
                2. Candidate Discovery
                         │
                         ▼
                3. Candidate Filtering
                         │
              ┌──────────┴──────────┐
              │                     │
        obvious noise        surviving candidate
              │                     │
           discard                  ▼
                         Build bounded evidence
                                  package
                                    │
                                    ▼
                           4. LLM Judge
                                    │
                             cache lookup
                                    │
                     ┌──────────────┴──────────────┐
                     │                             │
                  cache hit                    cache miss
                     │                             │
                     ▼                             ▼
                 use verdict                     LLM → cache it
                     └──────────────┬──────────────┘
                                    ▼
                         5. Dependency Model
                                    │
                         verdict + confidence
                                    │
                                    ▼
                           6. Resource Graph
                                    │
                                    ▼
                              7. Report
```

Static analysis discovers possible candidates. The LLM evaluates those pre-extracted candidates rather than reading an entire codebase and freely guessing dependencies.

---

## 1. Parse + Normalize

Input:

- `docker-compose.yml`
- `.env`
- supported `env_file` sources

Extract and normalize:

- services
- environment configuration
- volumes
- supported `${VAR_NAME}` / `${VAR_NAME:-default}` interpolation
- image information (needed for evidence resolution)

The parser should preserve unresolved references rather than silently inventing values.

The normalized representation must preserve enough information to **trace references** for Stage 3 evidence resolution:

```text
DB_HOST=${DB_HOST} → .env DB_HOST=postgres → Compose service "postgres" (postgres:16)
```

It should retain interpolation source, env-file origin, and resolution chain where applicable. Unresolved values must remain explicitly unresolved.

The output should be a consistent internal representation that downstream stages can operate on.

---

## 2. Candidate Discovery

Find services that share resources or configuration and could therefore be coupled.

For the Tier 1 implementation, this includes:

- shared environment configuration
- shared named volumes

Candidate Discovery identifies possible relationships but does **not** decide whether they are real dependencies.

It should remain **broad and deterministic**. Its job is to find possible shared resources/configuration. For example, `PORT=8000` in two services should still produce a candidate `resource=PORT` — Stage 3 then identifies it as generic/low-signal and avoids an LLM call.

---

## 3. Candidate Filtering — Deterministic Filtering + Bounded Evidence Construction

This stage has two responsibilities: **filter** and **build evidence**.

### 3a. Deterministic filtering

Reduce obvious coincidences before expensive LLM calls.

Use ordinary deterministic code/rules to eliminate or deprioritize obvious/common configuration coincidences. Examples include:

- standard ports such as `80`, `443`, `8080`, `3000`
- common debug flags such as `DEBUG=1`
- standard logging-level configuration
- other clearly generic configuration patterns discovered during implementation (e.g. `PORT`, `HOST`, `TZ`, `LANG`)

These are **filtering heuristics**, not absolute proofs. The filter should reduce obvious noise rather than claim that a pattern can never represent coupling.

Useful conceptual classification:

```text
OBVIOUS_NO → no LLM call
LOW_SIGNAL → no LLM call (deprioritized)
NEEDS_JUDGMENT → LLM call
HIGH_SIGNAL → LLM call
```

The implementation may simplify these categories, but behavior must remain:

```text
obvious/common coincidence → no LLM call
interesting candidate       → LLM call
```

A shared name does not automatically imply a dependency.

Example near-miss:

Two services both define:

`PORT`

This should not automatically be treated as a dependency simply because the variable name is shared.

### 3b. Bounded evidence construction and resolution

For each **surviving candidate**, Stage 3 must build **one compact, bounded evidence package** that the LLM will judge. Do **not** create multiple LLM prompts per evidence item (e.g. separate calls to resolve a variable, interpret a name, check a Compose service). These are static/deterministic tasks.

Evidence resolution before the LLM: the LLM must not be expected to understand infrastructure merely from names. `DB_HOST=postgres` alone is weak. BlindSpot should deterministically resolve what the value points to when possible:

```yaml
services:
  orders: { environment: { DB_HOST: postgres } }
  reports: { environment: { DB_HOST: postgres } }
  postgres: { image: postgres:16 }
```

→ `DB_HOST=postgres` resolves to Compose service `postgres` with image `postgres:16`. This is machine-derived evidence; the LLM then interprets the architectural meaning.

#### Bounded evidence package contents

**Required:**
- Service A, Service B
- shared resource/configuration
- resource type
- value(s), where applicable

**Deterministically resolved context, when applicable:**
- whether a value resolves to another Compose service
- referenced service name
- relevant image information
- whether a resource is internal or external
- named-volume identity
- interpolation source / env-file origin

**Small relevant surrounding configuration** — only directly relevant to the candidate (e.g. for a DB candidate, `DB_HOST`/`DB_NAME`/`DB_PORT`). Do not send unrelated `PORT`/`DEBUG`/`LOG_LEVEL`/`TZ`/`SECRET_KEY`.

**Filtering signals:**
- `generic_variable: false`
- `same_value: true`
- `resolved_reference: compose_service` (or external/unknown)

Principle: **Give the LLM the smallest set of machine-verified facts needed to make the semantic judgment.**

Normal pattern:

```text
Candidate → Deterministic context/evidence resolution → One bounded evidence package → One LLM call → Structured verdict
```

---

## 4. LLM Judge — Semantic Judgment (One Call Per Surviving Candidate)

For each meaningful candidate, ask an LLM whether the shared resource/configuration represents meaningful coupling or coincidence.

The LLM should judge pre-extracted candidates with their **bounded evidence package**.

It should NOT be used to freely scan an entire codebase and guess hidden dependencies.

It must not inspect the whole repository or freely discover dependencies.

Keep the judgment input narrow and based on the evidence produced by Stage 3.

**Do not use multiple LLM prompts per evidence item.** Do not create separate calls for resolving a variable, interpreting a name, checking a Compose service, or checking related configuration.

**Normal cost:** `0 LLM calls for obvious noise + 1 LLM call for each interesting candidate.` Do not build a multi-step/multi-agent evidence ladder in the first implementation. An `uncertain` verdict is acceptable.

Judgments should be run more than once during validation to check consistency.

Store LLM verdicts in a local `cache.json` file so repeated analysis can reuse previous judgments.

The cache key should represent the candidate and relevant evidence, not merely a variable name/value pair, because the same configuration value can have different meanings in different service contexts. If the evidence changes materially, the cache key should change.

Store at least `verdict`, `confidence`, `reason`, and model/version information where practical:

```text
Candidate + Evidence → deterministic cache key → cache.json → hit? reuse : LLM → store
```

### Structured output

The LLM should return structured output (with schema validation where practical):

```json
{
  "verdict": "meaningful | coincidental | uncertain",
  "confidence": 0.0,
  "reason": "short explanation"
}
```

**Confidence is mandatory.** It must be stored in the Dependency Model and exposed in the final report/metadata.

Prompt should conceptually present:

```text
SERVICE A/B, SHARED CONFIGURATION, VALUES, RESOLUTION (value → service + image),
RELATED CONFIGURATION (bounded), DETERMINISTIC FILTERING signals
→ Determine: meaningful coupling / coincidental overlap / insufficient evidence
→ Return: verdict, confidence, reason
```

---

## 5. Dependency Model

Store confirmed relationships as service-to-resource relationships that explain the implicit cross-service coupling. Do not automatically represent a shared resource as a direct service-to-service edge.

Each dependency should preserve at least:

- `service_a`
- `service_b`
- `resource`
- `resource_type`
- `evidence` (bounded package including resolution context)
- `verdict` (`meaningful` | `coincidental` | `uncertain`)
- `confidence` (first-class, 0.0–1.0, mandatory)
- `reason`

Data flow:

```text
LLM (verdict, confidence, reason) → Dependency Model → Graph / Report
```

The dependency model must preserve why BlindSpot believes two services are connected **and how confident it is**, not only the fact that they are connected. Do not collapse a finding into only `orders → reports`.

---

## 6. Graph — Resource-Based

Use:

- `networkx`
- `matplotlib`

The graph should visualize:

- service nodes
- resource/configuration nodes
- the implicit coupling between them
- the shared resource/configuration responsible for the relationship

**Do not convert a shared resource directly into a service-to-service edge:**

```text
Bad:  orders ───────── reports   // falsely implies direct call
```

Use resource nodes:

```text
orders ───────┐
              ▼
        DB_HOST=postgres
              ▲
              │
reports ──────┘

orders ───────┐
              ▼
         shared-data
              ▲
              │
reports ──────┘
```

This avoids falsely implying that `orders` calls `reports`. The resource node explicitly shows the mechanism through which the services are connected. The graph represents `Service ↔ Resource` rather than automatically asserting `Service ↔ Service`.

Use distinct visual treatment for service nodes and resource nodes.

The graph is a primary demonstration artifact.

---

## 7. Report

Produce human-readable explanations of the discovered relationships.

A finding should explain that services are potentially coupled and identify the resource/configuration through which the coupling was detected.

The report should include the relevant evidence (including resolution context and related configuration), dependency type, LLM judgment (`verdict`/`reason`), and **confidence** so the finding is explainable rather than a bare graph edge. Confidence must not be discarded after the LLM call and must be available in the final report.

---

# Scope

## Tier 1 — Required

Tier 1 is the complete core project.

It must include:

- Docker Compose / `.env` parsing with traceable references
- supported `env_file` imports
- supported `${VAR_NAME}` interpolation (preserve unresolved)
- shared environment-configuration candidate discovery (broad)
- shared-volume candidate discovery
- deterministic candidate filtering (heuristics for obvious noise)
- bounded evidence construction + deterministic resolution (service/image/interpolation/related config)
- LLM judgment — 1 call per surviving candidate, structured `verdict/confidence/reason`, `uncertain` allowed
- local LLM verdict caching with candidate+evidence-aware keys
- dependency model with evidence, verdict, confidence, and reason
- resource-based graph (Service ↔ Resource, not Service ↔ Service)
- report exposing evidence and confidence
- testing against deliberately messy synthetic repositories
- deliberate near-miss test cases
- validation against one small real-world open-source multi-service repository

If Tier 1 is complete, BlindSpot is a complete working and demoable project.

## Tier 2 — Stretch

Only implement Tier 2 after Tier 1 is working.

Tier 2 adds Kubernetes manifest support.

Initial scope:

- Kubernetes YAML parsing
- workload normalization
- shared ConfigMap detection
- shared Secret detection
- relevant shared-volume detection

Kubernetes findings must enter the existing pipeline:

Candidate Discovery
→ Candidate Filtering (with bounded evidence + resolution)
→ LLM Judge (1 call per candidate, cached)
→ Dependency Model (with confidence)
→ Graph (resource-based)
→ Report

Do not create a separate downstream architecture for Kubernetes findings.

AST/source-code analysis is no longer part of the project scope.

---

# Current Technology

Use:

- Python 3.10+
- `pyyaml`
- `python-dotenv`
- `networkx`
- `matplotlib`

No AST dependency is required. Tier 2 uses the same YAML/configuration parsing approach for Kubernetes manifests.

Docker is optional for the tool itself. BlindSpot reads Docker Compose configuration as text and does not require running the services.

---

# Development Priorities

Build in this order:

1. Deliberately messy synthetic test repositories
2. Config parser with reference-tracing support
3. Candidate discovery (broad, deterministic)
4. Candidate filtering (deterministic heuristics, separate from discovery)
5. Bounded evidence construction + deterministic resolution (what shared values point to)
6. LLM judgment layer — one call per surviving candidate + verdict cache (`cache.json`)
7. Dependency model with verdict/confidence/reason
8. Resource-based graph output (Service ↔ Resource)
9. Report generation (evidence + confidence)
10. Real-world repository validation
11. Tier 2 Kubernetes support only if time allows

Do not allow Tier 2 work to block completion of Tier 1.

---

# Important Architectural Principles

## Discovery ≠ Judgment

Deterministic/static analysis discovers candidates.

The LLM judges candidates.

Do not make the LLM responsible for unrestricted dependency discovery.

## Evidence Matters

A dependency finding must retain the evidence that led to the judgment.

## Shared Names Are Not Automatically Dependencies

Identical environment-variable names, paths, or other configuration values can be coincidental.

BlindSpot must distinguish possible coupling from obvious coincidences rather than treating every shared identifier as a dependency.

## Filtering Before LLM

LLM calls are reserved for candidates that survive deterministic filtering.

The filter should remove or deprioritize obvious/common configuration matches so that the LLM is used for semantic ambiguity rather than trivial cases.

## Evidence Resolution Before LLM

Do not expect the LLM to understand infrastructure from names alone. Deterministically resolve what values point to (Compose service, image, internal/external, interpolation source) before the LLM call. The LLM interprets the architectural meaning of machine-verified facts.

## One LLM Call Per Surviving Candidate

Do not create multiple LLM prompts per evidence item (variable resolution, name interpretation, service existence). Normal cost is 0 calls for obvious noise + 1 call per interesting candidate. An `uncertain` verdict is acceptable — do not build a multi-agent ladder.

## Verdict Caching

LLM judgments should be cached locally in `cache.json`.

A cached verdict is valid only when the candidate and its relevant evidence match the cached judgment (service A/B, resource, resource type, values, resolved context). The cache exists to make repeated analysis stable and reduce unnecessary API calls. The same value can have different meanings in different service contexts.

## Confidence Is First-Class

Confidence is mandatory. The LLM must return it, the Dependency Model must store it, and the Graph/Report must expose it.

## Resource-Based Graph

Represent coupling as `Service ↔ Resource`, not `Service ↔ Service`. Use distinct visual treatment for service and resource nodes. Do not imply a direct call between services.

## Bounded Evidence Package

Give the LLM the smallest set of machine-verified facts needed to judge — required fields + resolved context + small relevant surrounding configuration + filtering signals. Do not send unrelated configuration.

## Extensibility

Additional candidate sources, such as Kubernetes manifest analysis, should feed into the existing downstream pipeline rather than requiring a separate architecture.

---

## Final Architectural Principle

```text
Static analysis
    → What are the facts?

Deterministic filtering
    → Is this obviously generic/noisy?

Evidence resolution
    → What does this configuration actually point to?

LLM
    → Given these facts, does this represent meaningful coupling?

Dependency Model
    → What did we conclude, with what confidence and why?

Graph
    → How are services connected through shared resources?

Report
    → What does the finding mean to a human?
```

The LLM provides **semantic interpretation**, not raw discovery. The code provides **facts, filtering, and context**.
