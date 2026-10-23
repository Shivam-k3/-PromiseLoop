"""Shared test fixtures.

Environment variables are set *before* app.config is imported so the engine
binds to a throwaway SQLite file instead of the real database.
"""

import os
import pathlib
import tempfile

TEST_DB = pathlib.Path(tempfile.gettempdir()) / "promiseloop_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["SEED_API_KEY"] = "pl_seed_test_key"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MCP_TRANSPORT"] = "memory"
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, Commitment, CommitmentDependency, User  # noqa: E402
from app.security import hash_api_key  # noqa: E402

TEST_API_KEY = "pl_test_api_key"


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Create the schema and start every test with an empty database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        for model in (Activity, CommitmentDependency, Commitment, User):
            await session.execute(delete(model))
        await session.commit()
    yield
    # Closing the pool stops the aiosqlite worker threads so pytest can exit.
    await engine.dispose()


@pytest_asyncio.fixture
async def user(clean_db) -> User:
    async with AsyncSession(engine) as session:
        account = User(
            email="tester@promiseloop.local",
            display_name="Tester",
            api_key_hash=hash_api_key(TEST_API_KEY),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account


@pytest_asyncio.fixture
async def client(user) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        http_client.headers["X-API-Key"] = TEST_API_KEY
        yield http_client


@pytest_asyncio.fixture
async def anon_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
