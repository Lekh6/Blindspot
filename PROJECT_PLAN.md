# Hidden Dependency Discovery — Final Project Plan

## Status
Committed. Built around realistic pace: **1-2 hrs/day** Structured so a bad week doesn't sink the whole thing — there's a guaranteed working core, and everything past that is a bonus, not a requirement.

---

## 1. The Project — BlindSpot

**BlindSpot** is a tool for discovering implicit cross-service couplings in microservice systems.

## 1. The Project, In Plain Terms

Modern software is usually split into multiple small services that work together — one handles logins, another payments, another emails. These are described in a `docker-compose.yml` file, which lists each service, what it reads from its environment, and what files/folders it shares.

**The problem:** two services can depend on each other without ever directly calling each other. Example: Service A and Service C both silently assume there's a database table called `orders`. Nobody wrote that connection down. If someone renames that table while only thinking about Service A, Service C breaks with zero warning. That's a **hidden dependency**.

**What this tool does:**
1. **Parse + Normalize** — scans `docker-compose.yml` / `.env` files and converts services, environment configuration, and volumes into a consistent internal representation.
2. **Candidate Discovery** — finds services that share resources or configuration and could therefore be coupled.
3. **Candidate Filtering** — removes or prioritizes obvious coincidences and builds the evidence needed for the remaining candidates.
4. **LLM Judge** — for each meaningful candidate, asks an LLM whether the shared resource/configuration represents real coupling or coincidence.
5. **Dependency Model** — stores confirmed relationships as service-to-service dependencies with the shared resource, dependency type, evidence, judgment, and confidence.
6. **Graph + Report** — visualizes the hidden dependency network and explains why each relationship was identified.
7. **(Stretch)** Code reader — scans source code for shared table names using AST parsing and feeds those candidates through the same downstream pipeline.

---

## 2. The Angle (No Competitive Framing Needed)

Standard dependency-mapping tools (Dynatrace, Datadog, distributed tracing) find dependencies by watching network traffic between services — one service calling another's API. That mechanism can only ever see dependencies that involve something being sent over a connection.

The couplings this project targets — shared env vars, shared table-naming conventions, shared filesystem paths — never involve network traffic. Two services can be silently coupled through config or convention while never once talking to each other directly, and that kind of coupling is invisible to anything watching the wire.

That's the honest angle: not "beats existing tools," just "looks at a part of the problem those tools structurally can't see." That's enough of a differentiator for a resume project — it doesn't need to hold up as a startup pitch.


---

## 3. System Requirements

**No VM needed.** Lightweight on hardware — the difficulty is conceptual (AST parsing is new to you), not computational.

| Need | What to install | Why |
|---|---|---|
| Language | Python 3.10+ | Built-in `ast` module; easiest ecosystem for this |
| Editor | VS Code | Standard, good Python support |
| Version control | Git | To clone a real repo later |
| Python packages | `pyyaml`, `python-dotenv`, `networkx`, `matplotlib` | Config parsing, graph drawing |
| LLM access | API key (Claude or OpenAI) | Judgment step — short snippets per call, small budget |
| Docker (optional) | Docker Desktop | Only if you want to actually run services for a live demo — not needed for the tool to work, since it only reads config files as text |

**Hardware:** any normal laptop, 8GB RAM is fine. No GPU — this calls an API, doesn't run a model locally.

---

## 4. System Architecture

**Canonical pipeline:** Parse + Normalize → Candidate Discovery → Candidate Filtering → LLM Judge → Dependency Model → Resource Graph → Report.

Candidate Filtering uses deterministic heuristics before LLM calls; LLM verdicts are cached locally in `cache.json`. The cache key must include the candidate and relevant evidence, not only a variable/value pair.

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
                 │ Environment          │
                 │ Volumes              │
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
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 3. Candidate        │
                 │    Filtering        │
                 │                      │
                 │ Remove/prioritize   │
                 │ obvious coincidences│
                 │                      │
                 │ Build evidence      │
                 │ for remaining       │
                 │ candidates          │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 4. LLM Judge        │
                 │                      │
                 │ Is this shared      │
                 │ resource/config     │
                 │ actually meaningful │
                 │ coupling?            │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 5. Dependency Model │
                 │                      │
                 │ Service ↔ Resource  │
                 │ + type              │
                 │ + evidence          │
                 │ + confidence        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 6. Graph            │
                 │                      │
                 │ Services + hidden   │
                 │ dependencies        │
                 │                      │
                 │ Resource/config     │
                 │ shown as the reason │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 7. Report           │
                 │                      │
                 │ "These services are │
                 │ potentially coupled │
                 │ through X."          │
                 └──────────────────────┘
```

### Stage responsibilities

- **Parse + Normalize:** turn raw Compose/.env input into structured data.
- **Candidate Discovery:** find possible hidden relationships without deciding whether they are real dependencies.
- **Candidate Filtering:** reduce obvious noise before expensive LLM calls, while collecting evidence for candidates that remain.
- **LLM Judge:** determine whether a candidate represents meaningful coupling.
- **Dependency Model:** preserve the discovered relationship and the reasoning behind it.
- **Graph:** show services and their hidden dependencies, with the shared resource/configuration as the explanation.
- **Report:** turn findings into human-readable explanations.

The pipeline intentionally separates **discovery** from **judgment**. Static analysis is deterministic and produces candidates; the LLM only evaluates those pre-extracted candidates rather than reading an entire codebase and guessing freely.

The dependency model should preserve at least:

```text
Dependency
├── service_a
├── service_b
├── resource
├── resource_type
├── evidence
├── judge_result
└── confidence
```

This lets the final output explain not only that two services are connected, but **why** BlindSpot believes they are connected.

**Tier 2 extension:** AST-based code analysis becomes an additional candidate source. Its candidates enter the existing Candidate Filtering → LLM Judge → Dependency Model → Graph → Report pipeline rather than requiring a separate architecture.

## 5. Scope Tiers — This Is the Key Structural Change

**Tier 1 — Must-Have (this is "the project," full stop):**
- Config parser: env var + shared volume coupling detection from `docker-compose.yml` / `.env`
- LLM judgment layer on top of it
- Graph output
- Tested against your own synthetic repos (including a deliberate near-miss)

If you finish only this, you have a complete, working, demoable tool. That's the deliverable you can promise yourself in week 1.

**Tier 2 — Stretch (nice-to-have, only if pace allows):**
- Kubernetes manifest support for shared ConfigMaps, Secrets, and relevant shared volumes
- A real-world multi-service repo test

**Why this order, not config+code together from day one:** AST parsing is the one genuinely new, unpredictable skill here. If it eats more time than expected — likely, since you're learning it from scratch — you don't want it blocking the rest of the pipeline. Tier 1 has zero dependency on it, so it's safe from that risk entirely.

---

## 6. Pace Reality Check (1-2 hrs/day + LeetCode)

Rough math: 1-2 hrs/day, realistically not every single day, lands somewhere around 25-40 hours across a month. That's enough for Tier 1 comfortably, with real room to spare for LeetCode. Tier 2 depends entirely on how Tier 1 goes and how much AST parsing slows you down — treat it as a bonus, not a plan.

**Rule for the month:** if you're on schedule and enjoying it, add Tier 2. If a week gets eaten by LeetCode prep or the AST work is dragging, drop Tier 2 without guilt — Tier 1 alone is a complete, honest, demoable project.

---

## 7. Build Order

### Phase 1 — Setup + ground truth (a few short sessions)
- Install everything (Python, Git, VS Code, API key, virtual env, packages)
- Build 3 deliberately messy synthetic Docker Compose repos by hand:
  - One shared env/config coupling
  - One shared volume coupling
  - One deliberate near-miss (both services define generic `PORT`)
  - Include controlled comments, `${VAR_NAME}` interpolation, and external `env_file` usage
- These are your test fixtures for everything that follows.

### Phase 2 — Config parser (Tier 1 core)
- Parse `docker-compose.yml` + `.env` + supported `env_file` imports, extract env vars and volume mounts per service
- Handle supported `${VAR_NAME}` interpolation and preserve unresolved references
- Compare across services to generate candidates, then apply deterministic filtering before LLM judgment
- Validate: catches the two real couplings, does *not* flag the near-miss

### Phase 3 — LLM judgment layer (Tier 1 core)
- For each candidate coupling, ask the LLM: real coupling, or coincidence?
- Keep the prompt narrow — it only judges a pre-extracted candidate pair, it never reads a whole codebase and guesses freely
- Run each judgment more than once and sanity-check consistency — LLMs aren't perfectly repeatable judges, worth knowing before you trust the output

### Phase 4 — Graph output (Tier 1 core)
- `networkx` + `matplotlib`, functional over polished
- This is your demo artifact — the single most convincing thing to show live or screenshot for a resume/portfolio

**→ Tier 1 complete here. You have a finished, working, demoable project regardless of what happens next.**

### Phase 5 — Real-world sanity check (Tier 1, lighter version)
- Pick **one small, real open-source multi-service repo** — pre-scout it before committing (skim its `docker-compose.yml` and a bit of source for 10-15 minutes first, so you know it's likely to have *something* interesting before spending real time on it)
- Run your Tier 1 tool against it, note what it finds — even a messy or ambiguous result is a legitimate, honest thing to write up

### Phase 6 — Stretch: Kubernetes support (Tier 2, only if time allows)
- Parse Kubernetes manifests
- Identify workloads referencing shared ConfigMaps, Secrets, and relevant shared volumes
- Feed candidates through the existing filtering → LLM Judge → Dependency Model → Resource Graph → Report pipeline

### Phase 7 — Write-up (always do this, however far you got)
- What you built, what it found, one or two concrete examples (synthetic + real)
- Be plain about scope: "this version handles env vars and shared volumes; DB-naming detection is a natural next step" reads as a deliberate, honest scoping decision, not a gap you're hiding

---

## 8. What "Done" Looks Like

**Minimum (Tier 1 only):** A working tool that reads Docker Compose configs, flags shared env vars and shared volumes across services, uses an LLM to filter out coincidental matches, and draws a graph — validated on your own synthetic repos plus one real one. That alone is a complete, presentable, resume-worthy project.

**With Tier 2:** All of the above, plus Kubernetes manifest support for shared ConfigMaps, Secrets, and relevant shared volumes.

Either outcome is a legitimate finished project. Tier 2 makes it richer; its absence doesn't make Tier 1 incomplete.

---

## 9. One-Sentence Pitch

> "BlindSpot discovers implicit cross-service couplings that are not explicitly represented as service-to-service relationships by combining configuration analysis, deterministic filtering, and lightweight LLM judgment."

(If you finish Tier 2, extend it: "...plus Kubernetes manifest analysis for shared configuration and resources.")

---

## 10. The One Thing to Actually Remember

This doesn't need to be a billion-dollar idea. It needs to be: something you built end-to-end, something you can explain clearly and honestly in an interview, and something that shows you can pick up a genuinely new skill (AST parsing, or even just structured static analysis) under a real time constraint. Tier 1 alone does all three. Everything past that is upside, not a requirement.
