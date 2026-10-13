# BASE MISSION — BlindSpot Finish Fast (base branch only)

> LOCAL-ONLY. This file lives in `base/` and is gitignored. It does NOT replace the full-vision docs (`MISSION.md`, `AGENTS.md`, `PROJECT_PLAN.md`, `DECISIONS.md` — frozen reference for `main` full-potential track).

## Objective

Smallest technically coherent extension of the D-042 Tier 1 system that demonstrates:

> BlindSpot discovers potential hidden cross-service coupling through shared resources and provides evidence explaining why the relationship may be meaningful.

## Starting point (do not rewrite)

D-042 Tier 1 audited baseline: 119 tests green, Stages 1–7 exist
(`parser.py`, `discovery.py`, `filtering.py`, `resolution.py`, `aggregation.py`,
`judge.py`, `model.py`, `graph.py`, `report.py`, `cli.py`).
Windows bind fix + prompt/schema fix + hermeticity fix done. E2E deterministic works.

## Finish-fast scope (3 improvements only)

1. **Better context to LLM** — judge a shared resource as a group with:
   resource + services + relevant Compose slice + resolved config +
   deterministic discoveries + bounded file tree + bounded source context if cheap +
   small fixed question set. No whole-repo send, no crawler, no rediscovery.
2. **Structured signals, not binary** — stable question IDs, machine-readable
   `{answer, evidence, confidence/strength, uncertainty}`, validated, failsafe on
   malformed output, cache keyed on material evidence/context, provider hidden.
3. **Deterministic scoring layer** — isolated component, explicit versioned
   weights/rules → bands `strong / likely / possible / uncertain`.
   LLM never sets final score directly. Score reproducible from evidence.
   No ML calibration, no perfect weights.

## Depth cap

L0 shared resource → L1 shared datastore → L2 shared table max.
No row/record lineage, no full SQL/ORM, no repo-wide AST framework.
Preserve uncertainty when table evidence is unreliable.

## Boundaries

`Evidence construction → LLM investigation → Structured judgment → Scoring → Dependency Model`
New judge + scoring replaceable. Do not spread LLM logic into parser/discovery/graph/report.
Do not rewrite working D-042 components for prettiness.

## Non-goals (BASE)

No Kubernetes, no runtime tracing, no row-level lineage, no full static-analysis
framework, no probabilistic calibration, no multi-agent LLM, no elaborate frontend,
no unrelated refactoring, no statistically rigorous precision/recall claims.

## Definition of done (BASE)

- Existing suite passes (no weakened tests)
- Contextual judge + structured evidence + deterministic scoring work
- Existing graph/model/report still work
- Several real Compose repos tested (Cal.com one of them), findings manually reviewed
- Limitations documented in `base/STATE.md`
- Repo runnable (`python run.py`) and presentable

## Branch rule

- `base` = this file. Finish fast, stop at DoD.
- `main` = full potential (K8s D-039, micro-verifier D-043, etc.).
- Never merge full-vision ideas into `base` to "improve" it.
