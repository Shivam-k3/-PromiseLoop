"""Offline LLM provider.

PromiseLoop must work in a demo without an API key, and the AI has to go
through the same MCP tool loop it uses with a real model. This provider is a
deterministic planner: it reads the conversation, decides which MCP tool the
user meant, fills in the arguments with the rule based extractor and turns the
tool results into a short answer.
"""

import json
import re
from typing import Any

from app.llm.extraction import extract_commitment
from app.llm.provider import LLMResponse, ToolCall

COMPLETE_PATTERN = re.compile(
    r"\b(mark|complete|completed|finish|finished|done|tick off)\b", re.IGNORECASE
)
NEXT_PATTERN = re.compile(r"\b(next|priorit|focus|start with|do first)\b", re.IGNORECASE)
OVERDUE_PATTERN = re.compile(r"\b(overdue|late|missed|behind)\b", re.IGNORECASE)
LIST_PATTERN = re.compile(
    r"\b(list|show|what are my|what did i|my commitments|everything)\b", re.IGNORECASE
)


class MockProvider:
    """Rule based stand-in for a chat model."""

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        user_text = _last_user_text(messages)
        intent = self._intent(user_text)
        results = _tool_results(messages)

        if intent == "complete":
            if not results:
                return _call("list_commitments", {"status": "pending", "limit": 20})
            name, payload = results[-1]
            if name == "list_commitments":
                follow_up = self._complete_follow_up(payload, user_text)
                if follow_up is not None:
                    return follow_up
                return LLMResponse(
                    content="I could not find a matching commitment to complete."
                )
            return LLMResponse(content=_summarise(name, payload))

        if intent in {"next", "overdue", "list"}:
            if not results:
                return _call(*_query_for(intent))
            name, payload = results[-1]
            return LLMResponse(content=_summarise(name, payload))

        if intent == "create":
            if not results:
                extracted = extract_commitment(user_text)
                if extracted is None:
                    return LLMResponse(
                        content=(
                            "I could not find a promise in that. Try something like "
                            "\"I promised Abhishek that I'll send the demo by tomorrow evening\"."
                        )
                    )
                return _call("create_commitment", extracted.as_tool_arguments("UTC"))
            name, payload = results[-1]
            return LLMResponse(content=_summarise(name, payload))

        return LLMResponse(
            content=(
                "I can capture a promise, list what you are tracking, or tell you what to do "
                "next. Try: \"I promised Abhishek that I'll send the demo by tomorrow evening\"."
            )
        )

    async def structured(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], name: str = "result"
    ) -> dict[str, Any]:
        text = _last_user_text(messages)
        extracted = extract_commitment(text)
        if extracted is None:
            return {}
        return extracted.as_tool_arguments("UTC")

    # ------------------------------------------------------------------ #
    def _intent(self, text: str) -> str:
        lowered = text.lower()
        forward_looking = re.search(
            r"\b(?:need to|have to|must|going to)\b|i['’]?ll|\bi will\b", lowered
        )
        if (
            COMPLETE_PATTERN.search(lowered)
            and not re.search(r"\bpromis", lowered)
            and not forward_looking
        ):
            return "complete"
        if NEXT_PATTERN.search(lowered):
            return "next"
        if OVERDUE_PATTERN.search(lowered):
            return "overdue"
        if LIST_PATTERN.search(lowered):
            return "list"
        if extract_commitment(text) is not None:
            return "create"
        if re.search(r"\b(i promise|i'll|i will|i need to|remind me)\b", lowered):
            return "create"
        return "unknown"

    def _complete_follow_up(
        self, listed: dict[str, Any], user_text: str
    ) -> LLMResponse | None:
        """After listing commitments, pick the one the user means and complete it."""
        commitments = listed.get("commitments") or []
        if not commitments:
            return LLMResponse(content="There are no open commitments to complete.")

        wanted = _target_title(user_text)
        match = None
        for commitment in commitments:
            title = (commitment.get("title") or "").lower()
            if wanted and wanted in title:
                match = commitment
                break
        if match is None and len(commitments) == 1:
            match = commitments[0]
        if match is None:
            return LLMResponse(
                content=(
                    "Which one should I mark as done? I see: "
                    + ", ".join((item.get("title") or "") for item in commitments[:5])
                )
            )
        return _call("complete_commitment", {"id": match["id"]})


def _query_for(intent: str) -> tuple[str, dict[str, Any]]:
    if intent == "next":
        return "get_next_actions", {"limit": 5}
    if intent == "overdue":
        return "list_commitments", {"period": "overdue"}
    return "list_commitments", {"limit": 20}


def _call(name: str, arguments: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=f"mock_{name}", name=name, arguments=arguments)],
    )


def _summarise(name: str, payload: dict[str, Any]) -> str:
    if payload.get("status") == "awaiting_confirmation":
        return str(payload.get("question") or "Shall I save this commitment?")

    if name == "list_commitments":
        commitments = payload.get("commitments") or []
        if not commitments:
            return "You have no commitments matching that yet."
        titles = ", ".join((item.get("title") or "") for item in commitments[:5])
        more = "" if len(commitments) <= 5 else f" (+{len(commitments) - 5} more)"
        return f"You have {payload.get('count', len(commitments))} matching commitments: {titles}{more}."

    if name == "get_next_actions":
        actions = payload.get("next_actions") or []
        if not actions:
            return "Nothing is open right now - you are all caught up."
        first = actions[0]
        title = (first.get("commitment") or {}).get("title") or "your next task"
        reason = first.get("reason") or ""
        extra = f" Then {actions[1]['commitment']['title']}." if len(actions) > 1 else ""
        return f"Next up: {title} ({reason}).{extra}"

    if name == "complete_commitment":
        if payload.get("error"):
            return f"I could not complete that: {payload['error']}"
        return f"Done - \"{payload.get('title', 'the commitment')}\" is completed."

    if name == "update_commitment":
        if payload.get("error"):
            return f"I could not update that: {payload['error']}"
        return f"Updated \"{payload.get('title', 'the commitment')}\"."

    if name == "add_dependency":
        if payload.get("error"):
            return f"I could not link those: {payload['error']}"
        return f"Linked - \"{payload.get('title', 'it')}\" now waits on its prerequisite."

    if payload.get("error"):
        return f"That did not work: {payload['error']}"
    return "Done."


def _target_title(text: str) -> str:
    match = re.search(
        r"(?:mark|complete|finish|tick off)\s+(?:the\s+|my\s+)?(?P<title>.+)", text, re.IGNORECASE
    )
    if not match:
        return ""
    return match.group("title").strip().strip(".").lower()


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _tool_results(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    results: list[tuple[str, dict[str, Any]]] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            parsed = json.loads(message.get("content") or "{}")
        except (TypeError, ValueError):
            parsed = {}
        results.append((str(message.get("name") or ""), parsed if isinstance(parsed, dict) else {}))
    return results
