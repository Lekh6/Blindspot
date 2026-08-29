# MISSION.md

## Mission
Build **BlindSpot** — a tool that finds implicit cross-service couplings in Docker Compose projects that are invisible to network-traffic analysis, by combining deterministic static analysis with narrow LLM judgment and visualizing the result as a resource-based graph.

## Why This Matters To You
You are building Tier 1 end-to-end on 1–2 hrs/day: deliberately messy synthetic repos → parser (`env_file`, `${VAR}`) → candidate discovery → heuristic filtering → LLM judge (`cache.json`) → dependency model → graph → report → real-world validation. Tier 2 (Kubernetes) is stretch only.

## Current Focus
Understand **Stage 3 Candidate Filtering** (the heuristic stage immediately BEFORE LLM Judge) and how Stage 4 Judge consumes its output — the `Discovery ≠ Judgment` boundary that makes the pipeline cheap, deterministic, and explainable.

## Success Criteria
Can explain why every shared name is NOT a dependency (e.g. `PORT`), what filtering drops/keeps/enriches, and why the Judge sees only filtered candidates with `candidate+evidence` cache keys.

## Non-Goals
No unrestricted LLM codebase scanning; no AST work until Tier 1 is demoable.
