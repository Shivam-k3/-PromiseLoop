"""Dependency tracking: blocking, unblocking, cycle rejection."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine
from app.models import Commitment, CommitmentDependency

BASE = {"title": "Task", "timezone": "UTC"}


async def create(client: AsyncClient, title: str) -> dict:
    response = await client.post("/api/commitments", json={**BASE, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


async def test_dependency_marks_the_dependent_as_blocked(client: AsyncClient):
    first = await create(client, "Draft slides")
    second = await create(client, "Send slides")

    response = await client.post(
        f"/api/commitments/{second['id']}/dependencies",
        json={"depends_on_id": first["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["depends_on_ids"] == [first["id"]]
    assert body["blocked_by"] == [first["id"]]


async def test_completing_the_prerequisite_unblocks_the_dependent(client: AsyncClient):
    first = await create(client, "Draft slides")
    second = await create(client, "Send slides")
    await client.post(
        f"/api/commitments/{second['id']}/dependencies", json={"depends_on_id": first["id"]}
    )

    await client.post(f"/api/commitments/{first['id']}/complete")

    refreshed = (await client.get(f"/api/commitments/{second['id']}")).json()
    assert refreshed["blocked_by"] == []
    assert refreshed["depends_on_ids"] == [first["id"]]


async def test_blocking_is_transitive(client: AsyncClient):
    a = await create(client, "A")
    b = await create(client, "B")
    c = await create(client, "C")
    await client.post(f"/api/commitments/{b['id']}/dependencies", json={"depends_on_id": a["id"]})
    await client.post(f"/api/commitments/{c['id']}/dependencies", json={"depends_on_id": b["id"]})

    refreshed = (await client.get(f"/api/commitments/{c['id']}")).json()
    assert set(refreshed["blocked_by"]) == {a["id"], b["id"]}


async def test_circular_dependency_is_rejected(client: AsyncClient):
    a = await create(client, "A")
    b = await create(client, "B")
    await client.post(f"/api/commitments/{b['id']}/dependencies", json={"depends_on_id": a["id"]})

    response = await client.post(
        f"/api/commitments/{a['id']}/dependencies", json={"depends_on_id": b["id"]}
    )
    assert response.status_code == 409
    assert "circular" in response.json()["detail"].lower()


async def test_self_dependency_is_rejected(client: AsyncClient):
    a = await create(client, "A")
    response = await client.post(
        f"/api/commitments/{a['id']}/dependencies", json={"depends_on_id": a["id"]}
    )
    assert response.status_code == 409


async def test_dependency_on_missing_commitment_returns_404(client: AsyncClient):
    a = await create(client, "A")
    response = await client.post(
        f"/api/commitments/{a['id']}/dependencies",
        json={"depends_on_id": "22222222-2222-2222-2222-222222222222"},
    )
    assert response.status_code == 404


async def test_dependency_can_be_removed(client: AsyncClient):
    a = await create(client, "A")
    b = await create(client, "B")
    await client.post(f"/api/commitments/{b['id']}/dependencies", json={"depends_on_id": a["id"]})

    response = await client.delete(f"/api/commitments/{b['id']}/dependencies/{a['id']}")
    assert response.status_code == 200
    assert response.json()["depends_on_ids"] == []


async def test_commitments_and_dependencies_survive_database_pool_restart(client: AsyncClient):
    prerequisite = await create(client, "Draft slides")
    dependent = await create(client, "Send slides")
    linked = await client.post(
        f"/api/commitments/{dependent['id']}/dependencies",
        json={"depends_on_id": prerequisite["id"]},
    )
    assert linked.status_code == 200, linked.text

    # A new connection after disposal models the server reopening its database
    # connection pool. The file-backed SQLite test database keeps committed rows.
    await engine.dispose()

    refreshed = await client.get(f"/api/commitments/{dependent['id']}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["depends_on_ids"] == [prerequisite["id"]]

    async with AsyncSession(engine) as session:
        stored_commitment = await session.get(Commitment, uuid.UUID(dependent["id"]))
        stored_dependency = await session.scalar(
            select(CommitmentDependency).where(
                CommitmentDependency.commitment_id == uuid.UUID(dependent["id"]),
                CommitmentDependency.depends_on_id == uuid.UUID(prerequisite["id"]),
            )
        )
    assert stored_commitment is not None
    assert stored_dependency is not None


async def test_dashboard_reports_blocked_commitments(client: AsyncClient):
    a = await create(client, "A")
    b = await create(client, "B")
    await client.post(f"/api/commitments/{b['id']}/dependencies", json={"depends_on_id": a["id"]})

    body = (await client.get("/api/dashboard")).json()
    assert body["counts"]["blocked"] == 1
    assert body["blocked"][0]["title"] == "B"
