"""The web demo must prove real MCP traffic over Streamable HTTP."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.mcp_server.client import open_client

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_API_KEY = "pl_test_api_key"

EXPECTED_TOOLS = {
    "create_commitment",
    "list_commitments",
    "update_commitment",
    "add_dependency",
    "get_next_actions",
    "complete_commitment",
}

PROMISE = "I promised Abhishek that I'll send him our project demo by tomorrow evening."


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"MCP HTTP server did not start on port {port}")


@pytest.fixture(scope="module")
def mcp_http_server():
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND_DIR),
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "LLM_PROVIDER": "mock",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp_server.server", "--http", "--port", str(port)],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    settings = get_settings()
    old_url = settings.mcp_http_url
    old_transport = settings.mcp_transport
    try:
        _wait_for_port(port)
        settings.mcp_http_url = f"http://127.0.0.1:{port}/mcp"
        settings.mcp_transport = "http"
        yield settings.mcp_http_url
    finally:
        settings.mcp_http_url = old_url
        settings.mcp_transport = old_transport
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


async def test_status_verifies_initialize_and_tools_list(
    client: AsyncClient, mcp_http_server: str
) -> None:
    response = await client.get("/api/mcp/status")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["transport"] == "streamable-http"
    assert body["endpoint"] == mcp_http_server
    assert body["connected"] is True
    assert body["protocol_version"] == "2025-11-25"
    assert body["server_name"] == "promiseloop"
    assert body["chat_transport"] == "http"
    assert {tool["name"] for tool in body["tools"]} == EXPECTED_TOOLS


async def test_read_runs_a_tools_call_over_http(
    client: AsyncClient, mcp_http_server: str
) -> None:
    created = await client.post(
        "/api/commitments", json={"title": "HTTP read", "timezone": "UTC"}
    )
    assert created.status_code == 201, created.text

    response = await client.post("/api/mcp/read")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["tool"] == "list_commitments"
    assert body["protocol_version"] == "2025-11-25"
    assert body["server_name"] == "promiseloop"
    assert body["result"]["count"] == 1
    assert body["result"]["commitments"][0]["title"] == "HTTP read"

    listed = (await client.get("/api/commitments")).json()
    assert len(listed) == 1


async def test_chat_workflow_uses_http_and_waits_for_confirmation(
    client: AsyncClient, mcp_http_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.mcp_server import client as mcp_client_module

    def forbidden(*args, **kwargs):
        raise AssertionError("memory MCP transport was used")

    monkeypatch.setattr(
        mcp_client_module, "create_connected_server_and_client_session", forbidden
    )

    response = await client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": PROMISE}], "timezone": "UTC"},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["confirmation"] is not None
    assert "create_commitment" not in body["tools_used"]
    assert (await client.get("/api/commitments")).json() == []

    confirmed = await client.post(
        "/api/chat/confirm", json={"draft": body["confirmation"]["draft"]}
    )
    assert confirmed.status_code == 200, confirmed.text

    rows = (await client.get("/api/commitments")).json()
    assert len(rows) == 1
    assert rows[0]["recipient"] == "Abhishek"


async def test_all_six_tools_run_over_streamable_http(
    client: AsyncClient, mcp_http_server: str
) -> None:
    async with open_client(TEST_API_KEY, transport="http") as mcp:
        first = await mcp.call_tool(
            "create_commitment", {"title": "HTTP tool one", "timezone": "UTC"}
        )
        second = await mcp.call_tool(
            "create_commitment", {"title": "HTTP tool two", "timezone": "UTC"}
        )
        updated = await mcp.call_tool(
            "update_commitment", {"id": first["id"], "priority": "high"}
        )
        linked = await mcp.call_tool(
            "add_dependency",
            {"commitment_id": second["id"], "depends_on_id": first["id"]},
        )
        actions = await mcp.call_tool("get_next_actions", {"limit": 5})
        completed = await mcp.call_tool("complete_commitment", {"id": first["id"]})
        listed = await mcp.call_tool("list_commitments", {})

    assert first["status"] == "pending"
    assert second["status"] == "pending"
    assert updated["priority"] == "high"
    assert linked["blocked_by"] == [first["id"]]
    assert any(action["commitment"]["title"] == "HTTP tool two" for action in actions["next_actions"])
    assert completed["status"] == "completed"
    assert listed["count"] == 2


async def test_http_tool_call_rejects_an_unknown_key(mcp_http_server: str) -> None:
    async with open_client("not-a-real-key", transport="http") as mcp:
        result = await mcp.call_tool("list_commitments", {})
    assert "error" in result


async def test_demo_endpoints_require_authentication(
    anon_client: AsyncClient, mcp_http_server: str
) -> None:
    assert (await anon_client.get("/api/mcp/status")).status_code == 401
    assert (await anon_client.post("/api/mcp/read")).status_code == 401
