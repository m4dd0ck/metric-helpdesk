"""Claude API tool definitions derived from the MCP server, so both front ends share one source."""

from typing import Any

from mcp.server.mcpserver import MCPServer


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace local ``$ref`` pointers with the definitions they name and drop ``$defs``."""
    definitions: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(definitions[ref.removeprefix("#/$defs/")])
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


async def tool_definitions(server: MCPServer) -> list[dict[str, Any]]:
    """Every MCP tool as a Claude API tool definition."""
    return [
        {
            "name": tool.name,
            "description": tool.description or tool.name,
            "input_schema": inline_refs(tool.input_schema),
        }
        for tool in await server.list_tools()
    ]
