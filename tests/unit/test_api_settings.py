from __future__ import annotations

import pytest

import bot_ofertas.api.settings as settings_module
from bot_ofertas.api.settings import ApiSettings

_API_ENV_NAMES = (
    "BOT_API_ADMIN_TOKEN",
    "BOT_API_HOST",
    "BOT_API_PORT",
    "BOT_API_CORS_ORIGINS",
    "BOT_API_DOCS_ENABLED",
)


@pytest.fixture(autouse=True)
def _isolated_api_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_module,
        "load_dotenv",
        lambda *_args, **_kwargs: False,
    )
    for name in _API_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_api_settings_require_an_explicit_admin_token() -> None:
    with pytest.raises(RuntimeError, match="BOT_API_ADMIN_TOKEN"):
        ApiSettings.from_env()


def test_api_settings_allow_local_dashboard_ports_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_API_ADMIN_TOKEN", "a" * 32)

    settings = ApiSettings.from_env()

    assert settings.cors_origins == (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )


def test_api_settings_load_exact_origins_without_exposing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "safe-token-" + ("a" * 32)
    monkeypatch.setenv("BOT_API_ADMIN_TOKEN", token)
    monkeypatch.setenv(
        "BOT_API_CORS_ORIGINS",
        "https://panel.example.pe,http://localhost:5173/,https://panel.example.pe",
    )
    monkeypatch.setenv("BOT_API_DOCS_ENABLED", "false")

    settings = ApiSettings.from_env()

    assert settings.cors_origins == (
        "https://panel.example.pe",
        "http://localhost:5173",
    )
    assert settings.docs_enabled is False
    assert token not in repr(settings)


@pytest.mark.parametrize(
    "token",
    [
        "short",
        "CHANGE_ME_" + ("a" * 32),
        ("a" * 31) + " ",
        ("a" * 31) + "!",
        "a" * 257,
    ],
)
def test_api_settings_reject_unsafe_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="admin_token"):
        ApiSettings(admin_token=token)


@pytest.mark.parametrize(
    "origins",
    [
        "*",
        "http://user:password@localhost:5173",
        "http://localhost:5173/path",
        "file:///tmp/panel",
        "http://localhost:99999",
        ", ,",
    ],
)
def test_api_settings_reject_unsafe_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
    origins: str,
) -> None:
    monkeypatch.setenv("BOT_API_ADMIN_TOKEN", "a" * 32)
    monkeypatch.setenv("BOT_API_CORS_ORIGINS", origins)

    with pytest.raises(RuntimeError, match="BOT_API_CORS_ORIGINS"):
        ApiSettings.from_env()
