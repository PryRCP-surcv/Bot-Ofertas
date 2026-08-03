"""Bounded, in-memory downloads for Telegram photo upload fallback."""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
_CONTENT_TYPE_FILENAMES = {
    "image/jpeg": "offer.jpg",
    "image/png": "offer.png",
    "image/webp": "offer.webp",
}


class RemoteImageError(ValueError):
    """Sanitized image retrieval failure that never includes the remote URL."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    """One validated image kept only in memory until the Bot API call ends."""

    content: bytes
    content_type: str
    filename: str


class RemoteImageFetcher(Protocol):
    """Fetch a public HTTPS image with strict resource and network limits."""

    def fetch(self, url: str, *, timeout: float) -> DownloadedImage:
        """Return one validated in-memory image."""


Resolver = Callable[..., list[tuple[Any, ...]]]
OpenUrl = Callable[..., Any]


class _ValidatedRedirectHandler(HTTPRedirectHandler):
    """Apply the same public-network policy to every redirect target."""

    def __init__(self, resolver: Resolver) -> None:
        super().__init__()
        self._resolver = resolver

    def redirect_request(  # type: ignore[override]
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        validated_url = _validate_public_https_url(new_url, resolver=self._resolver)
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            validated_url,
        )


class SafeRemoteImageFetcher:
    """Download a small public image without persisting it to disk."""

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        resolver: Resolver = socket.getaddrinfo,
        open_url: OpenUrl | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._resolver = resolver
        self._open_url = open_url

    def fetch(self, url: str, *, timeout: float) -> DownloadedImage:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        validated_url = _validate_public_https_url(url, resolver=self._resolver)
        request = Request(
            validated_url,
            headers={
                "Accept": "image/jpeg,image/png,image/webp;q=0.9",
                "Cache-Control": "max-age=0",
                "User-Agent": "bot-ofertas/0.1",
            },
            method="GET",
        )
        try:
            if self._open_url is None:
                opener = build_opener(_ValidatedRedirectHandler(self._resolver))
                response_context = opener.open(request, timeout=timeout)
            else:
                response_context = self._open_url(request, timeout=timeout)
            with response_context as response:
                content_type = _response_content_type(response)
                content_length = _content_length(response)
                if content_length is not None and content_length > self._max_bytes:
                    raise RemoteImageError("image_too_large")
                content = response.read(self._max_bytes + 1)
        except RemoteImageError:
            raise
        except HTTPError as error:
            category = (
                "remote_rate_limited"
                if error.code == 429
                else "remote_http_error"
            )
            raise RemoteImageError(category) from None
        except (URLError, TimeoutError, OSError):
            raise RemoteImageError("remote_network_error") from None

        if len(content) > self._max_bytes:
            raise RemoteImageError("image_too_large")
        if not content:
            raise RemoteImageError("empty_image")
        detected_type = _detected_content_type(content)
        if (
            content_type not in _ALLOWED_CONTENT_TYPES
            or detected_type != content_type
        ):
            raise RemoteImageError("unsupported_image")
        return DownloadedImage(
            content=content,
            content_type=content_type,
            filename=_CONTENT_TYPE_FILENAMES[content_type],
        )


def _validate_public_https_url(url: str, *, resolver: Resolver) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise RemoteImageError("invalid_image_url")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise RemoteImageError("invalid_image_url") from error
    hostname = parsed.hostname
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise RemoteImageError("invalid_image_url")

    try:
        addresses = {
            str(info[4][0]).split("%", maxsplit=1)[0]
            for info in resolver(
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
            if len(info) >= 5 and info[4]
        }
    except (OSError, TypeError, ValueError):
        raise RemoteImageError("image_dns_error") from None
    if not addresses:
        raise RemoteImageError("image_dns_error")
    try:
        parsed_addresses = tuple(ip_address(address) for address in addresses)
    except ValueError:
        raise RemoteImageError("image_dns_error") from None
    if any(not address.is_global for address in parsed_addresses):
        raise RemoteImageError("non_public_image_host")

    return urlunsplit(
        (
            "https",
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    raw_value = headers.get("Content-Type") if headers is not None else None
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("latin-1", errors="replace")
    if not isinstance(raw_value, str):
        raise RemoteImageError("missing_content_type")
    normalized = raw_value.partition(";")[0].strip().casefold()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    raw_value = headers.get("Content-Length") if headers is not None else None
    if raw_value is None:
        return None
    try:
        parsed = int(str(raw_value))
    except (TypeError, ValueError):
        raise RemoteImageError("invalid_content_length") from None
    if parsed < 0:
        raise RemoteImageError("invalid_content_length")
    return parsed


def _detected_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


__all__ = [
    "DEFAULT_MAX_IMAGE_BYTES",
    "DownloadedImage",
    "RemoteImageError",
    "RemoteImageFetcher",
    "SafeRemoteImageFetcher",
]
