# MetricHelpDesk

Ask questions about your metrics in plain English, answered only through a
[MetricForge](https://github.com/m4dd0ck/metricforge) semantic layer. MCP server for Claude Code
and Claude Desktop, plus an optional Claude API CLI.

```
                  ┌─ MCP server ──▶ Claude Code / Claude Desktop   (your Claude subscription)
metric tools ─────┤
(MetricForge)     └─ ask CLI ─────▶ Claude API                     (only with API credentials)
```

The model never writes SQL. It picks metrics and dimensions that MetricForge defines, and
supplies filter values and dates, which are validated and escaped. So an answer can only use
numbers from definitions you control, and it cannot make up a formula for "revenue".

## Try it

Needs Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
make build
make demo       # seeded 2024 e-commerce warehouse + metric definitions
```

**With Claude Code (no API key):** run `claude` in this directory. `.mcp.json` starts the server,
so you can ask:

> Why did revenue dip in July 2024?

Claude lists the metrics, sees revenue fall 7.9% while cancellations tripled, breaks the change
down by country and payment method, and lands on German card payments. The full session is in
[transcripts/claude-code-july-dip.md](transcripts/claude-code-july-dip.md).

To use it from Claude Desktop, add the same server to its config with an absolute path:

```json
{"mcpServers": {"metric-helpdesk": {"command": "uv", "args": [
  "run", "--directory", "/path/to/metric-helpdesk", "metric-helpdesk", "serve"]}}}
```

**Offline:** `make replay` plays a saved session through the real tools; no Claude access needed.

**With the Claude API:** set `ANTHROPIC_API_KEY` (or `ant auth login`), then

```bash
uv run metric-helpdesk ask "Which product category brought in the most revenue in 2024?"
uv run metric-helpdesk ask "..." --record transcripts/my-session.json
```

Without credentials, `ask` explains the two options above instead of failing.

**Your own data:** point the server at any MetricForge project:
`metric-helpdesk serve --metrics path/to/metrics --db path/to/warehouse.duckdb`.

## Tools

| Tool | What it does |
|------|--------------|
| `list_metrics` | Every queryable metric with its table, dimensions and time dimension |
| `describe_metric` | A metric's definition and the SQL a monthly query compiles to |
| `query_metrics` | Metrics by time grain and dimensions, within a date range, with filters |
| `compare_periods` | One metric across two date ranges, broken down by a dimension, largest changes first |

`compare_periods` is what makes "why" questions answerable: it reports each dimension value's
change and, for sums and counts, its share of the total change. Averages and ratios get no share,
because their parts do not add up to the whole.

## Guardrails

- **No model-written SQL.** Metric and dimension names are checked against the catalog (with
  did-you-mean suggestions), filter values become escaped literals, and dates arrive as parsed
  dates. The SQL itself comes from MetricForge.
- **Read-only warehouse.** The DuckDB file is attached `READ_ONLY` into an in-memory database.
- **Only metrics MetricForge can answer.** Cumulative metrics and metrics spanning tables are
  left out of the catalog. A request mixing tables is refused with a hint to query separately.
- **Bounded results.** At most 500 rows per query, with a `truncated` flag.
- **Errors the model can act on.** Bad names and arguments come back as tool errors with the fix
  in the message, so Claude corrects itself instead of guessing.

## The demo data

A year of orders (~15k) and website sessions (~90k) with mild seasonality. One planted story: in
July 2024 card checkout in Germany failed for most of the month, so German card orders were
cancelled. June and July demand is otherwise equal. Revenue drops $7,265 (-7.9%), Germany
accounts for 113% of it, and 129 of Germany's 130 extra cancellations are card orders. The
tools can find all of this; nothing tells the model where to look.

## Evals

`evals/questions.yaml` holds questions with checkable facts rather than reference answers:
tools that must be called, numbers the answer must contain (computed from the warehouse when
grading), and patterns that must or must not appear. One question (customer acquisition cost)
has no answer in the data; the check is that the model says so.

```bash
make evals       # headless Claude Code on your subscription
make evals-api   # Claude API, needs credentials
```

Latest Claude Code run: **7/7** ([evals/results/claude-code.json](evals/results/claude-code.json),
answers included).

## What is and isn't tested

- **Offline, in CI:** tools, validation and escaping, the MCP server over the MCP protocol, the
  `ask` tool loop against a scripted client, and a full replay through the real tools.
- **Live, by hand:** the eval set through Claude Code, recorded above.
- **Not yet live:** the Claude API path. `transcripts/july-dip.json` is a hand-built fixture
  (marked as such) showing the loop's shape; `--record` replaces it with a real session once
  credentials are available.

## Limits

- MetricForge compiles single-table queries, so one call cannot combine metrics from different
  tables. Claude handles this by making two calls (see the `cross_table` eval).
- The data explains *where* and *when* a number moved, not *why* in the business sense; answers
  are prompted to say so.
- DuckDB warehouses only, like MetricForge.

## Project structure

```
metric-helpdesk/
├── src/metric_helpdesk/
│   ├── catalog.py      # queryable metrics and their dimensions
│   ├── warehouse.py    # read-only attach
│   ├── tools.py        # the four tools, no AI dependency
│   ├── models.py       # tool inputs and outputs
│   ├── server.py       # MCP server
│   ├── ask/            # Claude API loop, tool schemas, record/replay
│   ├── demo.py         # seeded demo warehouse
│   ├── demo_metrics/   # demo MetricForge definitions
│   ├── evals.py        # questions, grader, Claude Code runner
│   └── cli.py          # serve, demo, ask, eval
├── evals/              # questions and recorded results
├── transcripts/        # replayable and example sessions
├── tests/
├── .mcp.json           # registers the demo server for Claude Code
└── Makefile
```

## License

MIT
