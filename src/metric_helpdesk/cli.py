"""``metric-helpdesk`` command line interface."""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from metric_helpdesk.ask.loop import DEFAULT_MODEL, AskResult, MessagesClient, run_question
from metric_helpdesk.ask.transcript import (
    RecordingClient,
    ReplayClient,
    Transcript,
    TranscriptError,
)
from metric_helpdesk.demo import build_demo
from metric_helpdesk.evals import (
    EvalRunError,
    RunOutput,
    grade,
    load_questions,
    run_claude_code,
)
from metric_helpdesk.server import build_server
from metric_helpdesk.tools import HelpDesk

DEMO_DIR = Path("data/demo")

app = typer.Typer(help="Ask questions about your metrics, answered through MetricForge.")
# Reason: stdout belongs to the MCP protocol when serving, so messages go to stderr.
console = Console(stderr=True)

MetricsOption = Annotated[Path, typer.Option(help="MetricForge YAML directory.")]
DbOption = Annotated[Path, typer.Option(help="DuckDB warehouse file.")]


@app.command()
def serve(
    metrics: MetricsOption = DEMO_DIR / "metrics",
    db: DbOption = DEMO_DIR / "shop.duckdb",
) -> None:
    """Run the MCP server over stdio (Claude Code and Claude Desktop launch this)."""
    build_server(HelpDesk.open(metrics, db)).run("stdio")


@app.command()
def demo(out: Annotated[Path, typer.Option(help="Output directory.")] = DEMO_DIR) -> None:
    """Build the seeded demo warehouse and metric definitions."""
    paths = build_demo(out)
    console.print(f"Demo warehouse: [bold]{paths.db_path}[/]")
    console.print(f"Metric definitions: [bold]{paths.metrics_dir}[/]")


NO_CREDENTIALS = """No Claude API credentials found (ANTHROPIC_API_KEY, or `ant auth login`).

You can still ask questions without an API key:
  - With Claude Code: run `make demo`, then `claude` in this directory. The MCP server in
    .mcp.json answers through the same tools, on your Claude subscription.
  - Offline: `metric-helpdesk ask --replay transcripts/july-dip.json` replays a saved session."""


def has_credentials(client: Any) -> bool:
    """True when the SDK found an API key, auth token or login profile."""
    return any(getattr(client, name, None) for name in ("api_key", "auth_token", "credentials"))


class ApiMessagesClient:
    """Adapts ``AsyncAnthropic().beta.messages`` to the loop's MessagesClient protocol."""

    def __init__(self, client: Any) -> None:
        self._messages = client.beta.messages

    async def create(self, **params: Any) -> Any:
        return await self._messages.create(**params)


def api_messages_client() -> MessagesClient:
    """The real Claude API client, or exit with guidance when there are no credentials."""
    import anthropic

    client = anthropic.AsyncAnthropic()
    if not has_credentials(client):
        typer.echo(NO_CREDENTIALS, err=True)
        raise typer.Exit(code=2)
    return ApiMessagesClient(client)


def print_answer(result: AskResult) -> None:
    for call in result.tool_calls:
        status = "[red]error[/]" if call.is_error else "[green]ok[/]"
        console.print(f"[dim]tool[/] {call.name} {status}")
    Console().print(Markdown(result.answer))


@app.command()
def ask(
    question: Annotated[
        str | None, typer.Argument(help="Question; optional with --replay.")
    ] = None,
    metrics: MetricsOption = DEMO_DIR / "metrics",
    db: DbOption = DEMO_DIR / "shop.duckdb",
    model: Annotated[str, typer.Option(help="Claude model ID.")] = DEFAULT_MODEL,
    record: Annotated[Path | None, typer.Option(help="Save the session to this file.")] = None,
    replay: Annotated[Path | None, typer.Option(help="Replay a saved session.")] = None,
) -> None:
    """Answer a question with the Claude API (needs API credentials), or replay a saved one."""
    messages_client: MessagesClient
    if replay:
        try:
            replay_client = ReplayClient(Transcript.load(replay))
            question = question or replay_client.transcript.question
            replay_client.check_question(question)
        except TranscriptError as error:
            raise typer.BadParameter(str(error)) from error
        model = replay_client.transcript.model
        console.print(f"[dim]Replaying {replay} ({replay_client.transcript.source})[/]")
        messages_client = replay_client
    elif question is None:
        raise typer.BadParameter("Ask a question, or pass --replay.")
    else:
        messages_client = api_messages_client()
        if record:
            messages_client = RecordingClient(messages_client, question, model)

    server = build_server(HelpDesk.open(metrics, db))
    console.print(f"[bold]Q:[/] {question}")
    print_answer(asyncio.run(run_question(messages_client, server, question, model)))
    if record and isinstance(messages_client, RecordingClient):
        messages_client.transcript.save(record)
        console.print(f"[dim]Saved session to {record}[/]")


PROJECT_ROOT = Path.cwd()


@app.command(name="eval")
def run_eval(
    runner: Annotated[
        Literal["claude-code", "api"], typer.Option(help="claude-code uses your subscription.")
    ] = "claude-code",
    questions: Annotated[Path, typer.Option(help="Questions file.")] = Path("evals/questions.yaml"),
    only: Annotated[str | None, typer.Option(help="Run one question id.")] = None,
    model: Annotated[str | None, typer.Option(help="Model override.")] = None,
    metrics: MetricsOption = DEMO_DIR / "metrics",
    db: DbOption = DEMO_DIR / "shop.duckdb",
    out: Annotated[Path | None, typer.Option(help="Write results JSON here.")] = None,
) -> None:
    """Ask every eval question and grade the answers on facts."""
    helpdesk = HelpDesk.open(metrics, db)
    selected = [q for q in load_questions(questions) if only is None or q.id == only]
    messages_client = api_messages_client() if runner == "api" else None

    table = Table(title=f"Evals ({runner})")
    for column in ("Question", "Result", "Failed checks"):
        table.add_column(column)
    records = []
    for question in selected:
        console.print(f"[dim]asking[/] {question.id}")
        try:
            if messages_client is not None:
                server = build_server(helpdesk)
                ask_result = asyncio.run(
                    run_question(messages_client, server, question.question, model or DEFAULT_MODEL)
                )
                output = RunOutput(ask_result.answer, [c.name for c in ask_result.tool_calls])
            else:
                output = run_claude_code(question.question, PROJECT_ROOT, model)
        except EvalRunError as error:
            output = RunOutput(answer=f"RUN ERROR: {error}", tools_called=[])
        checks = grade(helpdesk, question, output.answer, output.tools_called)
        passed = all(check.passed for check in checks)
        failed = "; ".join(
            f"{c.name} ({c.detail})" if c.detail else c.name for c in checks if not c.passed
        )
        table.add_row(question.id, "[green]pass[/]" if passed else "[red]fail[/]", failed)
        records.append(
            {
                "id": question.id,
                "question": question.question,
                "passed": passed,
                "tools_called": output.tools_called,
                "checks": [vars(check) for check in checks],
                "answer": output.answer,
            }
        )
    Console().print(table)
    passed_count = sum(1 for record in records if record["passed"])
    console.print(f"{passed_count}/{len(records)} passed")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "runner": runner,
            "model": model or ("claude-code default" if runner == "claude-code" else DEFAULT_MODEL),
            "passed": passed_count,
            "total": len(records),
            "results": records,
        }
        out.write_text(json.dumps(summary, indent=2) + "\n")
        console.print(f"[dim]Wrote {out}[/]")
