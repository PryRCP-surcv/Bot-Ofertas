"""Strict shared parser for reviewed Magento product pages with JSON-LD evidence."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

from parsel import Selector
from scrapy.http import Response


class MagentoPayloadError(ValueError):
    """Raised when a reviewed product page no longer exposes consistent evidence."""


@dataclass(frozen=True, slots=True)
class MagentoParserConfig:
    store_slug: str
    display_name: str
    extractor_version: str
    hosts: frozenset[str]
    canonical_host: str
    own_seller_names: frozenset[str]

    def __post_init__(self) -> None:
        if self.canonical_host not in self.hosts:
            raise ValueError("canonical_host must belong to the reviewed hosts")
        normalized_sellers = frozenset(_searchable_text(name) for name in self.own_seller_names)
        if not normalized_sellers or "" in normalized_sellers:
            raise ValueError("own_seller_names must not be empty")
        object.__setattr__(self, "own_seller_names", normalized_sellers)


def normalize_magento_product_url(
    url: str,
    *,
    config: MagentoParserConfig,
) -> str:
    """Accept only one explicit root-level Magento product page ending in `.html`."""

    if not isinstance(url, str) or url != url.strip() or not url:
        raise ValueError(f"A {config.display_name} product URL is required.")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise ValueError(f"The {config.display_name} product URL is invalid.") from error
    decoded_path = unquote(parts.path)
    segments = [segment for segment in decoded_path.split("/") if segment]
    if (
        parts.scheme.lower() != "https"
        or host not in config.hosts
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or len(segments) != 1
    ):
        raise ValueError(
            f"Only explicit HTTPS product URLs on reviewed {config.display_name} hosts are allowed."
        )
    filename = segments[0].strip()
    slug = filename[:-5] if filename.casefold().endswith(".html") else ""
    if (
        not slug
        or slug in {".", ".."}
        or "/" in slug
        or "\\" in slug
        or not re.fullmatch(r"[\w.\-~%]+", slug, flags=re.UNICODE)
    ):
        raise ValueError(
            f"The {config.display_name} URL must be a root product page ending in '.html'."
        )
    canonical_path = f"/{quote(unquote(slug), safe='-._~')}.html"
    return urlunsplit(("https", config.canonical_host, canonical_path, "", ""))


def parse_magento_product(
    payload: Response | str,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
    *,
    config: MagentoParserConfig,
) -> list[dict[str, Any]]:
    """Normalize one exact Magento Product JSON-LD graph into one observation."""

    canonical_url = normalize_magento_product_url(source_url, config=config)
    selector = payload.selector if isinstance(payload, Response) else Selector(text=payload)
    product = _matching_product(selector, canonical_url, config=config)
    offer = _single_offer(product, canonical_url, config=config)

    title = _required_text(product.get("name"), "product name", config=config)
    sku = _required_text(product.get("sku"), "product SKU", config=config)
    brand = _brand(product.get("brand"))
    seller_name = _seller_name(offer.get("seller"))
    quality_flags: list[str] = []
    if seller_name is None:
        seller_name = "Vendedor no informado"
        quality_flags.append("ambiguous_seller_identity")
    seller_key = _searchable_text(seller_name)
    is_marketplace = seller_key not in config.own_seller_names
    seller_id = (
        config.store_slug
        if not is_marketplace
        else f"marketplace-{hashlib.sha256(seller_key.encode('utf-8')).hexdigest()[:16]}"
    )

    currency = _currency(offer.get("priceCurrency"), quality_flags)
    price = _positive_decimal(offer.get("price"), field="offer price", config=config)
    availability = _availability(offer.get("availability"))
    if availability == "unknown":
        quality_flags.append("unknown_availability")
    if availability == "out_of_stock":
        price = None

    final_prices = _html_prices(selector, "finalPrice", config=config)
    old_prices = _html_prices(selector, "oldPrice", config=config)
    if price is not None and final_prices and price not in final_prices:
        quality_flags.append("jsonld_html_price_mismatch")
    list_price = next(iter(old_prices)) if len(old_prices) == 1 else None
    if len(old_prices) > 1:
        quality_flags.append("ambiguous_list_price")
    if price is not None and list_price is not None and list_price < price:
        quality_flags.append("list_price_below_price")
    if availability == "out_of_stock":
        list_price = None
        quality_flags.append("out_of_stock_prices_suppressed")

    product_ids = {
        value.strip()
        for value in selector.css(
            "[data-role='priceBox'][data-product-id]::attr(data-product-id)"
        ).getall()
        if value.strip()
    }
    external_product_id = next(iter(product_ids)) if len(product_ids) == 1 else sku
    if len(product_ids) > 1:
        quality_flags.append("ambiguous_external_product_id")

    product_url = _optional_text(product.get("url"))
    offer_url = _optional_text(offer.get("url"))
    canonical_evidence_url = product_url or offer_url
    if canonical_evidence_url is None:
        quality_flags.append("jsonld_url_not_reported")

    tracked_id = _tracked_product_uuid(tracked_product_id)
    observed = _observed_at(observed_at)
    payload_hash = _payload_hash(
        {
            "product": product,
            "final_prices": sorted(str(value) for value in final_prices),
            "old_prices": sorted(str(value) for value in old_prices),
        },
        config=config,
    )
    category_path = _breadcrumb_path(selector, canonical_url)
    condition = _condition(offer.get("itemCondition"))
    if condition == "unknown":
        quality_flags.append("unknown_product_condition")

    return [
        {
            "store_slug": config.store_slug,
            "tracked_product_id": tracked_id,
            "source_url": canonical_url,
            "external_product_id": external_product_id,
            "product_reference": sku,
            "sku": sku,
            "sku_reference": sku,
            "seller_id": seller_id,
            "seller_name": seller_name,
            "title": title,
            "brand": brand,
            "model": None,
            "category_path": category_path,
            "variant": {},
            "condition": condition,
            "currency": currency,
            "price": price,
            "list_price": list_price,
            "availability": availability,
            "available_quantity": None,
            "is_marketplace": is_marketplace,
            "installments": [],
            "observed_at": observed,
            "extractor_version": config.extractor_version,
            "source_payload_hash": payload_hash,
            "quality_flags": list(dict.fromkeys(quality_flags)),
        }
    ]


def _matching_product(
    selector: Selector,
    canonical_url: str,
    *,
    config: MagentoParserConfig,
) -> Mapping[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    for raw_script in selector.css("script[type='application/ld+json']::text").getall():
        try:
            decoded = json.loads(raw_script)
        except json.JSONDecodeError:
            continue
        for node in _jsonld_nodes(decoded):
            if not _has_type(node, "Product"):
                continue
            raw_urls = [
                _optional_text(node.get("url")),
                _optional_text(node.get("@id")),
            ]
            offers = node.get("offers")
            for offer in _offer_nodes(offers):
                raw_urls.append(_optional_text(offer.get("url")))
            if any(
                _same_product_url(raw_url, canonical_url, config=config)
                for raw_url in raw_urls
                if raw_url is not None
            ):
                candidates.append(node)
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        fingerprint = _payload_hash(candidate, config=config)
        if fingerprint not in seen:
            unique.append(candidate)
            seen.add(fingerprint)
    if len(unique) != 1:
        raise MagentoPayloadError(
            f"Expected one matching {config.display_name} Product JSON-LD object."
        )
    return unique[0]


def _single_offer(
    product: Mapping[str, Any],
    canonical_url: str,
    *,
    config: MagentoParserConfig,
) -> Mapping[str, Any]:
    offers = [
        offer
        for offer in _offer_nodes(product.get("offers"))
        if _has_type(offer, "Offer") and not _has_type(offer, "AggregateOffer")
    ]
    matching = [
        offer
        for offer in offers
        if (
            (raw_url := _optional_text(offer.get("url"))) is None
            or _same_product_url(raw_url, canonical_url, config=config)
        )
    ]
    if len(matching) != 1:
        raise MagentoPayloadError(
            f"Expected one exact {config.display_name} Offer JSON-LD object."
        )
    return matching[0]


def _jsonld_nodes(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _jsonld_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _jsonld_nodes(item)


def _offer_nodes(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                yield item


def _same_product_url(
    raw_url: str,
    canonical_url: str,
    *,
    config: MagentoParserConfig,
) -> bool:
    base_url = raw_url.split("#", maxsplit=1)[0]
    try:
        return normalize_magento_product_url(base_url, config=config) == canonical_url
    except ValueError:
        return False


def _has_type(value: Mapping[str, Any], expected: str) -> bool:
    raw_type = value.get("@type")
    if isinstance(raw_type, str):
        return raw_type.casefold() == expected.casefold()
    if isinstance(raw_type, list):
        return any(
            isinstance(item, str) and item.casefold() == expected.casefold()
            for item in raw_type
        )
    return False


def _html_prices(
    selector: Selector,
    price_type: str,
    *,
    config: MagentoParserConfig,
) -> set[Decimal]:
    values: set[Decimal] = set()
    query = f"[data-price-type='{price_type}'][data-price-amount]::attr(data-price-amount)"
    for raw_value in selector.css(query).getall():
        price = _positive_decimal(raw_value, field=price_type, config=config)
        if price is not None:
            values.add(price)
    return values


def _breadcrumb_path(selector: Selector, _canonical_url: str) -> list[str]:
    for raw_script in selector.css("script[type='application/ld+json']::text").getall():
        try:
            decoded = json.loads(raw_script)
        except json.JSONDecodeError:
            continue
        for node in _jsonld_nodes(decoded):
            if not _has_type(node, "BreadcrumbList"):
                continue
            items = node.get("itemListElement")
            if not isinstance(items, list):
                continue
            ordered: list[tuple[int, str]] = []
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                name = _optional_text(item.get("name"))
                position = item.get("position")
                if name and isinstance(position, int) and name.casefold() != "home":
                    ordered.append((position, name))
            ordered.sort()
            names = [name for _position, name in ordered]
            return names[:-1] if len(names) > 1 else []
    return []


def _brand(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _optional_text(value.get("name"))
    return _optional_text(value)


def _seller_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _optional_text(value.get("name"))
    return _optional_text(value)


def _currency(value: Any, quality_flags: list[str]) -> str:
    raw = _optional_text(value)
    if raw is None:
        quality_flags.append("currency_not_reported")
        return "PEN"
    currency = raw.upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        quality_flags.append("invalid_currency")
        return "PEN"
    if currency != "PEN":
        quality_flags.append(f"unexpected_currency_{currency.casefold()}")
    return currency


def _availability(value: Any) -> str:
    raw = _optional_text(value)
    suffix = raw.rsplit("/", maxsplit=1)[-1].casefold() if raw else ""
    return {
        "instock": "in_stock",
        "outofstock": "out_of_stock",
        "preorder": "preorder",
        "backorder": "backorder",
    }.get(suffix, "unknown")


def _condition(value: Any) -> str:
    raw = _optional_text(value)
    suffix = raw.rsplit("/", maxsplit=1)[-1].casefold() if raw else ""
    return {
        "newcondition": "new",
        "usedcondition": "used",
        "refurbishedcondition": "refurbished",
        "damagedcondition": "unknown",
    }.get(suffix, "unknown")


def _positive_decimal(
    value: Any,
    *,
    field: str,
    config: MagentoParserConfig,
) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (bool, float)):
        raise MagentoPayloadError(
            f"{config.display_name} {field} must be represented exactly."
        )
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise MagentoPayloadError(
            f"{config.display_name} {field} is not a valid decimal."
        ) from error
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _required_text(
    value: Any,
    field: str,
    *,
    config: MagentoParserConfig,
) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise MagentoPayloadError(f"{config.display_name} {field} is missing.")
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _searchable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.split())


def _tracked_product_uuid(value: UUID | str | None) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as error:
        raise MagentoPayloadError("tracked_product_id is not a valid UUID.") from error


def _observed_at(value: datetime | str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MagentoPayloadError("observed_at must be timezone-aware.")
    return parsed.astimezone(UTC)


def _payload_hash(value: Any, *, config: MagentoParserConfig) -> str:
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MagentoPayloadError(
            f"{config.display_name} JSON-LD cannot be represented safely."
        ) from error
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "MagentoParserConfig",
    "MagentoPayloadError",
    "normalize_magento_product_url",
    "parse_magento_product",
]
