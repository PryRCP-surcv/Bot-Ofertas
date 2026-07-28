from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import bot_ofertas.api.app as app_module
import bot_ofertas.api.routes as routes
from bot_ofertas.api.app import create_app
from bot_ofertas.api.schemas import RuntimePolicyRead
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.stores import StoreRegistry, build_store_registry

_TOKEN = "a" * 32
_ALLOWED_ORIGIN = "http://localhost:5173"


def _settings(*, docs_enabled: bool = True) -> ApiSettings:
    return ApiSettings(
        admin_token=_TOKEN,
        cors_origins=(_ALLOWED_ORIGIN,),
        docs_enabled=docs_enabled,
    )


def _policy(_session: object | None = None) -> RuntimePolicyRead:
    return RuntimePolicyRead(
        revision_id=None,
        policy_fingerprint="b" * 64,
        detector_version="phase3-v2",
        scheduler_poll_seconds=300,
        detection_history_limit=2_500,
        detection_history_days=90,
        minimum_history_samples=3,
        equivalent_max_age_hours=24,
        equivalent_limit=20,
        minimum_equivalent_samples=2,
        possible_error_minimum_corroborating_signals=2,
        possible_error_minimum_confidence=50,
        confirmation_required=True,
        confirmation_max_age_minutes=180,
        confirmation_price_tolerance_percent=Decimal("3"),
        confirmation_confidence_bonus=20,
        minimum_alert_confidence=50,
        good_deal_percent=Decimal("20"),
        exceptional_deal_percent=Decimal("40"),
        possible_price_error_percent=Decimal("70"),
        alert_cooldown_hours=24,
        alert_significant_improvement_percent=Decimal("5"),
        notification_lease_seconds=120,
        notification_max_attempts=5,
        notification_retry_base_seconds=300,
        telegram_enabled=False,
        telegram_configured=False,
        telegram_token_configured=False,
        telegram_chat_id_configured=False,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(routes, "runtime_policy", _policy)
    application = create_app(
        _settings(),
        session_factory=Mock(),
        registry=StoreRegistry(),
    )
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client


def test_liveness_is_public_and_has_request_id(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer wrong-token-that-is-long-enough",
        "Basic YWRtaW46cGFzc3dvcmQ=",
        "Bearer",
    ],
)
def test_admin_routes_reject_missing_or_invalid_credentials_uniformly(
    client: TestClient,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.get("/api/v1/settings", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 401
    assert body["instance"] == "/api/v1/settings"
    assert body["request_id"] == response.headers["x-request-id"]


def test_valid_bearer_accesses_admin_route_without_exposing_secret(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["detector_version"] == "phase3-v2"
    assert _TOKEN not in response.text


def test_openapi_documents_bearer_security_without_secret(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["components"]["securitySchemes"]["AdminBearer"] == {
        "type": "http",
        "description": ("Token administrativo local configurado en BOT_API_ADMIN_TOKEN."),
        "scheme": "bearer",
    }
    assert document["paths"]["/api/v1/settings"]["get"]["security"] == [{"AdminBearer": []}]
    for path, path_item in document["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in path_item.items():
            if method == "parameters":
                continue
            assert operation["security"] == [{"AdminBearer": []}], (
                f"{method.upper()} {path} quedó sin autenticación administrativa"
            )
    assert _TOKEN not in response.text


def test_cors_preflight_allows_panel_mutation_headers_only_for_configured_origin(
    client: TestClient,
) -> None:
    allowed = client.options(
        "/api/v1/settings",
        headers={
            "Origin": _ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": (
                "Authorization, Content-Type, If-Match, Idempotency-Key, "
                "X-Change-Reason, X-Request-ID"
            ),
        },
    )
    denied = client.options(
        "/api/v1/settings",
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    allowed_headers = allowed.headers["access-control-allow-headers"].casefold()
    for expected in (
        "authorization",
        "content-type",
        "if-match",
        "idempotency-key",
        "x-change-reason",
        "x-request-id",
    ):
        assert expected in allowed_headers
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    assert len(denied.headers["x-request-id"]) == 32


def test_cors_exposes_concurrency_and_trace_headers(client: TestClient) -> None:
    response = client.get(
        "/api/v1/settings",
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Origin": _ALLOWED_ORIGIN,
        },
    )

    assert response.status_code == 200
    exposed = response.headers["access-control-expose-headers"].casefold()
    for expected in (
        "etag",
        "location",
        "x-idempotent-replay",
        "x-request-id",
    ):
        assert expected in exposed


def test_cors_is_present_on_unauthorized_and_internal_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthorized = client.get(
        "/api/v1/settings",
        headers={"Origin": _ALLOWED_ORIGIN},
    )
    monkeypatch.setattr(
        routes,
        "runtime_policy",
        Mock(side_effect=RuntimeError("internal detail must stay private")),
    )
    failed = client.get(
        "/api/v1/settings",
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Origin": _ALLOWED_ORIGIN,
        },
    )

    assert unauthorized.status_code == 401
    assert unauthorized.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert failed.status_code == 500
    assert failed.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert failed.headers["content-type"].startswith("application/problem+json")
    assert "internal detail" not in failed.text
    assert failed.json()["request_id"] == failed.headers["x-request-id"]


def test_validation_errors_use_problem_details(client: TestClient) -> None:
    response = client.get(
        "/api/v1/observations",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:bot-ofertas:problem:validation"
    assert "query.product_id" in response.json()["invalid_fields"]


@pytest.mark.parametrize(
    ("method", "path", "json", "extra_headers"),
    [
        (
            "post",
            "/api/v1/products",
            {
                "url": "https://www.coolbox.pe/producto-invalido/p",
                "label": "   ",
            },
            {},
        ),
        (
            "put",
            f"/api/v1/products/{uuid4()}/variant",
            {"expected_variant": {"Color": "   "}},
            {"If-Match": '"1"'},
        ),
        (
            "put",
            f"/api/v1/products/{uuid4()}/variant",
            {"expected_variant": {"Color": "Azul", "COLOR": "Rojo"}},
            {"If-Match": '"1"'},
        ),
        (
            "get",
            "/api/v1/crawl-runs?status=desconocido",
            None,
            {},
        ),
    ],
)
def test_invalid_admin_inputs_are_422_not_internal_errors(
    client: TestClient,
    method: str,
    path: str,
    json: dict[str, object] | None,
    extra_headers: dict[str, str],
) -> None:
    response = client.request(
        method,
        path,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            **extra_headers,
        },
        json=json,
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_docs_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "runtime_policy", _policy)
    application = create_app(
        _settings(docs_enabled=False),
        session_factory=Mock(),
        registry=StoreRegistry(),
    )

    with TestClient(application, raise_server_exceptions=False) as test_client:
        assert test_client.get("/docs").status_code == 404
        assert test_client.get("/redoc").status_code == 404
        assert test_client.get("/openapi.json").status_code == 404


def test_readiness_checks_database_revision_and_enabled_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('test-head')"))
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(
        routes,
        "_expected_migration_heads",
        lambda: frozenset({"test-head"}),
    )
    application = create_app(
        _settings(),
        session_factory=factory,
        registry=build_store_registry(include_plugins=False),
    )

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "bot-ofertas-api",
        "database": "ready",
    }
    engine.dispose()


def test_readiness_reports_unavailable_when_migration_metadata_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routes,
        "_expected_migration_heads",
        Mock(side_effect=CommandError("missing migration directory")),
    )
    application = create_app(
        _settings(),
        session_factory=Mock(),
        registry=build_store_registry(include_plugins=False),
    )

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "missing migration directory" not in response.text


def test_factory_disposes_only_the_engine_it_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_engine = Mock()
    factory = Mock()
    monkeypatch.setattr(app_module, "create_database_engine", lambda: owned_engine)
    monkeypatch.setattr(
        app_module,
        "create_session_factory",
        lambda _engine: factory,
    )

    application = create_app(_settings(), registry=StoreRegistry())
    with TestClient(application, raise_server_exceptions=False):
        pass

    owned_engine.dispose.assert_called_once_with()
