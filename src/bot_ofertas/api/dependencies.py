"""FastAPI dependencies with explicit database and authorization boundaries."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.stores import StoreRegistry

_BEARER = HTTPBearer(
    auto_error=False,
    scheme_name="AdminBearer",
    description="Token administrativo local configurado en BOT_API_ADMIN_TOKEN.",
)


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    """Authenticated local administrator identity used for audit records."""

    subject: str = "local-admin"


def get_api_settings(request: Request) -> ApiSettings:
    return request.app.state.api_settings


def get_store_registry(request: Request) -> StoreRegistry:
    return request.app.state.store_registry


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_admin(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_BEARER),
    ],
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
) -> AdminPrincipal:
    supplied = credentials.credentials if credentials is not None else ""
    authenticated = (
        credentials is not None
        and credentials.scheme.casefold() == "bearer"
        and supplied.isascii()
        and secrets.compare_digest(
            supplied.encode("ascii"),
            settings.admin_token.encode("ascii"),
        )
    )
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales administrativas inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AdminPrincipal()


SessionDependency = Annotated[Session, Depends(get_session)]
AdminDependency = Annotated[AdminPrincipal, Depends(require_admin)]
RegistryDependency = Annotated[StoreRegistry, Depends(get_store_registry)]

__all__ = [
    "AdminDependency",
    "AdminPrincipal",
    "RegistryDependency",
    "SessionDependency",
    "get_api_settings",
    "get_session",
    "get_store_registry",
    "require_admin",
]
