"""The ask tool loop: Claude API on one side, the MCP server's tools on the other."""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from metric_helpdesk.ask.schemas import tool_definitions
from metric_helpdesk.server import INSTRUCTIONS

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AskError(RuntimeError):
    """Raised when the loop cannot produce an answer."""


class MessagesClient(Protocol):
    """The slice of ``AsyncAnthropic().beta.messages`` the loop uses; fakes implement it too."""

    async def create(self, **params: Any) -> Any: ...


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    is_error: bool


@dataclass
class AskResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    refused: bool = False


async def call_tool(server: MCPServer, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Run one tool; return (result text, is_error). Tool errors go back to the model as text."""
    try:
        result = await server.call_tool(name, arguments)
    except ToolError as error:
        return str(error), True
    texts = [block.text for block in getattr(result, "content", []) if block.type == "text"]
    return "\n".join(texts), bool(getattr(result, "is_error", False))


async def run_question(
    messages_client: MessagesClient,
    server: MCPServer,
    question: str,
    model: str = DEFAULT_MODEL,
    max_turns: int = 12,
) -> AskResult:
    """Ask one question, running tool calls until Claude answers.

    Args:
        messages_client: ``AsyncAnthropic().beta.messages`` or a recording/replaying stand-in.
        server: MCP server whose tools answer the questions.
        question: The user's question.
        model: Claude model ID.
        max_turns: Upper bound on API round trips.

    Raises:
        AskError: If Claude is still calling tools after ``max_turns``.
    """
    tools = await tool_definitions(server)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    calls: list[ToolCall] = []
    for _ in range(max_turns):
        response = await messages_client.create(
            model=model,
            max_tokens=16000,
            system=INSTRUCTIONS,
            tools=tools,
            messages=messages,
            output_config={"effort": "medium"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return AskResult(answer="Claude declined to answer this question.", refused=True)

        # Reason: append the content unchanged; editing earlier turns invalidates thinking.
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            text = "\n".join(block.text for block in response.content if block.type == "text")
            return AskResult(answer=text.strip(), tool_calls=calls)

        results = []
        for block in tool_uses:
            arguments = block.input if isinstance(block.input, dict) else json.loads(block.input)
            text, is_error = await call_tool(server, block.name, arguments)
            calls.append(ToolCall(block.name, arguments, is_error))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": text,
                    "is_error": is_error,
                }
            )
        # All results for one turn go back in a single user message.
        messages.append({"role": "user", "content": results})
    raise AskError(f"No answer after {max_turns} turns")
