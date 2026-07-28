"""FastAPI application factory with explicit resource ownership."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from starlette.types import ASGIApp

from bot_ofertas.api.errors import RequestIdMiddleware, install_exception_handlers
from bot_ofertas.api.routes import api_router, public_router
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
)
from bot_ofertas.stores import StoreRegistry, get_store_registry

SessionFactory = Callable[[], Session]


def create_app(
    api_settings: ApiSettings | None = None,
    *,
    engine: Engine | None = None,
    session_factory: SessionFactory | None = None,
    registry: StoreRegistry | None = None,
) -> ASGIApp:
    """Build the ASGI graph and dispose only resources created by this factory."""

    settings = api_settings or ApiSettings.from_env()
    owns_engine = engine is None and session_factory is None
    resolved_engine = engine
    if session_factory is None:
        resolved_engine = resolved_engine or create_database_engine()
        resolved_session_factory: SessionFactory = create_session_factory(resolved_engine)
    else:
        resolved_session_factory = session_factory

    resolved_registry = registry or get_store_registry()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_engine and resolved_engine is not None:
                resolved_engine.dispose()

    docs_url = "/docs" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    fastapi_app = FastAPI(
        title="Bot Ofertas API",
        description=("Administración local del monitor responsable de precios públicos en Perú."),
        version="1.0.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    fastapi_app.state.api_settings = settings
    fastapi_app.state.engine = resolved_engine
    fastapi_app.state.session_factory = resolved_session_factory
    fastapi_app.state.store_registry = resolved_registry

    install_exception_handlers(fastapi_app)
    fastapi_app.include_router(public_router)
    fastapi_app.include_router(api_router)

    cors_app: ASGIApp = CORSMiddleware(
        app=fastapi_app,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Change-Reason",
            "X-Request-ID",
        ],
        expose_headers=[
            "ETag",
            "Location",
            "X-Idempotent-Replay",
            "X-Request-ID",
        ],
        max_age=600,
    )
    return RequestIdMiddleware(cors_app)


__all__ = ["create_app"]
