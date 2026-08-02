from pathlib import Path
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from metric_helpdesk.ask.loop import FALLBACK_BETA, AskError, run_question
from metric_helpdesk.ask.schemas import inline_refs
from metric_helpdesk.ask.transcript import RecordingClient, ReplayClient, Transcript
from metric_helpdesk.cli import has_credentials
from metric_helpdesk.demo import build_demo
from metric_helpdesk.server import build_server
from metric_helpdesk.tools import HelpDesk

pytestmark = pytest.mark.anyio
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def message(content: list[dict[str, Any]], stop_reason: str) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def tool_use(name: str, arguments: dict[str, Any], tool_id: str = "toolu_1") -> BetaMessage:
    return message(
        [{"type": "tool_use", "id": tool_id, "name": name, "input": arguments}], "tool_use"
    )


def answer(text: str) -> BetaMessage:
    return message([{"type": "text", "text": text}], "end_turn")


class ScriptedClient:
    """Returns canned responses and remembers every request."""

    def __init__(self, responses: list[BetaMessage]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **params: Any) -> BetaMessage:
        # The loop keeps appending to the same list, so snapshot it as sent.
        self.requests.append({**params, "messages": list(params["messages"])})
        return self.responses.pop(0)


async def test_tool_result_goes_back_and_answer_is_returned(helpdesk: HelpDesk) -> None:
    client = ScriptedClient([tool_use("list_metrics", {}), answer("Four metrics.")])
    result = await run_question(client, build_server(helpdesk), "What metrics exist?")

    assert result.answer == "Four metrics."
    assert [call.name for call in result.tool_calls] == ["list_metrics"]
    tool_results = client.requests[1]["messages"][-1]["content"]
    assert tool_results[0]["tool_use_id"] == "toolu_1"
    assert "average_order_value" in tool_results[0]["content"]
    assert tool_results[0]["is_error"] is False


async def test_tool_errors_are_returned_to_the_model(helpdesk: HelpDesk) -> None:
    client = ScriptedClient([tool_use("describe_metric", {"name": "revenu"}), answer("Retrying.")])
    result = await run_question(client, build_server(helpdesk), "Define revenu")

    assert result.tool_calls[0].is_error
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "Did you mean revenue" in tool_result["content"]


async def test_request_uses_medium_effort_and_default_fallbacks(helpdesk: HelpDesk) -> None:
    client = ScriptedClient([answer("Hi.")])
    await run_question(client, build_server(helpdesk), "Hello")
    request = client.requests[0]
    assert request["output_config"] == {"effort": "medium"}
    assert request["fallbacks"] == "default"
    assert FALLBACK_BETA in request["betas"]
    assert {tool["name"] for tool in request["tools"]} == {
        "list_metrics",
        "describe_metric",
        "query_metrics",
        "compare_periods",
    }


async def test_refusal_is_reported_not_raised(helpdesk: HelpDesk) -> None:
    client = ScriptedClient([message([], "refusal")])
    result = await run_question(client, build_server(helpdesk), "Hello")
    assert result.refused


async def test_endless_tool_calls_stop_at_the_turn_limit(helpdesk: HelpDesk) -> None:
    client = ScriptedClient([tool_use("list_metrics", {}) for _ in range(3)])
    with pytest.raises(AskError, match="3 turns"):
        await run_question(client, build_server(helpdesk), "Loop", max_turns=3)


async def test_recording_client_keeps_every_response(helpdesk: HelpDesk) -> None:
    inner = ScriptedClient([tool_use("list_metrics", {}), answer("Done.")])
    recorder = RecordingClient(inner, "What metrics exist?", "claude-opus-5-5")
    await run_question(recorder, build_server(helpdesk), "What metrics exist?")
    assert [r["stop_reason"] for r in recorder.transcript.responses] == ["tool_use", "end_turn"]


async def test_bundled_replay_runs_against_the_demo(tmp_path: Path) -> None:
    paths = build_demo(tmp_path / "demo")
    transcript = Transcript.load(PROJECT_ROOT / "transcripts" / "july-dip.json")
    server = build_server(HelpDesk.open(paths.metrics_dir, paths.db_path))

    result = await run_question(ReplayClient(transcript), server, transcript.question)

    assert len(result.tool_calls) == 4
    assert not any(call.is_error for call in result.tool_calls)
    assert "Germany" in result.answer


def test_inline_refs_removes_definitions() -> None:
    schema = {
        "$defs": {"F": {"type": "object", "properties": {"v": {"type": "string"}}}},
        "properties": {"filters": {"type": "array", "items": {"$ref": "#/$defs/F"}}},
    }
    assert inline_refs(schema) == {
        "properties": {
            "filters": {
                "type": "array",
                "items": {"type": "object", "properties": {"v": {"type": "string"}}},
            }
        }
    }


def test_missing_credentials_are_detected() -> None:
    class NoCredentials:
        api_key = None
        auth_token = None
        credentials = None

    assert not has_credentials(NoCredentials())
