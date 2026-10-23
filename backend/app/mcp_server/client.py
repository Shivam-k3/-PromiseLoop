"""Client side of the MCP integration.

The assistant never calls the service layer directly: it goes through a real
MCP session, so the tool schemas, the validation and the authorisation all
live in the MCP server.

Transports:

* ``memory``  - in-process, using the SDK's in-memory transport (default)
* ``http``    - streamable HTTP against a separately running MCP server
* ``stdio``   - spawn ``python -m app.mcp_server.server`` as a subprocess
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from app.config import get_settings
from app.mcp_server.auth import current_api_key


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert an MCP tool definition into an OpenAI-style function tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class McpClient:
    """Thin wrapper around a live ``ClientSession``."""

    def __init__(
        self,
        session: ClientSession,
        protocol_version: str | None = None,
        server_name: str | None = None,
    ) -> None:
        self._session = session
        self.protocol_version = protocol_version
        self.server_name = server_name

    async def list_tools(self) -> list[McpTool]:
        result = await self._session.list_tools()
        return [
            McpTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {"type": "object", "properties": {}},
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, arguments)
        if result.isError:
            text = _text_of(result.content)
            return {"error": text or f"{name} failed"}
        return _normalise(result)


def _text_of(content) -> str:
    return "".join(getattr(block, "text", "") for block in content or [])


def _normalise(result) -> dict[str, Any]:
    """Unwrap the different shapes FastMCP can return."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    text = _text_of(result.content)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"result": text}
    if isinstance(parsed, dict) and set(parsed) == {"result"} and isinstance(parsed["result"], dict):
        return parsed["result"]
    return parsed if isinstance(parsed, dict) else {"result": parsed}


@asynccontextmanager
async def open_client(api_key: str, transport: str | None = None) -> AsyncIterator[McpClient]:
    """Open an MCP session as the given API key."""
    settings = get_settings()
    mode = (transport or settings.mcp_transport or "memory").lower()

    if mode in ("memory", "inprocess", "in_process"):
        from app.mcp_server.server import build_server

        token = current_api_key.set(api_key)
        try:
            async with create_connected_server_and_client_session(build_server()) as session:
                yield McpClient(session)
        finally:
            current_api_key.reset(token)
        return

    if mode == "http":
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(
            settings.mcp_http_url, headers={"X-API-Key": api_key}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                yield McpClient(
                    session,
                    protocol_version=initialized.protocolVersion,
                    server_name=initialized.serverInfo.name,
                )
        return

    if mode == "stdio":
        command = settings.mcp_server_command
        # MCP_SERVER_COMMAND may be a bare executable or a full command line.
        parts = command.split() if command else [sys.executable, "-m", "app.mcp_server.server"]
        env = {**os.environ, "PL_API_KEY": api_key, "PYTHONPATH": os.getcwd()}
        params = StdioServerParameters(command=parts[0], args=parts[1:], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                yield McpClient(
                    session,
                    protocol_version=initialized.protocolVersion,
                    server_name=initialized.serverInfo.name,
                )
        return

    raise ValueError(f"Unknown MCP transport: {mode}")
