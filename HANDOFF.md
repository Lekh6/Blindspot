# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.

**Last Updated:** 2026-08-27
**Current Phase:** Initialization — architecture locked, zero code
**Current Branch:** `main` — no commits yet

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (architecture), then `STATE.md` (§2 pipeline table), then this file.
2. Project is **greenfield** — no `src/`, no tests, no dependencies installed. Your first code change should follow the Build Order (§3).
3. Global model is already set to `opencode/muse-spark-1.2-contributor-free` — do not change it unless asked.
4. Keep these three files updated **every session**: `STATE.md` (status), `DECISIONS.md` (append ADR), `HANDOFF.md` (§5 progress).

---

## 2. Where We Left Off

- `AGENTS.md` created from user paste — defines 7-stage pipeline, Tier 1/2 scope, tech stack, principles.
- `~/.config/opencode/opencode.jsonc:16` changed: `model = "opencode/muse-spark-1.2-contributor-free"`.
- `STATE.md`, `DECISIONS.md`, `HANDOFF.md` initialized (this session).
- No code, no commits, no synthetic test repos yet.
- `git status` shows untracked `AGENTS.md`, `STATE.md`, `DECISIONS.md`, `HANDOFF.md`, `.opencode/`.

---

## 3. Immediate Next Steps (Do In Order)

**Do not skip or reorder — per `AGENTS.md` Development Priorities:**

1. **Synthetic test repositories** — create `tests/synthetic/` with at least:
   - `basic-shared-env/` → `docker-compose.yml` + `.env` where two services share `DATABASE_URL` (true positive)
   - `shared-volume/` → two services mounting same volume `app_data:/data`
   - `near-miss-port/` → two services both define `PORT` but unrelated — must NOT be flagged (required by AGENTS.md)
2. **Config parser** (Stage 1) — `src/blindspot/parser.py`: parse `docker-compose.yml` (`pyyaml`) + `.env` (`python-dotenv`), normalize to internal model: `{services: [{name, env:{}, volumes:[]}]}`. Write unit tests against synthetic fixtures.
3. **Candidate discovery** (Stage 2) — detect shared env vars + shared volumes → list of `{service_a, service_b, resource, resource_type, evidence}`.
4. **Candidate filtering** (Stage 3) — filter generic names (`PORT`, `HOST`, `DEBUG`), build evidence strings to justify LLM call.
5. **LLM judge** (Stage 4) — narrow prompt: given candidate + evidence, return `{is_dependency: bool, confidence: 0-1, reasoning}`. Test consistency: run 3x per candidate, log variance.
6. **Dependency model** (Stage 5) — dataclass/store with required 7 fields; preserve `evidence` + `judge_result`.
7. **Graph** (Stage 6) — `networkx` + `matplotlib`, edges labeled by `resource`, nodes = services.
8. **Report** + **Real-world validation** — pick 1 small OSS multi-service repo (e.g., `https://github.com/dockersamples/example-voting-app`), run full pipeline, document findings.

**Tier 2 (AST)** is *blocked* until Tier 1 demo passes.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — never let LLM freely scan codebase; only judge pre-extracted candidates.
- **Shared names are not auto-dependencies** — always go through filtering + LLM; `PORT` near-miss test must pass.
- **Evidence matters** — every dependency must carry `evidence` + `judge_result` + `confidence` into Model/Graph/Report.
- **Extensibility** — AST findings (Tier 2) must reuse same pipeline, not fork.
- **Stack** — `pyyaml`, `python-dotenv`, `networkx`, `matplotlib`, stdlib `ast` only for Tier 2. Python 3.10+.
- **Docker not required** — parse compose as text.
- **Windows host** — paths are `C:\Users\Lekha\Projects\Blindspot`. `bash` tool maps `~` → `C:\Users\Lekha`. `powershell.exe` not available — use `bash`.

---

## 5. Session Handoff Checklist (Update Before You Leave)

Copy this checklist and check it off in your final message:

- [ ] `STATE.md` §2 pipeline statuses flipped if stage completed
- [ ] `STATE.md` §6 Recent Activity appended with date + summary
- [ ] `DECISIONS.md` appended if any new ADR (e.g., parser schema, filtering heuristics)
- [ ] `HANDOFF.md` §§2–3 updated to reflect new next step
- [ ] Tests run and noted (synthetic + near-miss)
- [ ] Commit created? (currently no commits — first commit should be `chore: init blindspot pipeline with synthetic fixtures + parser`)

---

## 6. Useful Commands

```bash
git status
git log --oneline -10
ls -R
cat AGENTS.md
cat STATE.md
cat DECISIONS.md
cat HANDOFF.md
# after init:
python -m venv .venv && source .venv/Scripts/activate  # Windows git-bash
pip install pyyaml python-dotenv networkx matplotlib
pytest -v
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md`
2. `C:\Users\Lekha\Projects\Blindspot\STATE.md`
3. `C:\Users\Lekha\Projects\Blindspot\DECISIONS.md`
4. `C:\Users\Lekha\.config\opencode\opencode.jsonc` (global model)
