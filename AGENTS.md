# BlindSpot — Project Architecture

## Project Purpose

BlindSpot is a hidden dependency discovery tool for microservices.

It targets dependencies that may exist between services without direct service-to-service network communication.

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

Extract and normalize:

- services
- environment configuration
- volumes

The output should be a consistent internal representation that downstream stages can operate on.

---

## 2. Candidate Discovery

Find services that share resources or configuration and could therefore be coupled.

For the Tier 1 implementation, this includes:

- shared environment variables
- shared volumes

Candidate Discovery identifies possible relationships but does not decide whether they are real dependencies.

---

## 3. Candidate Filtering

Reduce obvious coincidences before expensive LLM calls and build evidence for candidates that remain.

A shared name does not automatically imply a dependency.

Example near-miss:

Two services both define:

`PORT`

This should not automatically be treated as a hidden dependency simply because the variable name is shared.

---

## 4. LLM Judge

For each meaningful candidate, ask an LLM whether the shared resource/configuration represents meaningful coupling or coincidence.

The LLM should judge pre-extracted candidates.

It should NOT be used to freely scan an entire codebase and guess hidden dependencies.

Keep the judgment input narrow and based on the evidence produced by the earlier stages.

Judgments should be run more than once during validation to check consistency, since LLM judgments are not perfectly repeatable.

---

## 5. Dependency Model

Store confirmed relationships as service-to-service dependencies.

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

- services
- hidden dependencies
- the shared resource/configuration responsible for the relationship

The resource or configuration should be shown as the reason for the dependency.

The graph is a primary demonstration artifact.

---

## 7. Report

Produce human-readable explanations of the discovered relationships.

A finding should explain that services are potentially coupled and identify the resource/configuration through which the coupling was detected.

The evidence and confidence associated with the finding should remain available to support the explanation.

---

# Scope

## Tier 1 — Required

Tier 1 is the complete core project.

It must include:

- Docker Compose / `.env` parsing
- shared environment-variable coupling detection
- shared-volume coupling detection
- candidate filtering
- LLM judgment
- dependency model
- graph output
- testing against synthetic repositories
- a deliberate near-miss test case
- validation against one small real-world open-source multi-service repository

If Tier 1 is complete, BlindSpot is a complete working and demoable project.

## Tier 2 — Stretch

Only implement Tier 2 after Tier 1 is working.

Tier 2 adds:

- AST-based source-code analysis
- shared database table-name detection
- a second real-world repository test

AST-based findings must enter the existing pipeline:

Candidate Discovery
→ Candidate Filtering
→ LLM Judge
→ Dependency Model
→ Graph
→ Report

Do not create a separate downstream architecture for AST findings.

---

# Current Technology

Use:

- Python 3.10+
- `pyyaml`
- `python-dotenv`
- `networkx`
- `matplotlib`

Python's built-in `ast` module may be used for Tier 2 source-code analysis.

Docker is optional for the tool itself. BlindSpot reads Docker Compose configuration as text and does not require running the services.

---

# Development Priorities

Build in this order:

1. Synthetic test repositories
2. Config parser
3. Candidate discovery
4. Candidate filtering
5. LLM judgment layer
6. Dependency model
7. Graph output
8. Real-world repository validation
9. Tier 2 AST analysis only if time allows

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

## Extensibility

Additional candidate sources, such as AST-based code analysis, should feed into the existing downstream pipeline rather than requiring a separate architecture.
