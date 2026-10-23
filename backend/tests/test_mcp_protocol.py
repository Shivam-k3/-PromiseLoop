"""Protocol checks for MCP spec 2025-11-25 over Streamable HTTP."""

import json

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from starlette.testclient import TestClient

from app.mcp_server.client import open_client
from app.mcp_server.server import ApiKeyMiddleware, build_server

TEST_API_KEY = "pl_test_api_key"

EXPECTED_TOOLS = {
    "create_commitment",
    "list_commitments",
    "update_commitment",
    "add_dependency",
    "get_next_actions",
    "complete_commitment",
}


def _sse_json(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no SSE data in response: {body!r}")


async def test_initialize_negotiates_spec_2025_11_25():
    server = build_server()._mcp_server
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )
            async with ClientSession(client_read, client_write) as session:
                result = await session.initialize()
                assert result.protocolVersion == "2025-11-25"
                assert result.serverInfo.name == "promiseloop"
            tg.cancel_scope.cancel()


def test_streamable_http_negotiates_2025_11_25_and_lists_tools():
    app = ApiKeyMiddleware(build_server().streamable_http_app())
    headers = {
        "Accept": "application/json, text/event-stream",
        "X-API-Key": TEST_API_KEY,
    }
    with TestClient(app, base_url="http://127.0.0.1:8000") as http:
        initialized = http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
            headers=headers,
        )
        assert initialized.status_code == 200, initialized.text
        result = _sse_json(initialized.text)["result"]
        assert result["protocolVersion"] == "2025-11-25"
        assert result["serverInfo"]["name"] == "promiseloop"

        session_headers = {
            **headers,
            "mcp-session-id": initialized.headers["mcp-session-id"],
            "mcp-protocol-version": "2025-11-25",
        }
        http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=session_headers,
        )
        listed = http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=session_headers,
        )
        assert listed.status_code == 200, listed.text
        tools = {tool["name"] for tool in _sse_json(listed.text)["result"]["tools"]}

    assert tools == EXPECTED_TOOLS


async def test_read_only_tools_do_not_write(client, user):
    async with open_client(TEST_API_KEY) as mcp:
        listed = await mcp.call_tool("list_commitments", {})
        assert listed["count"] == 0
        assert listed["commitments"] == []

        actions = await mcp.call_tool("get_next_actions", {})
        assert actions["count"] == 0
        assert actions["next_actions"] == []

    assert (await client.get("/api/commitments")).json() == []


async def test_empty_api_key_is_refused(user):
    async with open_client("") as mcp:
        result = await mcp.call_tool("list_commitments", {})
        assert "error" in result
