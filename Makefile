.PHONY: build demo serve replay evals evals-api test lint clean

build:
	uv sync

# seeded warehouse + metric definitions that .mcp.json and the CLI default to
demo:
	uv run metric-helpdesk demo

serve:
	uv run metric-helpdesk serve

# offline: replays a saved session through the real tools, no API key
replay:
	uv run metric-helpdesk ask --replay transcripts/july-dip.json

# live, on your Claude subscription via headless Claude Code
evals:
	uv run metric-helpdesk eval --runner claude-code --out evals/results/claude-code.json

# live, needs Claude API credentials
evals-api:
	uv run metric-helpdesk eval --runner api --out evals/results/api.json

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src/

clean:
	rm -rf data/
