# Runbook

Procedures for MetricHelpDesk. `README.md` describes what each command does; this file says
when to run it and in what order.

## On open

```bash
git status --short
git log -3 --oneline
```

## On close

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -q
```

## Run

`make demo` once, then `claude` in the repo for the MCP path, or `make replay` for the offline
path. `make serve` runs the server by hand on stdio for debugging.

## Record an eval run

1. `make demo` so the warehouse matches the questions.
2. `make evals` (headless Claude Code on the owner's subscription; several minutes). The
   graded answers land in `evals/results/claude-code.json`.
3. Read the failures before committing the file; a wrong fact in `evals/questions.yaml` is as
   likely as a wrong answer. Commit the results file and note the score in `TASK.md`.

`make evals-api` is the same through the Claude API and needs `ANTHROPIC_API_KEY`.

## Bump MetricForge

1. Change the tag in the `metricforge` dependency line of `pyproject.toml`, then `uv lock`.
2. `uv run pytest` and `make replay`; the replay exercises the real tools against the new
   compiler.
3. Commit, and bump revenue-monitor's pin in the same sitting
   (`~/developer/hq/CONVENTIONS.md` §Versioning).

## Release

Follows `~/developer/hq/CONVENTIONS.md` §Versioning.

1. Bump `version` in `pyproject.toml` and `__version__` in `src/metric_helpdesk/__init__.py`,
   then `uv lock` (CI installs with `--locked`).
2. Commit `chore: Release vX.Y.Z`, tag `git tag -a vX.Y.Z`, push `main` and the tag.
3. `gh release create vX.Y.Z` with handwritten notes; mark it latest.

## Deploy

Not deployed. The server runs on the machine that asks; there is no hosted copy.

## Restore on a new machine

1. Clone the repo, `make build`, `make demo`.
2. `uv run pytest` and `make replay`. Claude Code picks the server up from `.mcp.json`; for
   Claude Desktop add the config block from the README with the new absolute path.

## Validate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/
uv run pytest
make demo
make replay
python3 ~/.claude/scripts/doc-check.py --repo .
```
