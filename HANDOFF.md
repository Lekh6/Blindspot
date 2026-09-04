# HANDOFF.md — What the Next Agent Needs to Know

> Read this first when you start a session. It tells you where we left off and exactly what to do next.
**Last Updated:** 2026-09-04
**Current Phase:** **Finished Project — Stages 1–7 DONE** (parser + discovery + filtering + **LLM Judge provider-agnostic** + **Dependency Model model-hidden** + **Graph React Flow DATA** + **Report** + **CLI** one-command)
**Current Branch:** `main` — working tree: complete, demoable

---

## 1. TL;DR for Next Agent

1. Read `AGENTS.md` (§3 bounded evidence, §4 one call/candidate, §5 service-to-resource, §6 React Flow DATA) + `PROJECT_PLAN.md` + `STATE.md` §2, then this file.
2. **Stages 1–7 DONE:** `parser.py` 540 LOC, `discovery.py` 132 LOC, `filtering.py` 355 LOC, `judge.py` 687 LOC, `model.py` 160 LOC + `graph.py` 180 LOC + `report.py` 170 LOC (`ReportFinding:22`, `ReportData:85` `findings + summary{total/meaningful/services/resources} + graph_summary`, `build_report:160` → `report.json`+`report.md` model hidden) + `cli.py` one-command `blindspot` (Parse→Report). **61 tests pass**. `shared_env` 2→2 meaningful, `shared_volume` 1, `near_miss` 0→0.
3. **Full pipeline now:** `parse_compose_file` → `discover_candidates` → `build_evidence_packages` → `judge_evidence_packages` (0+1/candidate, cached) → `DependencyModel.from_judgments` → `build_graph(meaningful_only=True)` → `build_report(model, graph_data)` → `report.json`+`report.md`+`graph.json` (model hidden, `report.log.json` internal). CLI `src/blindspot/cli.py:1` wraps it for one/many repos.
4. Keep updated: `STATE.md`, `DECISIONS.md` (D-028 Report+CLI), `HANDOFF.md`.
5. `.env` gitignored, `!fixtures/**/.env` allowed, `cache.json` ignored.

---

## 2. Where We Left Off

- `AGENTS.md:1` 522 LOC + `PROJECT_PLAN.md:1` 301 LOC hybrid spec.
- **Parser:** `parser.py:45` `Service.image` + `parse_compose_file:488`/`505` + `_merge_projects:401` image override; `D-022`.
- **Filtering:** `filtering.py:70` `EvidencePackage` + `build_evidence_package:180` with HOST/URL-like guard, `host:port` split, `volume_targets`, `related_config` bounded; `D-023`.
- **Judge:** `judge.py:40` `JudgeResult` + `build_judge_prompt:81` + `GeminiJudgeClient:259` + `OpenRouterJudgeClient:475` + `failsafe_result:226` + `judge_evidence_package:582` `cache.json:165` `0+1/candidate`; `D-025`.
- **Model:** `model.py:27` `Dependency{..., _model(hidden)}` + `model.py:108` `DependencyModel{sorted, meaningful_only(), to_dict hides model, to_log_dict retains}` `Stage 4 → Stage 5` service-to-resource, model-blind; `D-026`.
- **Graph:** `graph.py:80` `build_graph(model, meaningful_only=True)` → `{"nodes","edges"}` bipartite, dedup, confidence, model hidden; `tests/test_graph.py` 13; `D-027`.
- **Report:** `report.py:22` `ReportFinding` + `report.py:84` `ReportData{findings, summary{total/meaningful/services/resources}, graph_summary, generated_at}` + `build_report:160` → `report.json`+`report.md` per finding `service_a/b, resource, resource_type, value, evidence{resolved/related/filtering}, verdict, confidence, reason` (model hidden); empty → placeholder; `D-028`.
- **CLI:** `cli.py:1` `blindspot` — one-command full pipeline for one/many repos, `find_compose`, `--provider auto|openrouter|gemini --thinking low/medium --cache cache.json --out out --all`, writes `out/<repo>/report.json+report.md+graph.json+report.log.json` (log has model), summary table; `D-028`.
- Tests: 48 passed (Stage 5 manual: external leak `False`, log retains).

---

## 3. How to Run (Finished Project)

**One-command testing — one or more repos `cli.py:1`:**
```bash
pip install -r requirements.txt
echo OPENROUTER_API_KEY=sk-or-v1-... >> .env  # or GEMINI_API_KEY (auto picks OPENROUTER)
PYTHONPATH=src python -m blindspot.cli fixtures/shared_env --out out --thinking low  # single
PYTHONPATH=src python -m blindspot.cli /path/to/repo1 /path/to/repo2 --out out --provider openrouter --cache cache.json  # many
git clone https://github.com/<small-multi-service-repo> /tmp/real && PYTHONPATH=src python -m blindspot.cli /tmp/real --out out --thinking low
# out/<repo>/report.json (machine, model hidden) + report.md (human) + graph.json (React Flow DATA, bipartite) + report.log.json (internal provider+model) + cache.json reuse
# Summary table printed: cand -> pkgs -> deps (meaningful) -> nodes/edges
```

No further stages — project is complete. To re-run on new repos, use the CLI command above.

---

## 4. Critical Constraints & Gotchas

- **Discovery ≠ Judgment** — LLM only judges filtered + bounded packages (one per package).
- **Shared names ≠ dependencies** — `PORT` filtered before LLM.
- **Evidence matters + bounded** — give LLM smallest machine-verified facts (required + resolved service/image/internal, related DB_* bounded, filtering signals). No unrelated config. Prompt `build_judge_prompt:81` is provider-agnostic.
- **Evidence resolution before LLM** — deterministically resolve `DB_HOST=postgres -> postgres:16` (only HOST/URL-like), `named_volume` internal.
- **One LLM call per survivor** — `0 for obvious noise + 1 per interesting candidate`; `uncertain` allowed; `cache.json` key = `sha256(cache_key_dict)` (not just value); model/version stored. Provider pluggable (Gemini or OpenRouter).
- **Provider-agnostic** — Do not tie prompt/architecture to Gemini; `DEFAULT_MODEL` = `nvidia/nemotron-3-ultra-550b-a55b`, `FAILSAFE_MODEL` = `gemini-3.1-flash-lite`; lazy `type: ignore` imports keep module importable without SDK. `OPENROUTER_MAX_TOKENS` maps thinking low/medium to max_tokens.
- **Confidence is first-class** — `JudgeResult` → `Dependency{verdict, confidence, reason, evidence}` → `Graph`/`Report` (confidence exposed, model hidden externally).
- **Model hidden** — `Dependency._model` stored privately, `to_dict()` omits it, `to_log_dict()`/`cache.json`/`logging` retain it. User never sees provider.
- **Resource graph (RE-ARCHED)** — Stage 6 is **DATA contract** `{"nodes": [{"id": "service:...", "type": "service"}, {"id": "resource:...", "type": "resource"}]` + `edges source→resource` — not `matplotlib`/`graph.png`. Bipartite, dedup by `resource_type`, deterministic, preserves `confidence`, hides `model`, JSON-serializable, extensible `data` for `source_locations` later.
- **Failsafe** — `failsafe_result:226` returns `uncertain 0.5` on missing key/SDK/API error/parse error, attributed to `FAILSAFE_MODEL` (logged, not external).
- **Stack** — `pyyaml`, `python-dotenv`, `google-genai`, `openai`, `networkx`, `matplotlib` (openai only for OpenRouter, google-genai only for Gemini).
- **Windows host** — `C:\Users\Lekha\Projects\Blindspot`, `bash`, `.env` gitignored.

---

## 5. Project Complete Checklist

- [x] `STATE.md` Stages 1–7 DONE (100% code), Graph DATA + Report model hidden
- [x] `HANDOFF.md` Stages 1–7 DONE, CLI one-command documented
- [x] `DECISIONS.md` D-021 → D-028 (hybrid → graph DATA → report+CLI)
- [x] `README.md` finished project (pipeline, fixtures, usage, graph DATA, report format, 61 tests)
- [x] Tests 61 passed (`test_parser` 32 + `test_discovery` 8 + `test_filtering` 8 + `test_graph` 13) + manual synthetic + real-repo via CLI
- [x] `src/blindspot/{parser, discovery, filtering, judge, model, graph, report, cli}.py` complete

No handoff needed — project is finished and demoable via `PYTHONPATH=src python -m blindspot.cli --help`.

---

## 6. Useful Commands

```bash
git status
PYTHONPATH=src .venv/Scripts/python -m pytest -v
# judge with Gemini (low thinking)
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import GeminiJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, GeminiJudgeClient(thinking_level='low'), cache_path='cache.json'))"
# judge with Nemotron Ultra via OpenRouter (provider-agnostic, low=512 tokens)
PYTHONPATH=src .venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); from blindspot.parser import parse_compose_file; from blindspot.discovery import discover_candidates; from blindspot.filtering import build_evidence_packages; from blindspot.judge import OpenRouterJudgeClient, judge_evidence_packages; p=parse_compose_file('fixtures/shared_env/docker-compose.yml'); pkgs=build_evidence_packages(discover_candidates(p), p); print(judge_evidence_packages(pkgs, OpenRouterJudgeClient(thinking_level='low'), cache_path='cache.json'))"
PYTHONPATH=src .venv/Scripts/python -c "from blindspot.judge import JudgeResult, validate_judge_result; validate_judge_result(JudgeResult(verdict='meaningful', confidence=0.93, reason='ok', model='test'))"
```

---

## 7. Files to Read First

1. `C:\Users\Lekha\Projects\Blindspot\AGENTS.md` (§4 one call/candidate, §5 Dependency Model, §6 React Flow DATA contract bipartite)
2. `C:\Users\Lekha\Projects\Blindspot\PROJECT_PLAN.md` (§4 hybrid diagram, §6 DATA)
3. `C:\Users\Lekha\Projects\Blindspot\STATE.md` (Stage 6 re-arched)
4. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/model.py` (`Dependency:27`, `DependencyModel:108`)
5. `C:\Users\Lekha\Projects\Blindspot\src/blindspot/graph.py` (next, `build_graph` DATA contract)
