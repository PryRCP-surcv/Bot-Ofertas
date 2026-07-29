"""Strict, size-bounded helpers for public XML sitemaps."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

MAX_SITEMAP_BYTES = 12 * 1024 * 1024
MAX_SITEMAP_LOCATIONS = 50_000
MAX_LOCATION_LENGTH = 4_096


class SitemapDocumentError(ValueError):
    """Raised when a sitemap is unsafe, malformed, or outside the supported shape."""


@dataclass(frozen=True, slots=True)
class SitemapDocument:
    kind: str
    locations: tuple[str, ...]
    image_locations: tuple[str, ...] = ()


def parse_sitemap_document(
    body: bytes,
    *,
    max_locations: int = MAX_SITEMAP_LOCATIONS,
) -> SitemapDocument:
    """Parse only a sitemap index or URL set without resolving external entities."""

    if not isinstance(body, bytes):
        raise TypeError("sitemap body must be bytes")
    if not body:
        raise SitemapDocumentError("the sitemap is empty")
    if len(body) > MAX_SITEMAP_BYTES:
        raise SitemapDocumentError("the sitemap exceeds the twelve-megabyte safety limit")
    if not 1 <= max_locations <= MAX_SITEMAP_LOCATIONS:
        raise ValueError("max_locations is outside the supported range")

    prefix = body[:16_384].lower()
    if b"<!doctype" in prefix or b"<!entity" in prefix:
        raise SitemapDocumentError("DTD and entity declarations are not accepted")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise SitemapDocumentError("the sitemap XML is malformed") from error

    root_name = _local_name(root.tag)
    if root_name == "sitemapindex":
        child_name = "sitemap"
        kind = "index"
    elif root_name == "urlset":
        child_name = "url"
        kind = "urls"
    else:
        raise SitemapDocumentError("the XML root is not a supported sitemap document")

    locations: list[str] = []
    image_locations: list[str] = []
    seen: set[str] = set()
    for child in root:
        if _local_name(child.tag) != child_name:
            continue
        raw_locations = [
            nested.text
            for nested in child
            if _local_name(nested.tag) == "loc" and nested.text is not None
        ]
        if len(raw_locations) != 1:
            continue
        location = " ".join(raw_locations[0].split())
        if not location or len(location) > MAX_LOCATION_LENGTH or location in seen:
            continue
        seen.add(location)
        locations.append(location)
        if kind == "urls" and any(
            _local_name(nested.tag) == "image"
            for nested in child
        ):
            image_locations.append(location)
        if len(locations) >= max_locations:
            break
    return SitemapDocument(
        kind=kind,
        locations=tuple(locations),
        image_locations=tuple(image_locations),
    )


def select_product_sitemap(
    locations: tuple[str, ...],
    *,
    source_url: str,
    child_path_pattern: str,
    cursor: int,
) -> tuple[str, int, int]:
    """Select one reviewed child sitemap and rotate deterministically."""

    if cursor < 0:
        raise ValueError("cursor must not be negative")
    source_parts = urlsplit(source_url)
    source_host = (source_parts.hostname or "").rstrip(".").lower()
    pattern = re.compile(child_path_pattern)
    candidates: list[str] = []
    for location in locations:
        try:
            parts = urlsplit(location)
            host = (parts.hostname or "").rstrip(".").lower()
            port = parts.port
        except ValueError:
            continue
        if (
            parts.scheme.lower() != "https"
            or host != source_host
            or parts.username is not None
            or parts.password is not None
            or port not in (None, 443)
            or parts.query
            or parts.fragment
            or not pattern.fullmatch(parts.path)
        ):
            continue
        candidates.append(location)
    if not candidates:
        raise SitemapDocumentError("the index has no reviewed product sitemap")
    position = cursor % len(candidates)
    return candidates[position], cursor + 1, len(candidates)


def label_from_product_url(url: str, *, store_name: str) -> str:
    """Build an editable human label from a canonical `/slug/p` URL."""

    path_parts = [
        unquote(part).strip()
        for part in urlsplit(url).path.split("/")
        if part.strip()
    ]
    if len(path_parts) >= 2 and path_parts[-1].casefold() == "p":
        slug = path_parts[-2]
    elif path_parts and path_parts[-1].casefold().endswith(".html"):
        slug = path_parts[-1][:-5]
    else:
        slug = ""
    words = " ".join(part for part in re.split(r"[-_]+", slug) if part)
    label = words[:500].strip()
    return label if label else f"Producto descubierto en {store_name}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].casefold()


__all__ = [
    "MAX_SITEMAP_BYTES",
    "MAX_SITEMAP_LOCATIONS",
    "SitemapDocument",
    "SitemapDocumentError",
    "label_from_product_url",
    "parse_sitemap_document",
    "select_product_sitemap",
]
