"""Settings parsing and the demo user bootstrap."""

from app.config import Settings
from app.db import _async_database_url
from app.seed import ensure_seed_user


def test_cors_origins_accept_a_comma_separated_string(monkeypatch):
    """A plain .env value must not blow up the settings loader."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_also_accept_a_json_array(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173"]')
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:5173"]


def test_database_url_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.is_sqlite


def test_supabase_dashboard_url_uses_asyncpg_and_requires_ssl():
    url, connect_args = _async_database_url(
        "postgresql://postgres:secret@db.example.supabase.co:5432/postgres?sslmode=require"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db.example.supabase.co"
    assert url.password == "secret"
    assert "sslmode" not in url.query
    assert connect_args == {"ssl": "require"}


def test_supabase_asyncpg_url_is_left_as_asyncpg():
    url, connect_args = _async_database_url(
        "postgresql+asyncpg://postgres:secret@db.example.supabase.co:5432/postgres"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert connect_args == {}


async def test_seed_user_is_created_once():
    first = await ensure_seed_user()
    second = await ensure_seed_user()
    assert first is not None
    assert first.email == second.email
    assert first.api_key_hash == second.api_key_hash
