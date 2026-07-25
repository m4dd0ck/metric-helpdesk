"""``metric-helpdesk`` command line interface."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

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
