from contextlib import asynccontextmanager

from app.llm.agent import _stage_write, run_turn
from app.llm.provider import LLMResponse, ToolCall


class FakeTool:
    def to_openai_tool(self):
        return {"type": "function", "function": {"name": "list_commitments"}}

class FakeClient:
    async def list_tools(self):
        return [FakeTool()]

    async def call_tool(self, name, arguments):
        return {"ok": True}


@asynccontextmanager
async def fake_open_client(api_key):
    yield FakeClient()


class FakeProvider:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="list_commitments",
                        arguments={},
                        extra_content={"google": {"thought_signature": "signature"}},
                    )
                ]
            )
        return LLMResponse(content="Done")


async def test_run_turn_preserves_tool_metadata(monkeypatch):
    monkeypatch.setattr("app.llm.agent.open_client", fake_open_client)
    provider = FakeProvider()

    result = await run_turn(
        [{"role": "user", "content": "what is next?"}], "key", "UTC", provider
    )

    assert result.reply == "Done"
    assistant = provider.calls[1][2]
    assert assistant["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature"}
    }


def test_stage_write_cleans_model_wording():
    _, confirmation = _stage_write(
        ToolCall(
            id="call_1",
            name="create_commitment",
            arguments={
                "title": "I'll send ₹2,000 to my sister",
                "recipient": "my sister",
                "due_text": "tomorrow",
            },
        ),
        "UTC",
    )

    draft = confirmation["draft"]
    assert draft["title"] == "Send ₹2,000 to my sister"
    assert draft["recipient"] == "sister"
