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

The pipeline intentionally separates deterministic discovery from LLM judgment.

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
- supported `${VAR_NAME}` interpolation

The parser should preserve unresolved references rather than silently inventing values.

The output should be a consistent internal representation that downstream stages can operate on.

---

## 2. Candidate Discovery

Find services that share resources or configuration and could therefore be coupled.

For the Tier 1 implementation, this includes:

- shared environment configuration
- shared named volumes

Candidate Discovery identifies possible relationships but does not decide whether they are real dependencies.

---

## 3. Candidate Filtering

Reduce obvious coincidences before expensive LLM calls and build evidence for candidates that remain.

This stage uses deterministic heuristics. Common generic configuration patterns such as standard ports, common debug flags, and standard logging settings can be filtered or deprioritized.

The filtering should be conservative: it reduces obvious noise but should not claim that a pattern can never represent coupling.

A shared name does not automatically imply a dependency.

Example near-miss:

Two services both define:

`PORT`

This should not automatically be treated as a dependency simply because the variable name is shared.

---

## 4. LLM Judge

For each meaningful candidate, ask an LLM whether the shared resource/configuration represents meaningful coupling or coincidence.

The LLM should judge pre-extracted candidates.

It should NOT be used to freely scan an entire codebase and guess hidden dependencies.

Keep the judgment input narrow and based on the evidence produced by the earlier stages.

Judgments should be run more than once during validation to check consistency.

Store LLM verdicts in a local `cache.json` file so repeated analysis can reuse previous judgments.

The cache key should represent the candidate and relevant evidence, not merely a variable name/value pair, because the same configuration value can have different meanings in different service contexts.

---

## 5. Dependency Model

Store confirmed relationships as service-to-resource relationships that explain the implicit cross-service coupling. Do not automatically represent a shared resource as a direct service-to-service edge.

Each dependency should preserve at least:

- `service_a`
- `service_b`
- `resource`
- `resource_type`
- `evidence`
- `judge_result`
- `confidence`

The dependency model must preserve why BlindSpot believes two services are connected, not only the fact that they are connected.

---

## 6. Graph

Use:

- `networkx`
- `matplotlib`

The graph should visualize:

- service nodes
- resource/configuration nodes
- the implicit coupling between them
- the shared resource/configuration responsible for the relationship

For example:

```text
orders ───────┐
              ▼
        DB_HOST=postgres
              ▲
              │
reports ──────┘
```

This avoids falsely implying that `orders` calls `reports`. The resource node explicitly shows the mechanism through which the services are connected.

Use distinct visual treatment for service nodes and resource nodes.

The graph is a primary demonstration artifact.

---

## 7. Report

Produce human-readable explanations of the discovered relationships.

A finding should explain that services are potentially coupled and identify the resource/configuration through which the coupling was detected.

The report should include the relevant evidence, dependency type, LLM judgment, and confidence so the finding is explainable rather than a bare graph edge.

---

# Scope

## Tier 1 — Required

Tier 1 is the complete core project.

It must include:

- Docker Compose / `.env` parsing
- supported `env_file` imports
- supported `${VAR_NAME}` interpolation
- shared environment-configuration candidate discovery
- shared-volume candidate discovery
- deterministic candidate filtering
- LLM judgment
- local LLM verdict caching
- dependency model with evidence and confidence
- resource-based graph output
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
→ Candidate Filtering
→ LLM Judge
→ Dependency Model
→ Graph
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
2. Config parser
3. Candidate discovery
4. Candidate filtering and evidence construction
5. LLM judgment layer + verdict cache
6. Dependency model
7. Resource-based graph output
8. Report generation
9. Real-world repository validation
10. Tier 2 Kubernetes support only if time allows

Do not allow Tier 2 AST work to block completion of Tier 1.

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

## Verdict Caching

LLM judgments should be cached locally.

A cached verdict is valid only when the candidate and its relevant evidence match the cached judgment. The cache exists to make repeated analysis stable and reduce unnecessary API calls.

## Extensibility

Additional candidate sources, such as Kubernetes manifest analysis, should feed into the existing downstream pipeline rather than requiring a separate architecture.
