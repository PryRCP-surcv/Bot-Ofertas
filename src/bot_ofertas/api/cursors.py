"""Small, validated opaque cursors for stable keyset pagination."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

_CURSOR_VERSION: Final = 1
_MAX_CURSOR_LENGTH: Final = 1_024
_MAX_DECODED_LENGTH: Final = 512
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class CursorError(ValueError):
    """Raised when a pagination cursor is malformed or belongs to another query."""


@dataclass(frozen=True, slots=True)
class CursorPosition:
    """Validated ordering values recovered from one opaque cursor."""

    timestamp: datetime
    key: str


def cursor_scope(resource: str, **filters: object) -> str:
    """Bind a cursor to one resource and its normalized filters.

    The digest prevents accidentally reusing a page cursor after changing filters.
    It is not intended as an authorization or cryptographic signature.
    """

    normalized_resource = resource.strip().lower()
    if not normalized_resource or len(normalized_resource) > 64:
        raise ValueError("cursor resource must contain between 1 and 64 characters")
    normalized_filters = {
        key: None if value is None else str(value)
        for key, value in sorted(filters.items())
    }
    serialized = json.dumps(
        normalized_filters,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"{normalized_resource}:{digest}"


def encode_cursor(
    *,
    scope: str,
    timestamp: datetime,
    key: str,
) -> str:
    """Serialize the final visible row of a page into a URL-safe token."""

    normalized_scope = scope.strip()
    normalized_key = key.strip()
    if not normalized_scope or len(normalized_scope) > 96:
        raise ValueError("cursor scope must contain between 1 and 96 characters")
    if not normalized_key or len(normalized_key) > 128:
        raise ValueError("cursor key must contain between 1 and 128 characters")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    normalized_timestamp = timestamp.astimezone(UTC)
    payload = json.dumps(
        {
            "k": normalized_key,
            "s": normalized_scope,
            "t": normalized_timestamp.isoformat(timespec="microseconds"),
            "v": _CURSOR_VERSION,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str, *, scope: str) -> CursorPosition:
    """Validate and decode a cursor for the expected resource/filter scope."""

    if not isinstance(value, str):
        raise CursorError("cursor must be a string")
    token = value.strip()
    if (
        not token
        or len(token) > _MAX_CURSOR_LENGTH
        or _TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise CursorError("invalid pagination cursor")

    padding = "=" * (-len(token) % 4)
    try:
        decoded = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise CursorError("invalid pagination cursor") from error
    if len(decoded) > _MAX_DECODED_LENGTH:
        raise CursorError("invalid pagination cursor")

    try:
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CursorError("invalid pagination cursor") from error
    if not isinstance(payload, dict) or set(payload) != {"k", "s", "t", "v"}:
        raise CursorError("invalid pagination cursor")
    if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
        raise CursorError("unsupported pagination cursor")
    if payload["s"] != scope:
        raise CursorError("pagination cursor does not match the current filters")

    raw_timestamp = payload["t"]
    raw_key = payload["k"]
    if not isinstance(raw_timestamp, str) or not isinstance(raw_key, str):
        raise CursorError("invalid pagination cursor")
    if not raw_key or len(raw_key) > 128:
        raise CursorError("invalid pagination cursor")
    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except ValueError as error:
        raise CursorError("invalid pagination cursor") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CursorError("invalid pagination cursor")
    return CursorPosition(
        timestamp=timestamp.astimezone(UTC),
        key=raw_key,
    )


__all__ = [
    "CursorError",
    "CursorPosition",
    "cursor_scope",
    "decode_cursor",
    "encode_cursor",
]
