"""SQLAlchemy engine and transaction helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from bot_ofertas.storage.config import DatabaseSettings


def create_database_engine(
    settings: DatabaseSettings | None = None,
    *,
    echo: bool = False,
) -> Engine:
    """Create a pooled PostgreSQL engine whose sessions operate in UTC."""

    resolved_settings = settings or DatabaseSettings.from_env()
    return create_engine(
        resolved_settings.sqlalchemy_url,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC"},
        echo=echo,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the application's explicit transaction boundary factory."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit a unit of work or roll it back atomically on failure."""

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
