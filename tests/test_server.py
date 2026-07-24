import json
from pathlib import Path

import pytest
from mcp import Client

from metric_helpdesk.server import CALL_LOG_ENV, build_server
from metric_helpdesk.tools import HelpDesk

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_server_lists_the_four_tools(helpdesk: HelpDesk) -> None:
    tools = await build_server(helpdesk).list_tools()
    assert sorted(tool.name for tool in tools) == [
        "compare_periods",
        "describe_metric",
        "list_metrics",
        "query_metrics",
    ]


async def test_query_over_the_protocol_returns_structured_rows(helpdesk: HelpDesk) -> None:
    async with Client(build_server(helpdesk)) as client:
        result = await client.call_tool(
            "query_metrics",
            {
                "metrics": ["completed_orders"],
                "grain": None,
                "start_date": "2024-01-10",
                "end_date": "2024-01-11",
                "filters": [{"dimension": "country", "values": ["US"]}],
            },
        )
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["rows"] == [{"completed_orders": 2}]


async def test_unknown_metric_is_a_tool_error_with_a_suggestion(helpdesk: HelpDesk) -> None:
    async with Client(build_server(helpdesk)) as client:
        result = await client.call_tool("describe_metric", {"name": "revenu"})
    assert result.is_error
    assert "Did you mean revenue" in result.content[0].text  # type: ignore[union-attr]


async def test_out_of_range_limit_is_rejected(helpdesk: HelpDesk) -> None:
    async with Client(build_server(helpdesk)) as client:
        result = await client.call_tool("query_metrics", {"metrics": ["revenue"], "limit": 9999})
    assert result.is_error
    assert "less than or equal to 500" in result.content[0].text  # type: ignore[union-attr]


async def test_calls_are_logged_when_requested(
    helpdesk: HelpDesk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log_path))
    async with Client(build_server(helpdesk)) as client:
        await client.call_tool("list_metrics", {})
        await client.call_tool("describe_metric", {"name": "revenue"})
    calls = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [call["tool"] for call in calls] == ["list_metrics", "describe_metric"]
