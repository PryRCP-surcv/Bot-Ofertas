"""Uniform Problem Details responses and request correlation for the HTTP API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bot_ofertas.api.cursors import CursorError
from bot_ofertas.api.service import (
    CrawlJobNotFoundError,
    InvalidCommercialRequestError,
    InvalidCrawlJobRequestError,
    InvalidDiscoveryRequestError,
    InvalidRuntimePolicyError,
    LaunchChecklistItemNotFoundError,
    ProductNotFoundError,
    SubscriberNotFoundError,
    UnsafeProductConfigurationError,
)
from bot_ofertas.storage.admin import (
    IdempotencyConflictError,
    OptimisticConcurrencyError,
)
from bot_ofertas.stores import StoreRegistryError

logger = logging.getLogger(__name__)

_REQUEST_ID_HEADER = b"x-request-id"
_PROBLEM_MEDIA_TYPE = "application/problem+json"


class RequestIdMiddleware:
    """Assign an opaque request identifier and expose it on every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        state = dict(scope.get("state") or {})
        state["request_id"] = request_id
        scope["state"] = state

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != _REQUEST_ID_HEADER
                ]
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else uuid4().hex


def _title(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def problem_response(
    request: Request,
    *,
    status_code: int,
    detail: str,
    title: str | None = None,
    type_uri: str = "about:blank",
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build an RFC 9457-compatible response without exposing internal state."""

    request_id = _request_id(request)
    body: dict[str, Any] = {
        "type": type_uri,
        "title": title or _title(status_code),
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id,
    }
    if extensions:
        body.update(extensions)
    return JSONResponse(
        body,
        status_code=status_code,
        headers=headers,
        media_type=_PROBLEM_MEDIA_TYPE,
    )


async def _http_exception_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    detail = error.detail if isinstance(error.detail, str) else "La solicitud no pudo procesarse."
    return problem_response(
        request,
        status_code=error.status_code,
        detail=detail,
        headers=dict(error.headers or {}),
    )


async def _validation_exception_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    invalid_fields = sorted(
        {
            ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            for item in error.errors()
        }
        - {""}
    )
    return problem_response(
        request,
        status_code=422,
        title="Solicitud inválida",
        detail="Uno o más parámetros no cumplen el contrato de la API.",
        type_uri="urn:bot-ofertas:problem:validation",
        extensions={"invalid_fields": invalid_fields},
    )


async def _cursor_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, CursorError)
    return problem_response(
        request,
        status_code=400,
        title="Cursor inválido",
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:invalid-cursor",
    )


async def _product_not_found_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, ProductNotFoundError)
    return problem_response(
        request,
        status_code=404,
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:product-not-found",
    )


async def _crawl_job_not_found_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, CrawlJobNotFoundError)
    return problem_response(
        request,
        status_code=404,
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:crawl-job-not-found",
    )


async def _commercial_not_found_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(
        error,
        (SubscriberNotFoundError, LaunchChecklistItemNotFoundError),
    )
    return problem_response(
        request,
        status_code=404,
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:commercial-resource-not-found",
    )


async def _unsafe_product_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, (UnsafeProductConfigurationError, StoreRegistryError))
    return problem_response(
        request,
        status_code=422,
        title="Configuración de producto inválida",
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:unsafe-product",
    )


async def _invalid_administration_request_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(
        error,
        (
            InvalidCrawlJobRequestError,
            InvalidCommercialRequestError,
            InvalidDiscoveryRequestError,
            InvalidRuntimePolicyError,
        ),
    )
    return problem_response(
        request,
        status_code=422,
        title="Solicitud inválida",
        detail=str(error),
        type_uri="urn:bot-ofertas:problem:invalid-administration-request",
    )


async def _integrity_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, IntegrityError)
    return problem_response(
        request,
        status_code=409,
        title="Conflicto",
        detail="El cambio entra en conflicto con un registro existente.",
        type_uri="urn:bot-ofertas:problem:conflict",
    )


async def _optimistic_concurrency_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, OptimisticConcurrencyError)
    return problem_response(
        request,
        status_code=412,
        title="Revisión desactualizada",
        detail=(
            "El recurso cambió desde que fue consultado. "
            "Vuelve a leerlo y reintenta con su ETag actual."
        ),
        type_uri="urn:bot-ofertas:problem:stale-revision",
    )


async def _idempotency_conflict_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, IdempotencyConflictError)
    return problem_response(
        request,
        status_code=409,
        title="Clave de idempotencia reutilizada",
        detail=(
            "Idempotency-Key ya se usó con una solicitud diferente. "
            "Usa una clave nueva."
        ),
        type_uri="urn:bot-ofertas:problem:idempotency-conflict",
    )


async def _unexpected_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    request_id = _request_id(request)
    logger.error(
        "Unhandled API error request_id=%s",
        request_id,
        exc_info=(type(error), error, error.__traceback__),
    )
    return problem_response(
        request,
        status_code=500,
        title="Error interno",
        detail="Ocurrió un error interno. Usa request_id para localizarlo.",
        type_uri="urn:bot-ofertas:problem:internal",
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Install the complete HTTP-to-domain error translation table."""

    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(CursorError, _cursor_error_handler)
    app.add_exception_handler(ProductNotFoundError, _product_not_found_handler)
    app.add_exception_handler(
        CrawlJobNotFoundError,
        _crawl_job_not_found_handler,
    )
    app.add_exception_handler(
        SubscriberNotFoundError,
        _commercial_not_found_handler,
    )
    app.add_exception_handler(
        LaunchChecklistItemNotFoundError,
        _commercial_not_found_handler,
    )
    app.add_exception_handler(
        UnsafeProductConfigurationError,
        _unsafe_product_handler,
    )
    app.add_exception_handler(StoreRegistryError, _unsafe_product_handler)
    app.add_exception_handler(
        InvalidCrawlJobRequestError,
        _invalid_administration_request_handler,
    )
    app.add_exception_handler(
        InvalidRuntimePolicyError,
        _invalid_administration_request_handler,
    )
    app.add_exception_handler(
        InvalidDiscoveryRequestError,
        _invalid_administration_request_handler,
    )
    app.add_exception_handler(
        InvalidCommercialRequestError,
        _invalid_administration_request_handler,
    )
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.add_exception_handler(
        OptimisticConcurrencyError,
        _optimistic_concurrency_handler,
    )
    app.add_exception_handler(
        IdempotencyConflictError,
        _idempotency_conflict_handler,
    )
    app.add_exception_handler(Exception, _unexpected_error_handler)


__all__ = [
    "RequestIdMiddleware",
    "install_exception_handlers",
    "problem_response",
]
