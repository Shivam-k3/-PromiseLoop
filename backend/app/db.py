"""Async SQLAlchemy engine, session factory and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.engine import URL, make_url

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def _async_database_url(database_url: str) -> tuple[URL, dict[str, object]]:
    """Prepare common Supabase connection strings for SQLAlchemy's asyncpg driver.

    Supabase's dashboard gives a ``postgresql://`` URI, while this application
    uses SQLAlchemy's async engine. Translate the scheme and pass SSL settings
    using asyncpg's connection arguments.
    """
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")

    connect_args: dict[str, object] = {}
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = "require" if sslmode == "require" else True
    if query != dict(url.query):
        url = url.set(query=query)
    return url, connect_args

if settings.is_sqlite:
    _database_url = make_url(settings.database_url)
    _connect_args: dict[str, object] = {"check_same_thread": False}
else:
    _database_url, _connect_args = _async_database_url(settings.database_url)


engine = create_async_engine(
    _database_url,
    echo=settings.db_echo,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()
