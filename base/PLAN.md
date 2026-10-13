# BASE PLAN — Finish-Fast Implementation (base branch only)

> LOCAL-ONLY, gitignored. Full-vision plan stays in `PROJECT_PLAN.md` (main track).

## Step 1 — Contextual judge (replaceable module, e.g. `src/blindspot/context_judge.py`)

- Input: one `GroupedEvidencePackage` (from `aggregation.py`) + bounded extras.
- Prompt unit per resource group:
  - discovery map (compact) + relevant compose slice + bounded file tree (fixed depth/count cap)
  - bounded source snippets only if cheaply identifiable (filename heuristics, fixed line cap)
  - fixed question set with stable IDs, e.g.:
    - `Q1_SHARED_USE` — do services plausibly use the same resource?
    - `Q2_COINCIDENCE` — generic/coincidental overlap signals?
    - `Q3_TABLE` — shared-table evidence (L2) if any, else `none` + uncertainty
    - `Q4_LIMIT` — what is missing / what would disprove coupling?
- Rules: no whole repo, no crawler, no re-asking what deterministic code already proved.

## Step 2 — Structured response + validation + cache

- Response: JSON array echoing IDs: `[{id, answer, evidence, confidence, uncertainty}]`.
- Validate per item with per-item failsafe (`uncertain`, confidence 0.0, reason `malformed`).
- Cache key = hash(grouping key + services + config evidence + unresolved vars + snippet hashes + prompt version).
  Any material change invalidates.
- Provider/model hidden from `DependencyModel` / `report.json` / `graph.json`
  (keep in `report.log.json` + `cache.json` only, as today).

## Step 3 — Deterministic scoring (`src/blindspot/scoring.py`, isolated)

- Inputs: validated structured signals only.
- Explicit weights, e.g. (tunable, documented here when locked):
  - shared normalized identity: strong +
  - same table both sides: strong +
  - read/write direction: medium +
  - ambiguous snippet: weak, capped
  - generic names/values: penalty −
  - unresolved placeholders: uncertainty penalty
- Output band: `strong / likely / possible / uncertain` + visible score breakdown.
- Never expose as probability. No ML.

## Step 4 — Wiring (minimal)

- `cli.py`: `packages → aggregate → context_judge → scoring → CouplingModel(+band/score) → graph → report`
- Keep `judge.py` (pairwise/grouped) intact for backward compat; new path opt-in then default once green.
- `graph.py` / `report.py`: add `classification` + `score_breakdown` + `uncertainty` fields, keep bipartite `Service ↔ Resource`, keep `potential coupling, not proven runtime` wording.

## Step 5 — Tests (new file `tests/test_base_scoring.py` + `tests/test_base_context.py`)

- Prompt construction: required context present, whole-repo absent, IDs stable
- Response validation: good / malformed / missing-ID cases
- Cache: hit on same evidence, miss on changed evidence
- Scoring: weights change → band change, uncertainty propagation, deterministic replay
- Table evidence: present / missing-source cases
- Report serialization: new fields round-trip, provider still hidden
- Full suite must stay green; do not weaken existing tests.

## Step 6 — Real-world validation (no rigorous precision/recall)

Per repo (Cal.com + 2–3 more via `python run.py`):
`exec ok? | findings | obvious FP | uncertain | notable miss | unsupported config`.
Manually review enough findings to show meaningful candidates. Document limits in `base/STATE.md`.

## Stop rule

DoD from `base/MISSION.md` met → stop. No K8s, no tracer, no frontend, no refactor.
