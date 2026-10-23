"""Application settings, loaded from environment variables / .env."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "PromiseLoop API"
    environment: str = "dev"
    api_prefix: str = "/api"

    # Supabase Postgres in production, SQLite for local dev + tests.
    database_url: str = "sqlite+aiosqlite:///./promiseloop.db"
    db_echo: bool = False

    # NoDecode keeps the raw string so a comma separated value survives;
    # pydantic-settings would otherwise insist on a JSON array and fail.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    api_key_header: str = "x-api-key"
    seed_api_key: str = ""
    seed_user_email: str = "demo@promiseloop.local"

    # AI provider: "mock" (offline, deterministic), "gemini", or "openai"
    # (any OpenAI-compatible endpoint).
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 45.0

    # Gemini uses its OpenAI-compatible endpoint, so it shares the provider code.
    # GEMINI_API_KEY is read from the environment; it is never sent to the browser.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-3.5-flash-lite"

    # MCP
    mcp_server_command: str = ""
    mcp_transport: str = "memory"
    mcp_http_url: str = "http://127.0.0.1:8001/mcp"
    mcp_startup_timeout: float = 30.0

    default_timezone: str = "UTC"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
