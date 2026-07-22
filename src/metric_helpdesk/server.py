"""MCP server exposing the help-desk tools to Claude Code, Claude Desktop or any MCP client."""

import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from metric_helpdesk.models import (
    ComparisonRequest,
    DimensionFilter,
    HelpDeskError,
    MetricDetail,
    MetricList,
    PeriodComparison,
    QueryRequest,
    QueryResult,
    TimeGrain,
)
from metric_helpdesk.tools import HelpDesk

CALL_LOG_ENV = "METRIC_HELPDESK_CALL_LOG"

INSTRUCTIONS = """\
Answer questions about business metrics using only these tools.
- Start with list_metrics to see what exists; never guess metric or dimension names.
- Use describe_metric when the user asks how a number is calculated.
- For "why did X change" questions, use compare_periods to find which dimension values drove it,
  then drill in with filters.
- Name the metrics you used and the periods, and say plainly when the data cannot answer.
"""


def _log_call(tool: str, arguments: dict[str, Any]) -> None:
    """Append the call to a JSON Lines log when evals ask for one."""
    log_path = os.environ.get(CALL_LOG_ENV)
    if log_path:
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": tool, "arguments": arguments}, default=str) + "\n")


def _run[T](tool: str, arguments: dict[str, Any], action: Callable[[], T]) -> T:
    """Log, run, and turn our errors into messages the model can act on."""
    _log_call(tool, arguments)
    try:
        return action()
    except HelpDeskError as error:
        raise ToolError(str(error)) from error
    except ValidationError as error:
        raise ToolError(f"Invalid arguments: {error.errors(include_url=False)}") from error


def build_server(helpdesk: HelpDesk) -> MCPServer:
    """Register the four tools on a new MCP server."""
    server = MCPServer("metric-helpdesk", instructions=INSTRUCTIONS)

    @server.tool(description="List every metric with its table, dimensions and time dimension.")
    def list_metrics() -> MetricList:
        return _run("list_metrics", {}, helpdesk.list_metrics)

    @server.tool(description="Show how a metric is defined and the SQL a monthly query runs.")
    def describe_metric(name: str) -> MetricDetail:
        return _run("describe_metric", {"name": name}, lambda: helpdesk.describe_metric(name))

    @server.tool(
        description=(
            "Compute metrics from one table, optionally by time grain (default month) and "
            "dimensions, within an inclusive date range. Filters keep rows whose dimension "
            "equals one of the given values."
        )
    )
    def query_metrics(
        metrics: list[str],
        group_by: list[str] | None = None,
        grain: TimeGrain | None = "month",
        start_date: date | None = None,
        end_date: date | None = None,
        filters: list[DimensionFilter] | None = None,
        limit: int = 200,
    ) -> QueryResult:
        arguments = {
            "metrics": metrics,
            "group_by": group_by or [],
            "grain": grain,
            "start_date": start_date,
            "end_date": end_date,
            "filters": filters or [],
            "limit": limit,
        }
        return _run(
            "query_metrics",
            arguments,
            lambda: helpdesk.query_metrics(QueryRequest.model_validate(arguments)),
        )

    @server.tool(
        description=(
            "Compare one metric between two inclusive date ranges, broken down by a dimension, "
            "largest changes first. Use it to explain why a metric moved."
        )
    )
    def compare_periods(
        metric: str,
        dimension: str,
        period_a_start: date,
        period_a_end: date,
        period_b_start: date,
        period_b_end: date,
        filters: list[DimensionFilter] | None = None,
    ) -> PeriodComparison:
        arguments = {
            "metric": metric,
            "dimension": dimension,
            "period_a_start": period_a_start,
            "period_a_end": period_a_end,
            "period_b_start": period_b_start,
            "period_b_end": period_b_end,
            "filters": filters or [],
        }
        return _run(
            "compare_periods",
            arguments,
            lambda: helpdesk.compare_periods(ComparisonRequest.model_validate(arguments)),
        )

    return server
