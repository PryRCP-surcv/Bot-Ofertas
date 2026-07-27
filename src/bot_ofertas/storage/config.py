"""Database configuration sourced exclusively from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _required_environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection settings with the password excluded from repr output."""

    database: str
    username: str
    password: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 5432
    drivername: str = "postgresql+psycopg"

    def __post_init__(self) -> None:
        if not self.database.strip():
            raise ValueError("database must not be empty")
        if not self.username.strip():
            raise ValueError("username must not be empty")
        if not self.password:
            raise ValueError("password must not be empty")
        if not self.host.strip():
            raise ValueError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Build settings from POSTGRES_* variables without logging their values."""

        load_dotenv(_PROJECT_ROOT / ".env", override=False)
        raw_port = os.environ.get("POSTGRES_PORT", "5432").strip()
        try:
            port = int(raw_port)
        except ValueError as error:
            raise RuntimeError("POSTGRES_PORT must be an integer") from error

        return cls(
            database=_required_environment_value("POSTGRES_DB"),
            username=_required_environment_value("POSTGRES_USER"),
            password=_required_environment_value("POSTGRES_PASSWORD"),
            host=os.environ.get("POSTGRES_HOST", "127.0.0.1").strip(),
            port=port,
        )

    @property
    def sqlalchemy_url(self) -> URL:
        """Return a structured URL, avoiding unsafe string interpolation."""

        return URL.create(
            drivername=self.drivername,
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )

    @property
    def safe_url(self) -> str:
        """Return a URL suitable for diagnostics, always hiding the password."""

        return self.sqlalchemy_url.render_as_string(hide_password=True)
