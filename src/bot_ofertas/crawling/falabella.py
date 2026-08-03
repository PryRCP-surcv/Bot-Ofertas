"""Strict parser for public Falabella Peru product pages."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

from parsel import Selector
from scrapy.http import Response

from bot_ofertas.domain import normalize_optional_https_url

FALABELLA_HOSTS = frozenset({"falabella.com.pe", "www.falabella.com.pe"})
EXTRACTOR_VERSION = "falabella-next-data-v1"
_OWN_SELLER_ID = "FALABELLA_PERU"
_OWN_SELLER_NAME = "falabella"
_FIXED_UNITS = frozenset({"un", "und", "unidad", "unit"})
_SALE_UNIT_KEYS = frozenset(
    {
        "saleunit",
        "unidad de medida de venta",
        "unidad de venta",
    }
)


class FalabellaPayloadError(ValueError):
    """Raised when Falabella's public evidence is missing or inconsistent."""


def normalize_falabella_product_url(url: str) -> str:
    """Return one exact, canonical Falabella Peru product and SKU URL."""

    if not isinstance(url, str) or url != url.strip() or not url:
        raise ValueError("A Falabella product URL is required.")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise ValueError("The Falabella product URL is invalid.") from error

    raw_segments = [segment for segment in parts.path.split("/") if segment]
    segments = [unquote(segment) for segment in raw_segments]
    slug = segments[3] if len(segments) == 5 else ""
    valid_shape = (
        len(segments) == 5
        and segments[0].casefold() == "falabella-pe"
        and segments[1].casefold() == "product"
        and segments[2].isdigit()
        and bool(slug)
        and slug.casefold() not in {"null", "undefined"}
        and "/" not in slug
        and "\\" not in slug
        and all(ord(character) >= 32 for character in slug)
        and segments[4].isdigit()
    )
    if (
        parts.scheme.lower() != "https"
        or host not in FALABELLA_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or not valid_shape
    ):
        raise ValueError(
            "Only exact HTTPS Falabella Peru product and SKU URLs are allowed."
        )

    path = (
        f"/falabella-pe/product/{segments[2]}/"
        f"{quote(slug, safe='-._~(),')}/{segments[4]}"
    )
    return urlunsplit(("https", "www.falabella.com.pe", path, "", ""))


def parse_falabella_product(
    payload: Response | str,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize the exact SKU shown by one public Falabella product page."""

    canonical_url = normalize_falabella_product_url(source_url)
    segments = [unquote(segment) for segment in urlsplit(canonical_url).path.split("/") if segment]
    expected_product_id = segments[2]
    expected_slug = segments[3]
    expected_variant_id = segments[4]
    selector = payload.selector if isinstance(payload, Response) else Selector(text=payload)

    next_data = _single_json_script(selector, "script#__NEXT_DATA__::text")
    product = _mapping_path(next_data, "props", "pageProps", "productData")
    product_id = _required_text(product.get("id"), "product id")
    product_slug = _required_text(product.get("slug"), "product slug")
    current_variant = _required_text(product.get("currentVariant"), "current variant")
    if (
        product_id != expected_product_id
        or product_slug.casefold() != expected_slug.casefold()
        or current_variant != expected_variant_id
    ):
        raise FalabellaPayloadError(
            "Falabella returned a different product or variant."
        )

    variants = product.get("variants")
    if not isinstance(variants, list):
        raise FalabellaPayloadError("Falabella product variants are missing.")
    matches = [
        variant
        for variant in variants
        if isinstance(variant, Mapping)
        and _optional_text(variant.get("id")) == expected_variant_id
    ]
    if len(matches) != 1:
        raise FalabellaPayloadError(
            "Falabella variant identity is missing or ambiguous."
        )
    variant = matches[0]

    jsonld_product = _matching_jsonld_product(selector, expected_variant_id)
    jsonld_offers = [
        offer
        for offer in _offer_nodes(jsonld_product.get("offers"))
        if _optional_text(offer.get("sku")) in {None, expected_variant_id}
    ]
    currencies = {
        _required_text(offer.get("priceCurrency"), "offer currency").upper()
        for offer in jsonld_offers
    }
    if currencies and currencies != {"PEN"}:
        raise FalabellaPayloadError(
            "Falabella price currency is not unambiguously PEN."
        )

    seller_info = product.get("sellerInfo")
    if not isinstance(seller_info, Mapping):
        raise FalabellaPayloadError("Falabella seller information is missing.")
    seller_id = _required_text(seller_info.get("sellerId"), "seller id")
    seller_name = _required_text(seller_info.get("sellerName"), "seller name")

    offerings = variant.get("offerings")
    active_offerings = (
        [
            offering
            for offering in offerings
            if isinstance(offering, Mapping) and offering.get("isActive") is True
        ]
        if isinstance(offerings, list)
        else []
    )
    if len(active_offerings) != 1:
        raise FalabellaPayloadError(
            "Falabella active seller offering is missing or ambiguous."
        )
    offering = active_offerings[0]
    offering_id = _required_text(offering.get("offeringId"), "offering id")
    if offering_id != expected_variant_id:
        raise FalabellaPayloadError(
            "Falabella offering does not match the requested variant."
        )

    offering_seller_id = _required_text(offering.get("sellerId"), "offering seller id")
    offering_seller_name = _required_text(
        offering.get("sellerName"),
        "offering seller name",
    )
    quality_flags: list[str] = []
    if (
        offering_seller_id != seller_id
        or _normalized_identity(offering_seller_name)
        != _normalized_identity(seller_name)
    ):
        quality_flags.append("ambiguous_falabella_seller_identity")

    jsonld_sellers = {
        _normalized_identity(name)
        for offer in jsonld_offers
        if (name := _jsonld_seller_name(offer.get("seller"))) is not None
    }
    if jsonld_sellers and jsonld_sellers != {_normalized_identity(seller_name)}:
        quality_flags.append("ambiguous_falabella_seller_identity")

    is_marketplace = not (
        seller_id == _OWN_SELLER_ID
        and _normalized_identity(seller_name) == _OWN_SELLER_NAME
    )
    if not is_marketplace:
        quality_flags.append("delivery_location_confirmation")

    product_out = product.get("isOutOfStock")
    purchasable = variant.get("isPurchaseable")
    online_sellable = variant.get("isOnlineSellable")
    if not all(
        isinstance(value, bool)
        for value in (product_out, purchasable, online_sellable)
    ):
        raise FalabellaPayloadError("Falabella stock evidence is missing.")
    availability = (
        "out_of_stock"
        if product_out or not purchasable or not online_sellable
        else "in_stock"
    )

    price_entries = variant.get("prices")
    if not isinstance(price_entries, list):
        raise FalabellaPayloadError("Falabella prices are missing.")
    active_prices: list[tuple[Decimal, str]] = []
    crossed_prices: list[Decimal] = []
    for entry in price_entries:
        if not isinstance(entry, Mapping):
            continue
        value = _price_value(entry.get("price"), "price")
        price_type = _required_text(entry.get("type"), "price type")
        if entry.get("crossed") is True:
            crossed_prices.append(value)
        elif entry.get("crossed") is False:
            active_prices.append((value, price_type))

    price: Decimal | None = None
    list_price: Decimal | None = None
    selected_price_type: str | None = None
    if availability == "in_stock":
        if not active_prices:
            raise FalabellaPayloadError("Falabella current price is missing.")
        price, selected_price_type = min(active_prices, key=lambda item: item[0])
        list_price = max(crossed_prices, default=None)
        if list_price is not None and list_price <= price:
            list_price = None
        conditional_flag = _conditional_price_flag(selected_price_type)
        if conditional_flag is not None:
            quality_flags.append(conditional_flag)

        jsonld_prices = {
            _price_value(offer.get("price"), "JSON-LD offer price")
            for offer in jsonld_offers
        }
        if price not in jsonld_prices:
            raise FalabellaPayloadError(
                "Falabella visible and JSON-LD prices do not match."
            )
        jsonld_availability = {
            _availability(offer.get("availability")) for offer in jsonld_offers
        }
        if jsonld_availability != {"in_stock"}:
            raise FalabellaPayloadError(
                "Falabella stock evidence is inconsistent."
            )
    else:
        quality_flags.append("out_of_stock_prices_suppressed")

    sale_unit = _sale_unit(product, variant)
    if sale_unit is not None and _normalized_identity(sale_unit) not in _FIXED_UNITS:
        quality_flags.append("unsupported_price_basis")

    title = _required_text(product.get("name"), "product name")
    brand = _optional_text(product.get("brandName"))
    model = _specification_value(product, {"model", "modelo"})
    image_url = _variant_image(variant) or _jsonld_image(jsonld_product.get("image"))
    variant_name = _optional_text(variant.get("name"))
    variant_identity = {"variant_id": expected_variant_id}
    if variant_name is not None:
        variant_identity["variant_name"] = variant_name
    category_path = _category_path(product.get("breadCrumb"))
    condition = _product_condition(product)
    tracked_id = _tracked_product_uuid(tracked_product_id)
    observed = _observed_at(observed_at)
    evidence = {
        "product_id": product_id,
        "product_slug": product_slug,
        "current_variant": current_variant,
        "seller_info": seller_info,
        "is_out_of_stock": product_out,
        "selected_variant": variant,
        "jsonld_sku": jsonld_product.get("sku"),
        "jsonld_offers": jsonld_offers,
        "selected_price_type": selected_price_type,
    }

    return [
        {
            "store_slug": "falabella",
            "tracked_product_id": tracked_id,
            "source_url": canonical_url,
            "external_product_id": product_id,
            "product_reference": product_id,
            "sku": expected_variant_id,
            "sku_reference": _optional_text(offering.get("sellerSkuId")) or offering_id,
            "seller_id": seller_id,
            "seller_name": seller_name,
            "title": title,
            "brand": brand,
            "model": model,
            "image_url": image_url,
            "category_path": category_path,
            "variant": variant_identity,
            "condition": condition,
            "currency": "PEN",
            "price": price,
            "list_price": list_price,
            "availability": availability,
            "available_quantity": None,
            "is_marketplace": is_marketplace,
            "installments": [],
            "observed_at": observed,
            "extractor_version": EXTRACTOR_VERSION,
            "source_payload_hash": hashlib.sha256(
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "quality_flags": list(dict.fromkeys(quality_flags)),
        }
    ]


def _single_json_script(
    selector: Selector,
    css_query: str,
) -> Mapping[str, Any]:
    scripts = [value for value in selector.css(css_query).getall() if value.strip()]
    if len(scripts) != 1:
        raise FalabellaPayloadError(
            "Falabella __NEXT_DATA__ payload is missing or ambiguous."
        )
    try:
        decoded = json.loads(scripts[0])
    except json.JSONDecodeError as error:
        raise FalabellaPayloadError(
            "Falabella __NEXT_DATA__ payload is invalid."
        ) from error
    if not isinstance(decoded, Mapping):
        raise FalabellaPayloadError(
            "Falabella __NEXT_DATA__ payload must be an object."
        )
    return decoded


def _matching_jsonld_product(
    selector: Selector,
    expected_variant_id: str,
) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    for raw_script in selector.css("script[type='application/ld+json']::text").getall():
        try:
            decoded = json.loads(raw_script)
        except json.JSONDecodeError:
            continue
        for node in _jsonld_nodes(decoded):
            if (
                _has_type(node, "Product")
                and _optional_text(node.get("sku")) == expected_variant_id
            ):
                matches.append(node)
    if len(matches) != 1:
        raise FalabellaPayloadError(
            "Expected one matching Falabella Product JSON-LD object."
        )
    return matches[0]


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


def _mapping_path(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            raise FalabellaPayloadError(
                "Falabella product data has an invalid shape."
            )
        current = current.get(key)
    if not isinstance(current, Mapping):
        raise FalabellaPayloadError("Falabella product data is missing.")
    return current


def _price_value(value: Any, field: str) -> Decimal:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise FalabellaPayloadError(
            f"Falabella {field} must be represented exactly."
        )
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as error:
        raise FalabellaPayloadError(f"Falabella {field} is invalid.") from error
    if not parsed.is_finite() or parsed <= 0:
        raise FalabellaPayloadError(f"Falabella {field} must be positive.")
    return parsed


def _conditional_price_flag(price_type: str) -> str | None:
    normalized = _normalized_identity(price_type)
    if "cmr" in normalized or "card" in normalized or "tarjeta" in normalized:
        return "conditional_card_price"
    if "follower" in normalized or "member" in normalized or "socio" in normalized:
        return "conditional_membership_price"
    if "coupon" in normalized or "cupon" in normalized:
        return "conditional_coupon_price"
    if "quantity" in normalized or "cantidad" in normalized:
        return "conditional_quantity_price"
    if "promo" in normalized:
        return "conditional_promotion_price"
    return None


def _sale_unit(
    product: Mapping[str, Any],
    variant: Mapping[str, Any],
) -> str | None:
    for container in (variant.get("attributes"), product.get("attributes")):
        if not isinstance(container, Mapping):
            continue
        specifications = container.get("specifications")
        if not isinstance(specifications, list):
            continue
        for specification in specifications:
            if not isinstance(specification, Mapping):
                continue
            key = _optional_text(specification.get("id")) or _optional_text(
                specification.get("name")
            )
            if (
                key is not None
                and _normalized_identity(key) in _SALE_UNIT_KEYS
            ):
                return _optional_text(specification.get("value"))
    return None


def _product_condition(product: Mapping[str, Any]) -> str:
    raw = _specification_value(
        product,
        {"10 condicion del producto", "condicion del producto", "condition"},
    )
    normalized = _normalized_identity(raw or "")
    if normalized in {"nuevo", "new"}:
        return "new"
    if normalized in {"reacondicionado", "refurbished", "renovado"}:
        return "refurbished"
    if normalized in {"usado", "used"}:
        return "used"
    if normalized in {"caja abierta", "open box"}:
        return "open_box"
    return "unknown"


def _specification_value(
    product: Mapping[str, Any],
    expected_keys: set[str],
) -> str | None:
    attributes = product.get("attributes")
    if not isinstance(attributes, Mapping):
        return None
    specifications = attributes.get("specifications")
    if not isinstance(specifications, list):
        return None
    normalized_expected = {_normalized_identity(key) for key in expected_keys}
    for specification in specifications:
        if not isinstance(specification, Mapping):
            continue
        keys = (
            _optional_text(specification.get("id")),
            _optional_text(specification.get("name")),
        )
        if any(
            key is not None and _normalized_identity(key) in normalized_expected
            for key in keys
        ):
            return _optional_text(specification.get("value"))
    return None


def _availability(value: Any) -> str:
    raw = _optional_text(value)
    suffix = raw.rsplit("/", maxsplit=1)[-1].casefold() if raw else ""
    return {
        "instock": "in_stock",
        "outofstock": "out_of_stock",
        "preorder": "preorder",
        "backorder": "backorder",
    }.get(suffix, "unknown")


def _jsonld_seller_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _optional_text(value.get("name"))
    return _optional_text(value)


def _variant_image(variant: Mapping[str, Any]) -> str | None:
    medias = variant.get("medias")
    if not isinstance(medias, list):
        return None
    for media in medias:
        if not isinstance(media, Mapping) or media.get("mediaType") != "image":
            continue
        image = _safe_https_url(media.get("url"))
        if image is not None:
            return image
    return None


def _jsonld_image(value: Any) -> str | None:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            candidate = candidate.get("url") or candidate.get("contentUrl")
        image = _safe_https_url(candidate)
        if image is not None:
            return image
    return None


def _safe_https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = f"https:{value}" if value.startswith("//") else value
    try:
        return normalize_optional_https_url(candidate, "image_url")
    except (TypeError, ValueError):
        return None


def _category_path(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = _optional_text(item.get("name")) or _optional_text(item.get("label"))
        if name is not None:
            result.append(name)
    return result


def _required_text(value: Any, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise FalabellaPayloadError(f"Falabella {field} is missing.")
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _normalized_identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    words = "".join(
        character if character.isalnum() else " "
        for character in without_accents
    )
    return " ".join(words.split())


def _tracked_product_uuid(value: UUID | str | None) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as error:
        raise FalabellaPayloadError(
            "tracked_product_id is not a valid UUID."
        ) from error


def _observed_at(value: datetime | str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if (
        not isinstance(parsed, datetime)
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise FalabellaPayloadError("observed_at must be timezone-aware.")
    return parsed.astimezone(UTC)


__all__ = [
    "EXTRACTOR_VERSION",
    "FALABELLA_HOSTS",
    "FalabellaPayloadError",
    "normalize_falabella_product_url",
    "parse_falabella_product",
]
