# MISSION.md

## Mission
Build **BlindSpot** — a tool that discovers **potential** implicit cross-service couplings that are **not** represented as direct service-to-service communication and would otherwise be overlooked. Shared resources are **signals and evidence, not automatic proof** of dependency. BlindSpot scans repositories and infrastructure to identify potential coupling — it is not a query-level analyzer, request tracer, or general observability platform, and it does not prove runtime behavior.

## Tier 1 (Frozen)
Tier 1 analyzes Docker Compose + related configuration (shared env vars, named volumes) via deterministic discovery → filtering + bounded resolution → aggregation → LLM judgment → dependency model → graph → report. It is complete and demoable. It stays frozen unless a concrete bug or validation issue requires a change. Tier 1 identifies **potential shared-resource coupling**; it cannot prove application-level read/write relationships or runtime behavior. Findings must be worded as potential coupling with evidence and confidence, never as proven runtime dependency.

## Tier 2 (Kubernetes-backed, proposal-first)
Kubernetes is central to the original vision — not a minor optional extension. Tier 2 must demonstrate a **concrete discovery capability Tier 1 cannot provide** (not just re-representing the same shared config in YAML) before any implementation. See `DECISIONS.md` D-039 for the current proposal status. Preferred inputs: Kubernetes manifests and/or **read-only** Kubernetes API data (workloads, namespaces, Services/endpoints, ConfigMap/Secret references — **never expose secret values** — PVCs/volumes). Runtime tracing, eBPF, and privileged agents are **not** Tier 2 requirements (future optional only).

## Source analysis (selective, optional)
Source-code evidence may **optionally strengthen or distinguish** a finding (e.g. two services access the same application-level state). It is never mandatory per finding and never the primary mission. No query-level mapping, full call graphs, per-request proof, or repo execution required.

## Evidence tiers & claims
Distinguish **configuration-confirmed** (deterministic refs) vs **statically inferred** (likely but unproven use) vs **runtime-observed** (out of scope unless tracing exists). Never claim runtime read/write from static evidence. Never invent direct service-to-service edges; graph stays `Service ↔ Resource`.

## Current Focus
**Validate Tier 1 first**: audit the implemented pipeline, run it against multiple real-world Compose repositories, build a manually reviewed evaluation set (precision/recall where defensible), and fix demonstrated weaknesses with regression tests. Tier 1 is treated as a potentially complete standalone product. Kubernetes and source-level analysis are **deferred stretch directions** — no application-code changes, dependencies, adapters, or redesigns for them until Tier 1 is demonstrably useful and a future extension passes a concrete-capability decision gate.

## Guiding principle
Every new feature must answer: does this give stronger evidence about a real hidden cross-service dependency, or enable discovery of a relationship Tier 1 cannot find? Prioritize demonstrable capability, evidence quality, and honest claims over feature count or presentation.

## Non-Goals
No unrestricted LLM codebase scanning; no query/request tracing; no runtime-behavior claims from static evidence; no secret-value exposure.
