"""``metric-helpdesk`` command line interface."""

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown

from metric_helpdesk.ask.loop import DEFAULT_MODEL, AskResult, MessagesClient, run_question
from metric_helpdesk.ask.transcript import (
    RecordingClient,
    ReplayClient,
    Transcript,
    TranscriptError,
)
from metric_helpdesk.demo import build_demo
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
