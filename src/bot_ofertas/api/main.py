"""Executable entry point for the local FastAPI administration service."""

from __future__ import annotations

import uvicorn

from bot_ofertas.api.app import create_app
from bot_ofertas.api.settings import ApiSettings


def main() -> None:
    settings = ApiSettings.from_env()
    uvicorn.run(
        create_app(api_settings=settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
    )


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    main()
