"""The conversational flow: extract -> confirm -> save, and factual answers."""

import pytest
from httpx import AsyncClient

from app.llm.provider import ProviderError

PROMISE = "I promised Abhishek that I'll send him our project demo by tomorrow evening."


async def test_promise_is_extracted_and_awaiting_confirmation(client: AsyncClient):
    response = await client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": PROMISE}], "timezone": "UTC"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["confirmation"] is not None
    assert "create_commitment" not in body["tools_used"]
    draft = body["confirmation"]["draft"]
    assert "Abhishek" in draft["title"]
    assert draft["recipient"] == "Abhishek"
    assert draft["due_at"] is not None
    assert draft["timezone"] == "UTC"

    # Nothing is written before the user confirms.
    listed = (await client.get("/api/commitments")).json()
    assert listed == []


async def test_missing_deadline_is_asked_before_saving(client: AsyncClient):
    response = await client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "I promise to send money to my sister."}
            ],
            "timezone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["confirmation"] is not None
    draft = body["confirmation"]["draft"]
    assert draft["title"] == "Send money to my sister"
    assert draft["recipient"] == "sister"
    assert draft["due_at"] is None
    assert "deadline" in body["confirmation"]["question"].lower()
    assert (await client.get("/api/commitments")).json() == []


async def test_amount_and_deadline_are_preserved(client: AsyncClient):
    response = await client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "I'll send ₹2,000 to my sister tomorrow."}
            ],
            "timezone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()["confirmation"]["draft"]
    assert "2,000" in draft["title"]
    assert draft["recipient"] == "sister"
    assert draft["due_at"] is not None
    assert (await client.get("/api/commitments")).json() == []


async def test_told_recipient_is_preserved(client: AsyncClient):
    response = await client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "I told Abhishek I'll send the project demo tomorrow evening.",
                }
            ],
            "timezone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()["confirmation"]["draft"]
    assert draft["recipient"] == "Abhishek"
    assert draft["due_at"] is not None
    assert (await client.get("/api/commitments")).json() == []


async def test_ambiguous_weekday_asks_for_clarification(client: AsyncClient):
    response = await client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "I need to finish my report by Friday."}],
            "timezone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200, response.text
    confirmation = response.json()["confirmation"]
    assert confirmation is not None
    assert confirmation["draft"]["title"] == "Finish my report"
    assert "Friday" in confirmation["question"]
    assert (await client.get("/api/commitments")).json() == []


async def test_unrelated_question_does_not_create_a_draft(client: AsyncClient):
    response = await client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "What's the weather like today?"}],
            "timezone": "UTC",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmation"] is None
    assert body["tools_used"] == []
    assert (await client.get("/api/commitments")).json() == []


async def test_provider_failure_is_sanitized_and_writes_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def failing_turn(*args, **kwargs):
        raise ProviderError(429, "rate limit or quota")

    monkeypatch.setattr("app.routers.chat.run_turn", failing_turn)
    response = await client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": PROMISE}]}
    )
    assert response.status_code == 502, response.text
    assert "rate limit or quota" in response.json()["detail"]
    assert "test-key" not in response.text
    assert (await client.get("/api/commitments")).json() == []


async def test_confirming_saves_the_commitment(client: AsyncClient):
    reply = await client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": PROMISE}], "timezone": "UTC"}
    )
    draft = reply.json()["confirmation"]["draft"]

    confirmed = await client.post("/api/chat/confirm", json={"draft": draft})
    assert confirmed.status_code == 200, confirmed.text
    created = confirmed.json()
    assert created["recipient"] == "Abhishek"
    assert created["status"] == "pending"

    listed = (await client.get("/api/commitments")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


async def test_answer_uses_the_database_not_invention(client: AsyncClient):
    await client.post(
        "/api/commitments",
        json={
            "title": "Send the invoice",
            "recipient": "Abhishek",
            "due_at": "2020-01-01T00:00:00+00:00",
            "timezone": "UTC",
        },
    )

    response = await client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "What should I do next?"}], "timezone": "UTC"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "get_next_actions" in body["tools_used"]
    assert "Send the invoice" in body["reply"]


async def test_listing_uses_the_list_tool(client: AsyncClient):
    await client.post("/api/commitments", json={"title": "Call Priya", "timezone": "UTC"})
    response = await client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "List my commitments"}], "timezone": "UTC"},
    )
    body = response.json()
    assert "list_commitments" in body["tools_used"]
    assert "Call Priya" in body["reply"]


async def test_completing_through_the_assistant(client: AsyncClient):
    created = (
        await client.post("/api/commitments", json={"title": "Draft slides", "timezone": "UTC"})
    ).json()

    response = await client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Mark Draft slides as done"}],
            "timezone": "UTC",
        },
    )
    body = response.json()
    assert "complete_commitment" in body["tools_used"]

    refreshed = (await client.get(f"/api/commitments/{created['id']}")).json()
    assert refreshed["status"] == "completed"


async def test_chat_requires_authentication(anon_client: AsyncClient):
    response = await anon_client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": PROMISE}]}
    )
    assert response.status_code == 401
