"""Conversational assistant endpoints (Alexa+ style web demo)."""

from fastapi import APIRouter, Depends, HTTPException

from app.deps import AuthContext, get_auth
from app.llm.agent import run_turn
from app.llm.provider import ProviderError, build_provider
from app.mcp_server.client import open_client
from app.schemas import ChatRequest, ChatResponse, ConfirmRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, auth: AuthContext = Depends(get_auth)) -> ChatResponse:
    try:
        provider = build_provider()
    except Exception as exc:  # pragma: no cover - misconfiguration
        raise HTTPException(status_code=503, detail=f"LLM provider unavailable: {exc}")

    try:
        result = await run_turn(
            messages=[message.model_dump() for message in payload.messages],
            api_key=auth.api_key,
            timezone=payload.timezone,
            provider=provider,
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"AI provider request failed ({exc.status_code}: {exc.category}). "
                "Check the provider key, model, quota and network. Nothing was saved."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Assistant request failed. Nothing was saved. Check the backend logs.",
        ) from exc
    return ChatResponse(
        reply=result.reply,
        confirmation=result.confirmation,
        tools_used=result.tools_used,
    )


@router.post("/confirm", response_model=dict)
async def confirm(payload: ConfirmRequest, auth: AuthContext = Depends(get_auth)) -> dict:
    """Persist a commitment the user confirmed in the chat."""
    arguments = {
        key: value for key, value in payload.draft.model_dump().items() if value is not None
    }
    try:
        async with open_client(auth.api_key) as client:
            result = await client.call_tool("create_commitment", arguments)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="MCP write failed. The commitment was not saved.",
        ) from exc
    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result
