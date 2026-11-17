# Progress log

## 2026-11-17 — Phase 0 (repo skeleton), in progress

**Done**
- Step 1: `git init`, `.gitignore` covering secrets (.env, OAuth token/client files),
  venv, caches, personal settings. Verified with `git check-ignore`.
- Step 2: `pyproject.toml` (Python 3.13, uv_build backend with flat layout),
  dev group: ruff, mypy, pytest, pre-commit. `uv.lock` committed.
- Decisions: Python 3.13 (not 3.14: C-extension wheels such as OR-Tools lag new
  Pythons), flat layout as in the brief, mypy in strict mode.

**Problem found**
- The repo was in `~/Documents`, which iCloud Drive syncs. iCloud sets the macOS
  "hidden" flag on files in `.venv/`, and Python 3.13 skips hidden `.pth` files, so
  `import planner` failed. Fix: move the repo to `~/code/calendar-planner` (outside
  iCloud) and recreate `.venv` with `uv sync`.

**Next**
- Verify `import planner` works from the new location.
- Step 3: package layout (`planner/agent, parser, solver, checker, calendar, api`) and
  a smoke test.
- Step 4: ruff / mypy / pytest config. Step 5: pre-commit. Step 6: GitHub Actions.
- Create the public GitHub repo (browser) and push.
- Write `docs/decisions.md` entries (in my own words): Python 3.13, flat layout,
  mypy strict, repo location outside iCloud.

**Open questions**
- None.
