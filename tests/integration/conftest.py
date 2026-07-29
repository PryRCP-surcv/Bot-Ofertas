"""Isolation fixtures for PostgreSQL integration tests.

The integration suite must never consume observations from the operational
database.  Every opted-in test session therefore runs against a freshly
migrated temporary database and drops only that database on completion.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from bot_ofertas.storage import DatabaseSettings, create_database_engine

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAFE_DATABASE_PREFIX = "bot_ofertas_integration_"


def _database_identifier(name: str) -> str:
    """Quote a generated PostgreSQL identifier after validating its alphabet."""

    if not name.startswith(_SAFE_DATABASE_PREFIX) or not name.replace("_", "").isalnum():
        raise ValueError("unsafe temporary database name")
    return f'"{name}"'


@pytest.fixture(scope="session", autouse=True)
def isolated_postgres_database() -> None:
    """Run opted-in integration tests without reading or mutating real data."""

    if os.environ.get("RUN_POSTGRES_TESTS") != "1":
        yield
        return

    operational_settings = DatabaseSettings.from_env()
    temporary_database = f"{_SAFE_DATABASE_PREFIX}{uuid4().hex}"
    quoted_database = _database_identifier(temporary_database)
    maintenance_settings = replace(operational_settings, database="postgres")
    maintenance_engine = create_database_engine(maintenance_settings).execution_options(
        isolation_level="AUTOCOMMIT"
    )
    original_database = os.environ.get("POSTGRES_DB")
    database_created = False

    try:
        with maintenance_engine.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {quoted_database}")
        database_created = True
        os.environ["POSTGRES_DB"] = temporary_database

        alembic_config = Config(str(_PROJECT_ROOT / "alembic.ini"))
        command.upgrade(alembic_config, "head")
        yield
    finally:
        if original_database is None:
            os.environ.pop("POSTGRES_DB", None)
        else:
            os.environ["POSTGRES_DB"] = original_database

        if database_created:
            with maintenance_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database_name "
                        "AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": temporary_database},
                )
                connection.exec_driver_sql(f"DROP DATABASE {quoted_database}")
        maintenance_engine.dispose()
