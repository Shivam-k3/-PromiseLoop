"""Visible Streamable HTTP MCP demo endpoints.

These endpoints are the web simulator's MCP client: every request opens a real
MCP session over Streamable HTTP, then runs initialize, tools/list or tools/call.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.deps import AuthContext, get_auth
from app.mcp_server.client import open_client

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/status")
async def mcp_status(auth: AuthContext = Depends(get_auth)) -> dict:
    settings = get_settings()
    try:
        async with open_client(auth.api_key, transport="http") as client:
            tools = await client.list_tools()
            protocol_version = client.protocol_version
            server_name = client.server_name
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Streamable HTTP MCP server unavailable at {settings.mcp_http_url}: {exc}",
        ) from exc

    return {
        "transport": "streamable-http",
        "endpoint": settings.mcp_http_url,
        "connected": True,
        "protocol_version": protocol_version,
        "server_name": server_name,
        "chat_transport": settings.mcp_transport,
        "tools": [
            {"name": tool.name, "description": tool.description} for tool in tools
        ],
    }


@router.post("/read")
async def mcp_read(auth: AuthContext = Depends(get_auth)) -> dict:
    try:
        async with open_client(auth.api_key, transport="http") as client:
            result = await client.call_tool("list_commitments", {})
            protocol_version = client.protocol_version
            server_name = client.server_name
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Streamable HTTP MCP server unavailable: {exc}",
        ) from exc

    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return {
        "tool": "list_commitments",
        "protocol_version": protocol_version,
        "server_name": server_name,
        "result": result,
    }
