"""The assistant loop.

LLM -> MCP tool -> LLM -> reply. The tool list comes from the MCP server, the
arguments are validated by the MCP server, and every read hits the real
database. Creating a commitment is the one gated action: the assistant proposes
it and the user has to confirm before the MCP tool actually writes anything.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.provider import LLMProvider, ToolCall
from app.mcp_server.client import open_client
from app.services.timeparse import parse_deadline

MAX_TURNS = 6

# Tools that need an explicit "yes" from the user before they write.
GATED_TOOLS = {"create_commitment"}

SYSTEM_PROMPT = """You are PromiseLoop, an assistant that remembers the commitments \
a person makes to other people and to themselves.

Rules:
- Read real records with the tools. Never invent commitments, dates, counts or ids.
- Only call `create_commitment` when the user is stating a real promise or task they \
intend to keep. Do not call it for hypotheticals, examples, quoted text, or unrelated \
questions.
- To capture a new promise call `create_commitment` with a short title, the recipient \
when stated, and the deadline as natural language in `due_text` (for example "tomorrow \
evening"). A personal task can have no recipient.
- Keep the user's own wording in the title, including possessives: "Finish my report", \
not "Finish report".
- Never invent an amount, recipient, deadline or dependency. Leave missing details out \
and ask for them when you present the confirmation.
- A `create_commitment` proposal is not saved yet: the tool answers \
`awaiting_confirmation`. When that happens, ask the user to confirm and repeat exactly \
what you captured (task, who, when).
- If the user asks an unrelated question, answer briefly and do not call a tool.
- The user's timezone is {timezone}. Give deadlines in that timezone and prefer \
`due_text` over computing timestamps yourself.
- Keep replies short, warm and concrete. No lists of every tool you called.
"""


@dataclass
class AgentResult:
    reply: str
    confirmation: dict[str, Any] | None = None
    tools_used: list[str] = field(default_factory=list)


async def run_turn(
    messages: list[dict[str, Any]],
    api_key: str,
    timezone: str,
    provider: LLMProvider,
) -> AgentResult:
    """Run one conversational turn."""
    async with open_client(api_key) as client:
        tools = await client.list_tools()
        tool_schemas = [tool.to_openai_tool() for tool in tools]

        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(timezone=timezone)}
        ]
        conversation.extend(_normalise_messages(messages))

        tools_used: list[str] = []
        confirmation: dict[str, Any] | None = None

        for _turn in range(MAX_TURNS):
            response = await provider.chat(conversation, tool_schemas)

            if not response.tool_calls:
                return AgentResult(
                    reply=response.content or "",
                    confirmation=confirmation,
                    tools_used=tools_used,
                )

            tool_calls = []
            for call in response.tool_calls:
                tool_call = {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                if call.extra_content:
                    tool_call["extra_content"] = call.extra_content
                tool_calls.append(tool_call)
            conversation.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_calls,
                }
            )

            for call in response.tool_calls:
                if call.name in GATED_TOOLS:
                    # A write is never executed on the model's say-so alone.
                    if confirmation is None:
                        result, confirmation = _stage_write(call, timezone)
                    else:
                        result = {
                            "status": "awaiting_confirmation",
                            "question": confirmation["question"],
                            "commitment": confirmation["draft"],
                        }
                else:
                    result = await client.call_tool(call.name, call.arguments)
                    tools_used.append(call.name)
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result, default=str),
                    }
                )

        return AgentResult(
            reply="I lost track of that one - could you say it again?",
            confirmation=confirmation,
            tools_used=tools_used,
        )


def _normalise_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            normalised.append({"role": role, "content": content})
    return normalised


def _stage_write(call: ToolCall, timezone: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn a create_commitment call into a proposal the user has to confirm."""
    arguments = {key: value for key, value in call.arguments.items() if value is not None}
    arguments["timezone"] = timezone

    title = str(arguments.get("title") or "").strip()
    title = re.sub(
        r"^(?:i['’]?ll|i will|i promised?(?: to)?|i need to|i have to|i must)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    if title:
        title = title[0].upper() + title[1:]
    arguments["title"] = title

    recipient = arguments.get("recipient")
    if isinstance(recipient, str):
        arguments["recipient"] = re.sub(
            r"^(?:my|our|the)\s+", "", recipient.strip(), flags=re.IGNORECASE
        ) or None

    deadline = None
    if arguments.get("due_text") and not arguments.get("due_at"):
        deadline = parse_deadline(str(arguments["due_text"]), timezone)
        if deadline is not None:
            arguments["due_at"] = deadline.as_utc(timezone).isoformat()
            arguments["due_local_date"] = deadline.date.isoformat()
            arguments["due_local_time"] = deadline.time.isoformat() if deadline.time else None
            arguments["deadline_precision"] = deadline.precision

    draft = {
        "title": arguments.get("title", ""),
        "recipient": arguments.get("recipient"),
        "details": arguments.get("details"),
        "due_at": arguments.get("due_at"),
        "due_local_date": arguments.get("due_local_date"),
        "due_local_time": arguments.get("due_local_time"),
        "deadline_precision": arguments.get("deadline_precision", "none"),
        "timezone": timezone,
        "priority": arguments.get("priority", "normal"),
        "source": arguments.get("source", "chat"),
        "original_text": arguments.get("original_text"),
    }

    question = _confirmation_question(draft, deadline)
    confirmation = {
        "kind": "create_commitment",
        "question": question,
        "draft": draft,
    }
    result = {"status": "awaiting_confirmation", "commitment": draft, "question": question}
    return result, confirmation


def _confirmation_question(draft: dict[str, Any], deadline) -> str:
    if deadline is not None and deadline.ambiguous:
        return deadline.question or "Which date did you mean?"
    if not draft.get("recipient"):
        return "Shall I save this for you? (no recipient was mentioned)"
    if not draft.get("due_at"):
        return "Shall I save this? There is no deadline yet - want to add one?"
    return "Shall I save this commitment?"
