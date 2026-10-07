# Hidden Dependency Discovery — Final Project Plan

## Status
Committed. Built around realistic pace: **1-2 hrs/day** Structured so a bad week doesn't sink the whole thing — there's a guaranteed working core, and everything past that is a bonus, not a requirement.

Refined to the **hybrid deterministic + LLM** architecture: Stage 3 does deterministic filtering **plus bounded evidence construction/resolution**, Stage 4 makes **one LLM call per surviving candidate** (0 for obvious noise, cached reuse for unchanged evidence). Confidence is first-class.

---

## 1. The Project — BlindSpot

**BlindSpot** is a tool for discovering implicit cross-service couplings in microservice systems.

## 1. The Project, In Plain Terms

Modern software is usually split into multiple small services that work together — one handles logins, another payments, another emails. These are described in a `docker-compose.yml` file, which lists each service, what it reads from its environment, and what files/folders it shares.

**The problem:** two services can depend on each other without ever directly calling each other. Example: Service A and Service C both silently assume there's a database table called `orders`. Nobody wrote that connection down. If someone renames that table while only thinking about Service A, Service C breaks with zero warning. That's a **hidden dependency**.

**What this tool does:**
1. **Parse + Normalize** — scans `docker-compose.yml` / `.env` files and converts services, environment configuration, volumes, and image information into a consistent internal representation that preserves traceable references (`DB_HOST=${DB_HOST}` → `.env` → Compose service + image).
2. **Candidate Discovery** — finds services that share resources or configuration and could therefore be coupled (broad, deterministic — does not decide).
3. **Candidate Filtering** — deterministically filters obvious coincidences (`PORT`, `DEBUG`, `LOG_LEVEL`) and builds **one bounded evidence package per surviving candidate** with resolved context (does value point to a Compose service? which image? internal/external? interpolation/env-file origin + small relevant surrounding config).
4. **LLM Judge** — for each surviving candidate, one LLM call judges the bounded evidence package → structured `verdict: meaningful|coincidental|uncertain` + `confidence` + `reason` (cached in `cache.json` with candidate+evidence-aware key).
5. **Dependency Model** — stores confirmed relationships as service-to-resource relationships with evidence, verdict, confidence, and reason.
6. **Graph + Report** — visualizes the hidden dependency network as `Service ↔ Resource` (not `Service ↔ Service`) and explains why each relationship was identified, with confidence exposed.
7. **(Stretch)** Kubernetes — parses manifests for shared ConfigMaps/Secrets/volumes and feeds candidates through the same Filtering → Judge → Model → Graph → Report pipeline.

---

## 2. The Angle (No Competitive Framing Needed)

Standard dependency-mapping tools (Dynatrace, Datadog, distributed tracing) find dependencies by watching network traffic between services — one service calling another's API. That mechanism can only ever see dependencies that involve something being sent over a connection.

The couplings this project targets — shared env vars, shared table-naming conventions, shared filesystem paths — never involve network traffic. Two services can be silently coupled through config or convention while never once talking to each other directly, and that kind of coupling is invisible to anything watching the wire.

That's the honest angle: not "beats existing tools," just "looks at a part of the problem those tools structurally can't see." That's enough of a differentiator for a resume project — it doesn't need to hold up as a startup pitch.


---

## 3. System Requirements

**No VM needed.** Lightweight on hardware — the difficulty is conceptual (evidence resolution is the new learning curve), not computational.

| Need | What to install | Why |
|---|---|---|
| Language | Python 3.10+ | Easiest ecosystem for YAML/config parsing |
| Editor | VS Code | Standard, good Python support |
| Version control | Git | To clone a real repo later |
| Python packages | `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` | Config parsing, graph drawing |
| LLM access | API key (Claude or OpenAI) | Judgment step — 0 calls for obvious noise + 1 per interesting candidate, small budget |
| Docker (optional) | Docker Desktop | Only if you want to actually run services for a live demo — not needed for the tool to work, since it only reads config files as text |

**Hardware:** any normal laptop, 8GB RAM is fine. No GPU — this calls an API, doesn't run a model locally.

---

## 4. System Architecture

**Canonical pipeline:** Parse + Normalize → Candidate Discovery → Candidate Filtering (with bounded evidence + resolution) → LLM Judge (1 call per candidate, cached) → Dependency Model (with confidence) → Resource Graph → Report.

The hybrid is key: **deterministic filtering + bounded evidence construction** first, then **one LLM judgment per surviving candidate**. The LLM provides semantic interpretation, not raw discovery. Confidence is mandatory and preserved end-to-end.

Candidate Filtering uses deterministic heuristics before LLM calls; LLM verdicts are cached locally in `cache.json`. The cache key must include the candidate and relevant evidence (service A/B, resource, resource type, values, resolved context), not only a variable/value pair. Same value can mean different things in different service contexts.

The graph uses explicit resource nodes (for example `DB_HOST=postgres` or `shared-data`) rather than direct service-to-service edges, so the graph represents the coupling mechanism without implying that one service calls another.

Tier 2 replaces AST/source-code analysis with Kubernetes manifest support for shared ConfigMaps, Secrets, and relevant shared volumes, reusing the same downstream pipeline.

BlindSpot uses a seven-stage pipeline:

```text
                 ┌──────────────────────┐
                 │ docker-compose.yml   │
                 │ .env                 │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 1. Parse + Normalize │
                 │                      │
                 │ Services             │
                 │ Environment + Images │
                 │ Volumes + References │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 2. Candidate        │
                 │    Discovery        │
                 │                      │
                 │ Find services that  │
                 │ share resources or  │
                 │ configuration       │
                 │ (broad, determ.)     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 3. Candidate        │
                 │    Filtering        │
                 │                      │
                 │ ┌─ deterministic    │
                 │ │  filter           │
                 │ │  OBVIOUS_NO/      │
                 │ │  LOW_SIGNAL →     │
                 │ │  no LLM call      │
                 │ │  NEEDS_JUDGMENT/  │
                 │ │  HIGH_SIGNAL →    │
                 │ │  LLM call         │
                 │ └────────────────── │
                 │ Build bounded       │
                 │ evidence package    │
                 │ (resolve service/   │
                 │  image, filtering   │
                 │  signals, related   │
                 │  config)            │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 4. LLM Judge        │
                 │                      │
                 │ One bounded package │
                 │ → one LLM call      │
                 │ cache lookup        │
                 │ verdict|confidence  │
                 │ |reason|uncertain   │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 5. Dependency Model │
                 │                      │
                 │ Service ↔ Resource  │
                 │ + evidence          │
                 │ + verdict           │
                 │ + confidence        │
                 │ + reason            │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 6. Resource Graph   │
                 │                      │
                 │ Services + resource │
                 │ nodes (Service ↔    │
                 │ Resource, not       │
                 │ Service ↔ Service)  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 7. Report           │
                 │                      │
                 │ "These services are │
                 │ potentially coupled │
                 │ through X —         │
                 │ confidence 0.93."    │
                 └──────────────────────┘
```

### Stage responsibilities

- **Parse + Normalize:** turn raw Compose/.env input into structured data with traceable references (interpolation source, env-file origin, image) so Stage 3 can resolve what values point to.
- **Candidate Discovery:** find possible hidden relationships without deciding whether they are real dependencies. Broad, deterministic — e.g. `PORT` still produces a candidate.
- **Candidate Filtering:** two jobs — (1) deterministically filter obvious noise (standard ports, debug flags, generic keys) and (2) build one bounded evidence package per survivor: required fields (A/B, resource, type, values) + deterministically resolved context (does value resolve to Compose service? image? internal/external? interpolation/env-file origin) + small relevant surrounding config (e.g. `DB_HOST`/`DB_NAME`/`DB_PORT` for DB candidate) + filtering signals (`generic_variable`, `same_value`, `resolved_reference`). Do not send unrelated `PORT`/`DEBUG`/`LOG_LEVEL` to the LLM.
- **LLM Judge:** determine whether a candidate represents meaningful coupling given its bounded evidence. One call per surviving candidate, structured `verdict: meaningful|coincidental|uncertain` + `confidence` + `reason`. Narrow classification prompt, no multi-agent ladder, no whole-repo scan. Cached.
- **Dependency Model:** preserve the discovered relationship and the reasoning behind it with mandatory confidence.
- **Graph:** show services and their hidden dependencies as `Service ↔ Resource`, with distinct visual treatment for service vs resource nodes.
- **Report:** turn findings into human-readable explanations with evidence, verdict, reason, and confidence.

The pipeline intentionally separates **discovery** from **judgment**. Static analysis is deterministic and produces candidates; the LLM only evaluates those pre-extracted candidates rather than reading an entire codebase and guessing freely.

The dependency model should preserve at least:

```text
Dependency
├── service_a
├── service_b
├── resource
├── resource_type
├── evidence          // bounded package + resolved context
├── verdict           // meaningful | coincidental | uncertain
├── confidence        // 0.0–1.0 mandatory
└── reason
```

This lets the final output explain not only that two services are connected, but **why** BlindSpot believes they are connected and **how confident** it is.

**Tier 2 extension:** Kubernetes manifest analysis becomes an additional candidate source. Its candidates enter the existing Candidate Filtering → LLM Judge → Dependency Model → Graph → Report pipeline rather than requiring a separate architecture.

## 5. Scope Tiers — This Is the Key Structural Change

**Tier 1 — Must-Have (this is "the project," full stop):**
- Config parser with traceable references (env var + image + env_file origin) from `docker-compose.yml` / `.env`
- Shared env var + shared volume candidate discovery (broad, deterministic)
- Deterministic candidate filtering (heuristics for obvious noise) + bounded evidence construction with deterministic resolution (service/image/interpolation/related config)
- LLM judgment layer — 1 call per surviving candidate, structured `verdict/confidence/reason`, `uncertain` allowed, `cache.json` with candidate+evidence-aware keys
- Dependency model with evidence, verdict, confidence, and reason (service-to-resource)
- Resource-based graph (`Service ↔ Resource`, not `Service ↔ Service`)
- Report exposing evidence and confidence
- Tested against your own synthetic repos (including a deliberate near-miss)
- Real-world multi-service repo validation

If you finish only this, you have a complete, working, demoable tool. That's the deliverable you can promise yourself in week 1.

**Tier 2 — Kubernetes / source analysis (deferred stretch, decision-gated — NOT current work):**
- Only after Tier 1 is validated (audit + multi-repo evaluation + demonstrated fixes). A future extension must demonstrate a concrete capability Tier 1 cannot provide (e.g. same ConfigMap/Secret key under different env-var names across namespaces, via Service DNS → Endpoints and PVCs) — mere YAML parsing / "same database" is not sufficient
- Same downstream pipeline where technically appropriate (YAML parsing via `pyyaml`; read-only API preferred; Secret names/keys only, never values); do not force reuse where semantics differ
- Requires its own design + validation plan; not a condition for declaring Tier 1 complete

**Why this order, not config+code together from day one:** Evidence resolution is now the one genuinely new, bounded skill here. If it eats more time than expected, you don't want it blocking the rest of the pipeline. Tier 1 has zero dependency on Kubernetes, so it's safe from that risk entirely.

---

## 6. Pace Reality Check (1-2 hrs/day + LeetCode)

Rough math: 1-2 hrs/day, realistically not every single day, lands somewhere around 25-40 hours across a month. That's enough for Tier 1 comfortably, with real room to spare for LeetCode. Tier 2 depends entirely on how Tier 1 goes and how much evidence-resolution work is needed — treat it as a bonus, not a plan.

**Rule for the month:** if you're on schedule and enjoying it, add Tier 2. If a week gets eaten by LeetCode prep or the evidence work is dragging, drop Tier 2 without guilt — Tier 1 alone is a complete, honest, demoable project.

---

## 7. Build Order

### Phase 1 — Setup + ground truth (a few short sessions)
- Install everything (Python, Git, VS Code, API key, virtual env, packages)
- Build 3 deliberately messy synthetic Docker Compose repos by hand:
  - One shared env/config coupling
  - One shared volume coupling
  - One deliberate near-miss (both services define generic `PORT`)
  - Include controlled comments, `${VAR_NAME}` interpolation, `image: postgres:16` for resolution, and external `env_file` usage
- These are your test fixtures for everything that follows.

### Phase 2 — Config parser (Tier 1 core)
- Parse `docker-compose.yml` + `.env` + supported `env_file` imports, extract env vars, volumes, and image per service with traceable references
- Handle supported `${VAR_NAME}` interpolation and preserve unresolved references
- Preserve evidence needed for Stage 3: interpolation source, env-file origin, resolution chain (`DB_HOST=${DB_HOST}` → `.env` → Compose service + image)
- Validated: messy fixtures parse deterministically

### Phase 2b — Candidate discovery (Tier 1 core)
- Broad deterministic pairwise comparison: shared env keys + shared named volumes (ignore bind/anonymous)
- Remains broad — `PORT=8000` still produces candidate; filtering decides

### Phase 2c — Candidate filtering + bounded evidence construction (Tier 1 core, refined)
- Deterministic heuristics: standard ports (`80`/`443`/`8080`/`3000`), `DEBUG=1`, logging levels, other generic keys — reduce obvious noise (conceptually `OBVIOUS_NO`/`LOW_SIGNAL` → no LLM, `NEEDS_JUDGMENT`/`HIGH_SIGNAL` → LLM; implementation may simplify but behavior equivalent)
- **Evidence resolution before LLM:** deterministically resolve what shared values point to — does `DB_HOST=postgres` resolve to Compose service `postgres`? image `postgres:16`? internal vs external? Do not ask LLM to guess infrastructure from names.
- Build **one bounded evidence package per survivor**: required (A/B, resource, type, values) + resolved context (service/image/internal/external, volume identity, interpolation/env-file origin) + small relevant surrounding config (e.g. `DB_HOST`/`DB_NAME`/`DB_PORT`) + filtering signals (`generic_variable`, `same_value`, `resolved_reference`). Do not send unrelated `PORT`/`DEBUG`/`TZ`/`SECRET_KEY`.
- Do not create multiple LLM prompts per evidence item

### Phase 3 — LLM judgment layer (Tier 1 core)
- For each surviving candidate, one LLM call with its bounded evidence → structured `verdict: meaningful|coincidental|uncertain` + `confidence: 0.0-1.0` + `reason` (schema validation where practical)
- Keep prompt narrow — it only judges a pre-extracted candidate + evidence, it never reads a whole codebase and guesses freely
- Cache verdicts in `cache.json` with deterministic key over candidate + evidence (service A/B, resource, type, values, resolved context); same value can mean different things. Store `verdict`, `confidence`, `reason`, model/version. Reuse on re-run.
- Run each judgment more than once and sanity-check consistency — LLMs aren't perfectly repeatable judges, worth knowing before you trust the output
- Cost: `0 LLM calls for obvious noise + 1 per interesting candidate`; `uncertain` is acceptable — no multi-agent ladder

### Phase 4 — Dependency Model + Graph + Report (Tier 1 core)
- Model stores `service_a/b, resource, resource_type, evidence, verdict, confidence, reason` — service-to-resource, not collapsed `orders → reports`
- Graph `networkx` + `matplotlib`, resource-based `Service ↔ Resource` with distinct node styles; demo artifact
- Report exposes evidence, verdict/reason, and confidence per finding

**→ Tier 1 complete here. You have a finished, working, demoable project regardless of what happens next.**

### Phase 5 — Real-world sanity check (Tier 1, lighter version)
- Pick **one small, real open-source multi-service repo** — pre-scout it before committing (skim its `docker-compose.yml` and a bit of source for 10-15 minutes first, so you know it's likely to have *something* interesting before spending real time on it)
- Run your Tier 1 tool against it, note what it finds — even a messy or ambiguous result is a legitimate, honest thing to write up

### Phase 5 (revised) — Real-world validation BEFORE any extension
- Run Tier 1 against multiple real Compose repos via existing CLI; record candidates/findings/false positives/misses per repo
- Build manually reviewed evaluation set (synthetic + real); precision/recall where defensible; evaluate deterministic stages separately from LLM; check LLM reliability/calibration
- Fix demonstrated weaknesses only (repro + smallest fix + regression test + re-evaluation)

### Phase 6 — Tier 2 / extensions (future decision gate, not a commitment)
- Only after Phases 1–4 above: evaluate whether K8s or source analysis adds meaningful discovery capability Tier 1 cannot provide, with concrete example + design + validation plan
- No K8s adapter, dependency, source read/write analysis, or Tier 1 redesign until approved

### Phase 7 — Write-up (always do this, however far you got)
- What you built, what it found, one or two concrete examples (synthetic + real)
- Be plain about scope: "this version handles env vars and shared volumes; DB-naming via resolved evidence is a natural next step" reads as a deliberate, honest scoping decision, not a gap you're hiding

---

## 8. What "Done" Looks Like

**Minimum (Tier 1 only):** A working tool that reads Docker Compose configs, flags shared env vars and shared volumes across services, deterministically filters obvious coincidences and builds bounded evidence (including what values resolve to), uses one LLM call per surviving candidate (cached) to judge meaningful vs coincidental vs uncertain with confidence, and draws a resource-based graph + report — validated on your own synthetic repos plus one real one. That alone is a complete, presentable, resume-worthy project.

**With Tier 2:** All of the above, plus Kubernetes manifest support for shared ConfigMaps, Secrets, and relevant shared volumes (same pipeline).

Either outcome is a legitimate finished project. Tier 2 makes it richer; its absence doesn't make Tier 1 incomplete.

---

## 9. One-Sentence Pitch

> "BlindSpot discovers implicit cross-service couplings that are not explicitly represented as service-to-service relationships by combining deterministic configuration analysis, bounded evidence resolution, and lightweight LLM judgment (one call per candidate, confidence-aware)."

(If you finish Tier 2, extend it: "...plus Kubernetes manifest analysis for shared configuration and resources.")

---

## 10. The One Thing to Actually Remember

This doesn't need to be a billion-dollar idea. It needs to be: something you built end-to-end, something you can explain clearly and honestly in an interview, and something that shows you can pick up a genuinely new skill (evidence resolution + bounded prompting under a real time constraint) under a real time constraint. Tier 1 alone does all three. Everything past that is upside, not a requirement.
