"""Safe environment-backed settings for the administration API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]+$")


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} debe ser true o false")


def _port(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} debe ser un número entero") from error
    if not 1 <= value <= 65_535:
        raise RuntimeError(f"{name} debe estar entre 1 y 65535")
    return value


def _origin(value: str) -> str:
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("BOT_API_CORS_ORIGINS contiene un origen inválido") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise RuntimeError(
            "BOT_API_CORS_ORIGINS solo admite orígenes HTTP(S) exactos y revisados"
        )
    return candidate


def _cors_origins() -> tuple[str, ...]:
    raw_value = os.environ.get("BOT_API_CORS_ORIGINS")
    candidates = (
        raw_value.split(",")
        if raw_value is not None
        else list(_DEFAULT_CORS_ORIGINS)
    )
    normalized = tuple(
        dict.fromkeys(_origin(candidate) for candidate in candidates if candidate.strip())
    )
    if not normalized:
        raise RuntimeError("BOT_API_CORS_ORIGINS debe contener al menos un origen")
    return normalized


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Administration API settings with secrets excluded from diagnostics."""

    admin_token: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = _DEFAULT_CORS_ORIGINS
    docs_enabled: bool = True

    def __post_init__(self) -> None:
        token = self.admin_token.strip()
        if len(token) < 32 or len(token) > 256:
            raise ValueError("admin_token debe tener entre 32 y 256 caracteres")
        if not _TOKEN_PATTERN.fullmatch(token) or token.startswith("CHANGE_ME"):
            raise ValueError(
                "admin_token debe ser aleatorio y usar caracteres URL-safe"
            )
        object.__setattr__(self, "admin_token", token)

        host = self.host.strip()
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            raise ValueError("host debe ser local o 0.0.0.0 para un contenedor")
        object.__setattr__(self, "host", host)
        if not 1 <= self.port <= 65_535:
            raise ValueError("port debe estar entre 1 y 65535")
        object.__setattr__(
            self,
            "cors_origins",
            tuple(dict.fromkeys(_origin(item) for item in self.cors_origins)),
        )

    @classmethod
    def from_env(cls) -> ApiSettings:
        load_dotenv(_PROJECT_ROOT / ".env", override=False)
        token = os.environ.get("BOT_API_ADMIN_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_API_ADMIN_TOKEN no está configurado; genera un token aleatorio "
                "antes de iniciar la API"
            )
        return cls(
            admin_token=token,
            host=os.environ.get("BOT_API_HOST", "127.0.0.1"),
            port=_port("BOT_API_PORT", 8000),
            cors_origins=_cors_origins(),
            docs_enabled=_boolean("BOT_API_DOCS_ENABLED", True),
        )


__all__ = ["ApiSettings"]
