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

## 2026-11-20 — Phase 0 (repo skeleton), done

**Done**
- `import planner` works from `~/code/calendar-planner`.
- Step 3: six subpackages from the brief, each with a docstring stating its job.
  `tests/test_smoke.py` imports each one (parametrized, so failures are reported per
  package).
- Step 4: ruff, mypy (strict) and pytest (`--strict-markers`) configured in
  `pyproject.toml`. ruff skips `docs/` so the brief is never reformatted.
- Step 5: pre-commit with local hooks that call `uv run` (same versions as `uv.lock`,
  mypy sees project dependencies), plus detect-private-key, large-file, YAML/TOML checks.
- Step 6: GitHub Actions CI runs `uv sync --locked` and the four checks on every push
  and PR. Green on GitHub (`swarilord/calendar-planner`, public).
- Pushing uses a fine-grained token (this repo only, Contents + Workflows, 90 days),
  stored in the macOS Keychain.

**Problems found**
- First CI run failed: `astral-sh/setup-uv@v10` does not exist, because setup-uv only
  publishes exact tags. Fixed by pinning `v10.4.0`. Lesson: check that a tag exists,
  not only which release is newest.

**Next**
- Write `docs/decisions.md` entries (in my own words): Python 3.13, flat layout,
  mypy strict, repo outside iCloud, local pre-commit hooks via `uv run`, pre-commit
  plus CI.
- Phase 1: throwaway "hello agent" in ADK with `get_now()`.

**Open questions**
- Before putting the repo link on my CV: keep `CLAUDE.md` and the Claude co-author
  lines public, or remove them from history?
- Add gitleaks when the first real API key appears (Phase 1)?
