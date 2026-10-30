# BlindSpot — Find the Dependencies Your Monitors Can't See

**BlindSpot scans Docker Compose projects for hidden couplings: two services that quietly rely on the same database, shared volume, or configuration — without ever calling each other on the network.**

Available tracing tools (Dynatrace, Datadog, etc.) only see network traffic. BlindSpot catches the other kind of dependency — the kind that lives in shared environment variables and shared volumes. When one team changes "their" database, BlastRadius reaches services they didn't know existed. BlindSpot finds those relationships, explains them, and tells you how confident it is.

It runs **entirely on your machine**: it reads your `docker-compose.yml` and `.env` files as text, writes results to a local `out/` folder, and never uploads your code anywhere. Optionally it asks an LLM (OpenRouter or Gemini) to judge ambiguous cases — that key stays in your local `.env`.

---

## Quick Start

Three commands and you're done. Full details for each step are in the sections below.

```bash
# 1. Get the code
git clone <your-repo-url> BlindSpot
cd BlindSpot

# 2. Install (first time only — creates a Python environment)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
python -m pip install -r requirements.txt

# 3. Run it (interactive questions, guided)
python run.py
```

Want the point-and-click version instead of terminal reports? After the install above:

```bash
npm install --prefix frontend   # first time only (needs Node.js 18+)
python start_ui.py              # starts everything and opens your browser
```

---

## Installation (first time only)

### 1. Get the code

```bash
git clone <your-repo-url> BlindSpot
cd BlindSpot
```

### 2. Python environment

BlindSpot needs **Python 3.10+**. Create an isolated environment so its dependencies don't clash with anything else on your system:

**Windows (cmd.exe):**

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

**macOS / Linux / Git Bash:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This installs the parser and graph tools (`pyyaml`, `python-dotenv`, `networkx`, `matplotlib`) and the optional LLM clients (`google-genai`, `openai`).

> **Important:** always launch BlindSpot through `run.py` (or with the venv activated). Running `import yaml` with bare system Python usually fails with `ModuleNotFoundError: No module named 'yaml'` — the venv is where PyYAML lives.

### 3. Node.js — only for the web UI

The terminal workflow needs no Node at all. To use the browser UI, install **Node.js 18+** (from https://nodejs.org), then run the `npm install --prefix frontend` step shown in Quick Start once — the `start_ui.py` launcher also does this automatically for you on first run.

### 4. LLM API key — optional, recommended

BlindSpot works without any key, but works *best* with one: the LLM judges whether two services sharing a variable means "same real dependency" or "coincidence". **You never have to edit `.env` by hand.** On your first run, if no key is found, BlindSpot asks:

```
No LLM API key found in .env
Would you like to enter an API key? [Y/n]: Y
Paste your API key (OpenRouter sk-or-... or Gemini AIza...): sk-or-v1-...
Saved OPENROUTER_API_KEY to .env — will be used for LLM analysis.
```

* **Y** → paste an OpenRouter (`sk-or-...`) or Gemini (`AIza...`) key. It is saved to your local `.env` (which is gitignored) and reused from then on.
* **n** → BlindSpot runs in **deterministic-only mode**: it still parses everything, builds the graph and report, and flags potential shared resources — but without AI reasoning, findings carry `uncertain (0.0)` confidence and note "Deterministic-only mode". You'll be asked again next run.

---

## Running the Analysis (terminal)

```cmd
python run.py        :: Windows — or double-click run.bat
python run.py        :: macOS / Linux — or bash run.sh
```

You'll be asked two questions:

```
========================================================
  BlindSpot — Implicit Cross-Service Coupling Detector
========================================================
  Enter absolute application path (e.g. C:\path\to\YourApp): C:\path\to\YourApp
  Select AI thinking level [low / medium / high] (default: low): low
```

1. **Application path** — absolute path to a folder containing a `docker-compose.yml` (or `compose.yml`, searched recursively). Quote paths with spaces: `"C:\My Projects\App"`. On Windows, give the path from the drive root, e.g. `C:\...`; on macOS/Linux, `/path/to/repo`.
2. **Thinking level** — `low` (fast/cheap), `medium`, or `high` (thorough). This only affects LLM calls, which happen later per interesting finding.

If no API key is present, a third prompt appears (see installation step 4). `Ctrl+C` exits cleanly at any point.

When it finishes you'll see a summary like:

```
Analysis complete

Input
  Compose sources used : 1 (docker-compose.yml)

Parsed
  Services             : 5
  Named volumes        : 1

Analysis
  Candidates generated : 6
  Observations         : 6
  Resource groups      : 1
  Groups judged        : 1
  Meaningful couplings : 1

Graph
  Nodes                : 4
  Edges                : 3
```

Every number here also appears in `report.json` / `report.md`, so evidence is auditable — including when it's legitimately *zero* ("parsed 5 services but no shared-resource evidence found", which is not an error).

**Your results** land under `out/<app-name>/`:

```cmd
type out\YourApp\report.md      :: the human-readable report
type out\YourApp\graph.json     :: machine-readable graph
```

Re-running analysis on the same app keeps history instead of overwriting: `report.json` → `report_1.json` → `report_2.json`… (same for `.md`, `graph.json`).

**For scripting, you can skip the menu:**

```cmd
python run.py "C:\path\to\repo1" --thinking low
python run.py "C:\path\to\repo" --thinking medium --provider openrouter --out out
python run.py --list-fixtures     REM show the built-in example projects and exit
```

| Flag | Meaning |
|---|---|
| `--compose <file>` | analyze one explicit Compose file |
| `--provider auto\|openrouter\|gemini` | which LLM provider to use |
| `--thinking low\|medium\|high` | effort/verbosity of LLM calls (default `low`) |
| `--cache <file>` / `--cache none` | verdict cache location (default `cache.json`) or disable |
| `--all` | also include coincidental/uncertain findings in the graph & report |
| `--out <dir>` | where to write results (default `out/`) |
| `--interactive` | force the question menu even with flags |

---

## Viewing Results in the Web UI

The graph explorer turns a run into an interactive picture: services on one side, shared resources in the middle, and the potential hidden dependency highlighted in yellow.

**One-click (recommended):**

```bash
# Windows — double-click, or in a terminal:
start_ui.bat
# macOS / Linux / Git Bash:
bash start_ui.sh
```

This starts the local API, starts the frontend, and **opens your browser automatically** (http://localhost:5173). Frontend packages install themselves on the first run. Press `Ctrl+C` (or close the window) to stop everything.

**Like a "production" feel?** `start_ui.bat --build` compiles the frontend once and serves it from the API itself at http://127.0.0.1:8765 — afterwards it needs no Node process.

**Two-terminal alternative:** start `.venv\Scripts\python.exe api\server.py`, then in a second terminal `cd frontend && npm run dev` and open http://localhost:5173.

What you'll see:

* **Dependency graph** (default screen) — explicit `depends_on` arrows in grey, potential hidden couplings **in yellow**, uncertain ones dashed. Rejected coincidences are hidden until you toggle "Show rejected".
* **Click anything** — services, resources, and edges each open a side panel with the underlying evidence (which variables, which files, what the values resolve to), a confidence bar, and the reasoning behind every decision.
* **Analyze repository tab** — paste a local repository path, pick a thinking level, hit "Run analysis". It runs the same pipeline as `run.py` and no cloud is involved.
* The sidebar lists all runs found under `out/`. Useful URL parameters: `?run=shared_env`, `?select=…`, `?view=analyze`.

**Tip:** the `fixtures/` directory ships with three tiny self-contained example projects (`shared_env`, `shared_volume`, `near_miss`). Analyze one of them — `python run.py "<full path to fixtures\shared_env>" --thinking low` — to have real sample data in `out/` for the graph UI within seconds.

---

## How It Works (7 stages, in plain words)

| # | Stage | What happens | Why it matters |
|---|-------|--------------|----------------|
| 1 | **Parse + Normalize** | Reads every supported file format, traces `${VAR}` references and `env_file` imports through your Compose setup, keeps unresolved references visible | Reliable foundation, never guesses values |
| 2 | **Candidate Discovery** | Broadly collects *possible* shared resources: services with the same variable names, shared named volumes, `depends_on` chains, and same-database connections under different variable names | This is just suspicion — not yet a finding |
| 3 | **Filter + Evidence + Identity** | Drops obvious noise (`PORT`, `DEBUG`, `LOG_LEVEL`) — these cost zero LLM calls — then resolves what each value actually points to (a Compose service? an external DB?) and groups observations pointing at the *same physical resource* even when variable names differ | Cheaper and more accurate than treating every name match as a dependency |
| 4 | **LLM Judge** | One LLM call per surviving *shared resource group* (not per service pair!), returning `meaningful` / `coincidental` / `uncertain`, a confidence score, and a reason. Results are cached so repeated runs are stable and cheap | The LLM judges evidence you can read — it never free-roams your codebase |
| 5 | **Coupling + Decision Model** | Persists the groups (who shares what, which services observe it, verdict, confidence) and applies a deterministic policy to each candidate: `potential_dependency`, `review`, or `insufficient_evidence` | Every finding keeps *why* it was concluded, not just *that* it was |
| 6 | **Resource Graph** | Builds a bipartite graph — **services on one side, shared resources on the other** — as plain JSON (`{"nodes": [...], "edges": [...]}`) the web UI renders. Potential hidden couplings are `service → resource`, never a fake direct service↔service arrow | The mechanism of the coupling is visible, the data is deterministic |
| 7 | **Report** | Human-readable Markdown + JSON: conclusion first, then evidence, then technical details, with all confidence values preserved | Removes the need to interpret raw configuration by hand |

Design principles, briefly:

* **Discovery is deterministic, judgment is LLM.** Code finds candidates and gathers machine-verified facts; the LLM only interprets that bounded evidence.
* **Shared names are not automatically dependencies.** Identical env keys are often coincidence — the pipeline distinguishes the two before spending anything.
* **Evidence travels with the finding.** Every result includes which variables, which files, what values resolve to, and how confident the judgment is.
* **Same run in, same result out.** Deterministic IDs and caching make the analysis reproducible and cheap to repeat.
* **Wording stays careful.** Findings are *potential* couplings with evidence and confidence — never claimed as proven runtime behavior.
* **The LLM provider is an implementation detail.** Works with Gemini or OpenRouter (or none). Which model produced a verdict is recorded internally for audits, kept out of the shared report.

---

## Example Output

`report.md` reads like a review comment, with the tech trail attached:

```markdown
## 1. Shared PostgreSQL Database Configuration
Services involved:
- calcom
- calcom-api
- studio

Assessment: Meaningful implicit coupling
Confidence: Medium (0.80)
...
```

`graph.json` (the same data the UI renders):

```json
{
  "nodes": [
    {"id": "service:calcom", "type": "service", "data": {"name": "calcom"}},
    {"id": "resource:env_var:postgresql|${database_host}||${POSTGRES_DB}",
     "type": "resource",
     "data": {"resource_type": "env_var", "resource_protocol": "postgresql", "identity_strength": "config"}}
  ],
  "edges": [
    {"id": "service:calcom->resource:...", "source": "service:calcom", "target": "resource:...", "data": {"confidence": 0.8, "classification": "potential_hidden"}}
  ]
}
```

Edge classifications you'll encounter:

| Classification | Meaning | Visual |
|---|---|---|
| `explicit` | declared Compose `depends_on` (startup order) | grey line |
| `potential_hidden` | judged *meaningful* shared resource | **yellow line** |
| `uncertain` | judged inconclusive (deterministic-only or low evidence) | dashed line |
| `rejected` | judged coincidental | dotted (hidden by default) |

---

## Built-in Fixtures (example projects)

| Fixture | Demonstrates |
|---|---|
| `fixtures/shared_env/` | two services sharing `DB_HOST` via `env_file` + `.env` + `${VAR}` interpolation → 1 meaningful finding |
| `fixtures/shared_volume/` | two services sharing a named `shared-data` volume → 1 meaningful finding |
| `fixtures/near_miss/` | shares only coincidences (`PORT` with different values, `APP_ENV`) → **no findings** — the filter doing its job |
| `fixtures/stage12_levels/` | mixes explicit `depends_on`, cross-variable endpoint identity, unresolved values, and missing targets |

These are regression fixtures with deliberately messy real-world-style Compose files (merged env files, defaults, image overrides), kept small and hermetic.

---

## Verify Your Installation

```bash
cd BlindSpot
python -m pytest -q            # 174 tests should pass
cd frontend
npm run typecheck              # should finish silently (0 type errors)
npm run build                  # builds the UI for the API server
```

---

## Project Structure

```
Blindspot/
├── run.py / run.bat / run.sh         — one-command CLI analysis (interactive)
├── start_ui.py / .bat / .sh          — one-command web UI (API + frontend + browser)
├── requirements.txt                  — Python dependencies
├── .env                              — your API key (gitignored, created via prompt)
├── cache.json                        — LLM verdict cache (gitignored)
├── out/<repo>/                       — per-repo results (report/graph JSON + Markdown, versioned history)
├── fixtures/                         — three tiny example projects + a levels-mix fixture
├── src/blindspot/                    — the 7-stage pipeline (parser, discovery, filtering,
│                                       resolution, aggregation, judge, coupling, decision,
│                                       graph, report, cli)
├── api/server.py                     — local run server + static hosting for the UI (stdlib only)
├── frontend/                         — React + TypeScript graph explorer (Vite, React Flow)
├── tests/                            — 174 hermetic tests, no network
└── docs: AGENTS.md, STATE.md, DECISIONS.md, HANDOFF.md, PROJECT_PLAN.md
```

---

## Supported Inputs

**Works with:** `docker-compose.yml` / `docker-compose.yaml` / `compose.yml` / `compose.yaml`, plus the equivalent JSON (`docker-compose.json` / `compose.json`). Also reads `.env` files and Compose `env_file:` imports, understands `${VAR}`, `${VAR:-default}`, `$VAR` interpolation (unresolved variables stay visibly unresolved — never invented, never silently dropped), and merges multi-file setups (e.g. `docker-compose.override.yml` patterns: env override, volume union, `depends_on` union).

**Does not (yet):** Kubernetes manifests, Terraform, remote URLs. Docker itself does not need to be running — everything is static file analysis.

Dependency levels BlindSpot distinguishes: **L0** — explicit `depends_on` (baseline context); **L1** — shared resource across services (the hidden-coupling focus). Table-level (L2) analysis is a future direction.

---

## Technology

Python 3.10+ · `pyyaml` · `python-dotenv` · `networkx` · `matplotlib` (optional) · `google-genai` · `openai`. Frontend: Vite · React 19 · TypeScript · `@xyflow/react` · dagre · lucide-react. No Docker, no database, no cloud services, no telemetry.

---

## Documentation

* `STATE.md` — current project state (what exists, what's verified)
* `DECISIONS.md` — why every significant architectural choice was made (D-001…D-046)
* `HANDOFF.md` — orientation notes for the next developer/agent
* `AGENTS.md` — the architecture contract the implementation follows
* `PROJECT_PLAN.md` — original build plan

Run `python run.py` for a guided analysis, or `python start_ui.py` to browse an interactive graph — both work on Windows, macOS, and Linux.
