"""Renders the SQLAlchemy metadata to Postgres DDL for the Supabase SQL editor.

Run:  python -m app.schema_sql  >  migrations/001_init.sql
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base
from app import models  # noqa: F401  (register mappers)

DIALECT = postgresql.dialect()


def render() -> str:
    parts: list[str] = [
        "-- PromiseLoop schema (Supabase / PostgreSQL).",
        "-- Generated from app/models.py -- do not edit by hand.",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=DIALECT)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=DIALECT)).strip() + ";")
        parts.append("")

    parts.append(
        """
-- Row Level Security:
-- The backend connects with a privileged database role and enforces
-- authorisation in Python (every query is filtered by user_id). Add
-- policies before exposing these tables to PostgREST clients.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE commitment_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity ENABLE ROW LEVEL SECURITY;
"""
    )
    return "\n".join(parts)


if __name__ == "__main__":
    print(render())
