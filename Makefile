.PHONY: build demo serve replay evals evals-api test lint clean

build: ## Install dependencies
	uv sync

demo: ## Seeded 2024 e-commerce warehouse plus the metric definitions the server defaults to
	uv run metric-helpdesk demo

serve: ## Start the MCP server
	uv run metric-helpdesk serve

replay: ## Play a saved session through the real tools, offline
	uv run metric-helpdesk ask --replay transcripts/july-dip.json

evals: ## Graded questions through headless Claude Code
	uv run metric-helpdesk eval --runner claude-code --out evals/results/claude-code.json

evals-api: ## Graded questions through the Claude API
	uv run metric-helpdesk eval --runner api --out evals/results/api.json

test: ## pytest
	uv run pytest

lint: ## ruff and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src/

clean: ## Remove the generated data
	rm -rf data/
