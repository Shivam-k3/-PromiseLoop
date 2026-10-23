"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import dispose_db, init_db
from app.routers import chat, commitments, dashboard, health, mcp_demo
from app.seed import ensure_seed_user

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_seed_user()
    yield
    await dispose_db()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="PromiseLoop - remember and fulfil the commitments you make.",
    lifespan=lifespan,
)
app.state.api_key_header = settings.api_key_header

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(commitments.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(mcp_demo.router, prefix=settings.api_prefix)
