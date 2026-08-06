# Active Task State — Matcha

## Current Focus

**Phase 0 (Foundation) is COMPLETE and Phase 1's entry-point migration is
DONE.** Matcha now runs as a proper installed package: `pip install -e .`,
console script `matcha`, root shims deleted, `src/matcha/` is the only code
home, 152/152 tests pass. **Remaining Phase 1 work is the data-quality work:
OpenCLI backends for LinkedIn/Indeed**, per `revamp/matcha-2.0-strategy.md` §18.

> 2026-08-06 session 1: full repo audit + `.ai_memory/` rewrite.
> Session 2: Agent-Reach v1.5.0 study folded into revamp docs (strategy Rev 3).
> Session 3: pre-implementation analysis (F-01..F-23), strategy Rev 4.
> Session 4: **Phase 0 implemented** (src/ layout, shims, registry, doctor).
> Session 5: **Phase 1 part 1 — entry-point migration** (console script,
> `pip install -e .`, shims deleted, bandit/CI/Docker/README updated).
> Decisions locked in: shims-first (F-04); LinkedIn blank location = `"India"`
> (F-08); console entry is `matcha.main:main` (deviation from plan's
> `matcha.cli:main` — recorded in strategy §18 + handoff).

---

## Phase 1 Part 1 — Entry-point migration (DONE 2026-08-06)

- [x] pyproject `[build-system]` (setuptools) + `[project]` (dynamic version via
      `matcha.__version__`, `requires-python >=3.10`, deps mirror requirements.txt)
      + `[project.scripts] matcha = "matcha.main:main"` + `[tool.setuptools]` src layout
- [x] `venv/bin/pip install -e .` — `matcha` console script live
- [x] Tests rewritten to `matcha.*` / `matcha.sources.*` (imports + mock targets),
      `../src` sys.path bootstrap in all 8 test files
- [x] **Root shims deleted** (`main/profile/ai/matcher/config/settings/models/actions.py`
      + `scrapers/` package) — zero stale references repo-wide (grep-verified)
- [x] Makefile: run* targets → `$(VENV)/bin/matcha`; bandit `-c pyproject.toml -r src/matcha
      -lll`; pyinstaller entry = console-script path; venv bootstrap += `pip install -e .`
- [x] CI: `pip install -e .` (validate + build jobs); bandit `-c pyproject.toml`;
      pyinstaller via `$(command -v matcha)`
- [x] Dockerfile: builder `pip install --user .`; `ENTRYPOINT ["python3", "-m",
      "matcha.main"]`
- [x] README quickstart/fresh-setup/diagram/file-tree updated; in-code `python3 main.py`
      strings → `matcha`
- [x] `.gitignore` += `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `build/`, `dist/`,
      `*.spec`; requirements.txt notes pyproject is the authoritative dep list
- [x] Bandit config is now REAL: `-c pyproject.toml` applies skips (B101/B110/B311/B404/
      B603/B607, documented) → **0 issues, exit 0**; bandit-coverage gap from Phase 0 CLOSED
- **Acceptance met:** 152/152 tests (unittest + pytest); ruff / format / pre-commit /
  bandit clean; `matcha --help`, `matcha doctor`, `matcha doctor --json`,
  `python3 -m matcha.main --help` all work; **pyinstaller onefile build succeeds and the
  binary runs `--help` + `doctor --json`**.

## Immediate Next Steps

1. **Phase 1 part 2 — Data quality (the core Phase-1 work).** Per strategy §18:
   - **OpenCLI backends for LinkedIn/Indeed (+ consent flow)** — the biggest
     data-quality win; probe `opencli --version` + loopback `127.0.0.1:19825/status`
     (never `opencli doctor`); login-gated platforms report `warn`, never `ok`.
   - Exa Web Search backend; Naukri job-page extraction; `agent_reach_io.py`.
   - **Before `agent_reach_io.py`:** verify exact `agent-reach doctor --json` shape and
     `agent-reach install --channels=opencli` flags in
     `~/Code/projects/Agent-Reach/agent_reach/cli.py`.
2. **Do NOT build Phase 2+ features** (no filters module, no enrichment, no AI changes)
   during Phase 1.

## Blockers / Notes

- No blockers.
- **mypy baseline:** `mypy src/matcha` reports **24 errors, all pre-existing 1.x typing
  debt** in legacy files (DDGS `= None` fallbacks, `prompt_loop`/`app` annotations, dict
  reassignments). New modules are mypy-clean. mypy is NOT a project dependency or CI gate
  — defer cleanup to Phase 7. (mypy was pip-installed into the venv for verification only.)
- **Entry point:** `matcha` (venv console script) or `python3 -m matcha.main` (Docker).
  System `python3` (3.14.6) lacks the project deps — use the venv.
- Full findings register: `revamp/matcha-2.0-implementation-analysis.md` (F-01..F-23).
