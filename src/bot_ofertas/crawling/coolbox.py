"""Pure normalization helpers for Coolbox's public VTEX catalog response."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

COOLBOX_HOSTS = frozenset({"coolbox.pe", "www.coolbox.pe"})
EXTRACTOR_VERSION = "coolbox-vtex-v1"
MAX_REPORTED_QUANTITY = 99_999


class CoolboxPayloadError(ValueError):
    """Raised when the public response no longer matches the expected VTEX shape."""


def normalize_coolbox_product_url(url: str) -> str:
    """Validate and canonicalize an explicit public Coolbox product URL.

    Only HTTPS product-detail URLs on Coolbox are accepted. Query parameters and
    fragments are intentionally discarded; credentials, non-default ports, and
    non-product paths are rejected.
    """

    candidate = url.strip()
    if not candidate:
        raise ValueError("A Coolbox product URL is required.")

    parts = urlsplit(candidate)
    hostname = (parts.hostname or "").lower()
    if (
        parts.scheme.lower() != "https"
        or hostname not in COOLBOX_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        raise ValueError(
            "Only explicit HTTPS product URLs on coolbox.pe or www.coolbox.pe are allowed."
        )

    decoded_path = unquote(parts.path)
    path_segments = [segment for segment in decoded_path.split("/") if segment]
    if len(path_segments) < 2 or path_segments[-1].lower() != "p":
        raise ValueError("The Coolbox URL must be a product page ending in '/p'.")

    slug = path_segments[-2].strip()
    if not slug or slug in {".", ".."} or "/" in slug or "\\" in slug:
        raise ValueError("The Coolbox product URL contains an invalid slug.")

    encoded_segments = [quote(segment, safe="-._~") for segment in path_segments]
    canonical_path = "/" + "/".join(encoded_segments[:-2] + [quote(slug, safe="-._~"), "p"])
    return urlunsplit(("https", "www.coolbox.pe", canonical_path, "", ""))


def build_coolbox_catalog_url(product_url: str) -> str:
    """Derive the read-only public VTEX catalog endpoint for a product page."""

    canonical_url = normalize_coolbox_product_url(product_url)
    path_segments = [segment for segment in urlsplit(canonical_url).path.split("/") if segment]
    slug = path_segments[-2]
    return f"https://www.coolbox.pe/api/catalog_system/pub/products/search/{slug}/p"


def canonical_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 over a canonical JSON representation."""

    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_canonical_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise CoolboxPayloadError("The Coolbox payload cannot be represented as JSON.") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_coolbox_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize a VTEX product list into one observation per SKU and seller.

    Monetary fields are ``Decimal`` values (or ``None``), while ``observed_at`` is
    normalized to an aware UTC ``datetime``. Installment values never substitute
    for the cash/current price.
    """

    if not isinstance(payload, list):
        raise CoolboxPayloadError("Expected the Coolbox catalog response to be a JSON list.")

    canonical_source_url = normalize_coolbox_product_url(source_url)
    normalized_tracked_product_id = _tracked_product_uuid(tracked_product_id)
    normalized_observed_at = _normalize_observed_at(observed_at)
    payload_hash = canonical_payload_hash(payload)
    observations: list[dict[str, Any]] = []

    for product_index, product in enumerate(payload):
        if not isinstance(product, Mapping):
            raise CoolboxPayloadError(f"Product at index {product_index} is not an object.")

        product_id = _required_identifier(product.get("productId"), "productId")
        product_title = _first_text(product.get("productName"), product.get("productTitle"))
        brand = _first_text(product.get("brand"))
        model = _model_from_product(product)
        category_path = _category_path(product)
        product_reference_id = _reference_id(
            product.get("productReference", product.get("referenceId"))
        )

        items = product.get("items", [])
        if items is None:
            items = []
        if not isinstance(items, list):
            raise CoolboxPayloadError(f"Product {product_id!r} has a non-list 'items' field.")

        for item_index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise CoolboxPayloadError(
                    f"Item at product {product_id!r}, index {item_index} is not an object."
                )

            sku_id = _required_identifier(item.get("itemId"), "itemId")
            sku_name = _first_text(
                item.get("nameComplete"),
                item.get("name"),
                product_title,
            )
            if sku_name is None:
                raise CoolboxPayloadError(f"SKU {sku_id!r} is missing its title.")
            variant = _variant_attributes(item)
            sku_reference_id = _reference_id(item.get("referenceId"))
            condition = _detect_condition(product, item)

            sellers = item.get("sellers", [])
            if sellers is None:
                sellers = []
            if not isinstance(sellers, list):
                raise CoolboxPayloadError(f"SKU {sku_id!r} has a non-list 'sellers' field.")

            for seller_index, seller in enumerate(sellers):
                if not isinstance(seller, Mapping):
                    raise CoolboxPayloadError(
                        f"Seller at SKU {sku_id!r}, index {seller_index} is not an object."
                    )

                seller_id = _required_identifier(seller.get("sellerId"), "sellerId")
                seller_name = _first_text(seller.get("sellerName"), seller_id)
                offer = seller.get("commertialOffer") or {}
                if not isinstance(offer, Mapping):
                    raise CoolboxPayloadError(
                        f"Seller {seller_id!r} on SKU {sku_id!r} has an invalid offer."
                    )

                raw_quantity = _integer_or_none(offer.get("AvailableQuantity"))
                quantity_is_sentinel = (
                    raw_quantity is not None and raw_quantity >= MAX_REPORTED_QUANTITY
                )
                quantity_is_invalid = raw_quantity is not None and raw_quantity < 0
                stock_quantity = (
                    None if quantity_is_sentinel or quantity_is_invalid else raw_quantity
                )
                availability = _availability(offer.get("IsAvailable"), raw_quantity)
                is_out_of_stock = availability == "out_of_stock"
                quality_flags: list[str] = []
                if quantity_is_sentinel:
                    quality_flags.append("available_quantity_sentinel")
                if quantity_is_invalid:
                    quality_flags.append("invalid_available_quantity")

                # Deliberately read only Price for the current price. In particular,
                # Installments.Value is never a fallback for this field.
                price = _positive_decimal(offer.get("Price"))
                list_price = _positive_decimal(offer.get("ListPrice"))
                if _is_present_non_positive_number(offer.get("Price")):
                    quality_flags.append("non_positive_price")
                if _is_present_non_positive_number(offer.get("ListPrice")):
                    quality_flags.append("non_positive_list_price")
                if price is not None and list_price is not None and list_price < price:
                    quality_flags.append("list_price_below_price")
                if is_out_of_stock:
                    price = None
                    list_price = None
                    quality_flags.append("out_of_stock_prices_suppressed")

                installments = _installments(offer.get("Installments"), _currency_code(offer))
                if is_out_of_stock:
                    installments = []

                currency = _currency_code(offer)
                observations.append(
                    {
                        "store_slug": "coolbox",
                        "tracked_product_id": normalized_tracked_product_id,
                        "source_url": canonical_source_url,
                        "external_product_id": product_id,
                        "product_reference": product_reference_id,
                        "sku": sku_id,
                        "sku_reference": sku_reference_id,
                        "seller_id": seller_id,
                        "seller_name": seller_name,
                        "title": sku_name,
                        "brand": brand,
                        "model": model,
                        "category_path": category_path,
                        "variant": variant,
                        "condition": condition,
                        "currency": currency,
                        "price": price,
                        "list_price": list_price,
                        "availability": availability,
                        "available_quantity": stock_quantity,
                        "is_marketplace": seller_id != "1",
                        "installments": installments,
                        "observed_at": normalized_observed_at,
                        "extractor_version": EXTRACTOR_VERSION,
                        "source_payload_hash": payload_hash,
                        "quality_flags": quality_flags,
                    }
                )

    return observations


def _canonical_json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _normalize_observed_at(value).isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _normalize_observed_at(value: datetime | str) -> datetime:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith(("Z", "z")):
            candidate = candidate[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("observed_at must be a valid ISO-8601 timestamp.") from exc
    if not isinstance(value, datetime):
        raise TypeError("observed_at must be a datetime or an ISO-8601 string.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must include a timezone.")
    return value.astimezone(UTC)


def _required_identifier(value: Any, field_name: str) -> str:
    identifier = _first_text(value)
    if identifier is None:
        raise CoolboxPayloadError(f"The Coolbox payload is missing {field_name!r}.")
    return identifier


def _tracked_product_uuid(value: UUID | str | None) -> UUID | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("tracked_product_id must be a valid UUID.") from exc


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if normalized:
                return normalized
        elif isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            return str(value)
        elif isinstance(value, list):
            nested = _first_text(*value)
            if nested:
                return nested
    return None


def _reference_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        key = _first_text(value.get("Key"), value.get("key"))
        if key is None or key.casefold() in {"refid", "reference", "referencia"}:
            return _first_text(value.get("Value"), value.get("value"))
        return None
    if isinstance(value, list):
        for reference in value:
            if not isinstance(reference, Mapping):
                continue
            key = _first_text(reference.get("Key"), reference.get("key"))
            if key and key.casefold() in {"refid", "reference", "referencia"}:
                return _first_text(reference.get("Value"), reference.get("value"))
        for reference in value:
            if isinstance(reference, Mapping):
                candidate = _first_text(reference.get("Value"), reference.get("value"))
                if candidate:
                    return candidate
    return _first_text(value)


def _model_from_product(product: Mapping[str, Any]) -> str | None:
    for key in ("Modelo", "modelo", "Model", "model"):
        model = _first_text(product.get(key))
        if model:
            return model
    return None


def _category_path(product: Mapping[str, Any]) -> list[str]:
    categories = product.get("categories")
    if not isinstance(categories, list):
        return []

    for category in categories:
        text = _first_text(category)
        if not text:
            continue
        path = [part.strip() for part in text.split("/") if part.strip()]
        if path:
            # VTEX orders the most-specific category path first.
            return path
    return []


def _variant_attributes(item: Mapping[str, Any]) -> dict[str, str]:
    attributes: dict[str, str] = {}
    variations = item.get("variations")
    if isinstance(variations, list):
        for variation in variations:
            if isinstance(variation, str):
                name = _first_text(variation)
                if not name:
                    continue
                value = _variant_value(item.get(variation))
                if value:
                    attributes[name] = value
                continue
            if not isinstance(variation, Mapping):
                continue
            name = _first_text(variation.get("name"), variation.get("Name"))
            if not name:
                continue
            raw_values = variation.get("values", variation.get("Values"))
            value = _variant_value(raw_values)
            if value:
                attributes[name] = value

    variation_values = item.get("variationValues")
    if isinstance(variation_values, Mapping):
        for raw_name, raw_value in variation_values.items():
            name = _first_text(raw_name)
            value = _variant_value(raw_value)
            if name and value:
                attributes.setdefault(name, value)
    return attributes


def _variant_value(value: Any) -> str | None:
    if isinstance(value, list):
        values = [text for item in value if (text := _first_text(item)) is not None]
        return " | ".join(values) or None
    return _first_text(value)


def _is_present_non_positive_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return decimal_value.is_finite() and decimal_value <= 0


def _installments(value: Any, currency: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for installment in value:
        if not isinstance(installment, Mapping):
            continue
        amount = _positive_decimal(installment.get("Value"))
        count = _integer_or_none(installment.get("NumberOfInstallments"))
        if amount is None or count is None or count <= 0:
            continue

        interest_rate = _decimal_or_none(installment.get("InterestRate"))
        total = _positive_decimal(
            installment.get(
                "TotalValuePlusInterestRate",
                installment.get("TotalValuePlusInterest"),
            )
        )
        payment_method = _first_text(
            installment.get("PaymentSystemName"),
            installment.get("paymentSystemName"),
            installment.get("PaymentSystem"),
            installment.get("paymentSystem"),
        )
        normalized.append(
            {
                "count": count,
                "amount": amount,
                "currency": currency,
                "total": total,
                "down_payment": None,
                "interest_free": interest_rate == 0 if interest_rate is not None else None,
                "issuer": None,
                "payment_method": payment_method,
                "source_text": None,
            }
        )
    return normalized


def _detect_condition(product: Mapping[str, Any], item: Mapping[str, Any]) -> str:
    searchable = " ".join(
        filter(
            None,
            (
                _first_text(product.get("productName")),
                _first_text(product.get("description")),
                _first_text(product.get("linkText")),
                _first_text(item.get("name")),
                _first_text(item.get("nameComplete")),
                _first_text(item.get("complementName")),
            ),
        )
    )
    normalized = unicodedata.normalize("NFKD", searchable.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))

    if re.search(r"\b(open[\s-]?box|caja abierta)\b", normalized):
        return "open_box"
    if re.search(r"\b(reacondicionad[oa]s?|refurbished|remanufacturad[oa]s?)\b", normalized):
        return "refurbished"
    if re.search(r"\b(usad[oa]s?|segunda mano|seminuev[oa]s?)\b", normalized):
        return "used"
    return "new"


def _integer_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        return None
    return int(numeric)


def _boolean_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _availability(is_available_value: Any, raw_quantity: int | None) -> str:
    is_available = _boolean_or_none(is_available_value)
    if is_available is False or (raw_quantity is not None and raw_quantity <= 0):
        return "out_of_stock"
    if is_available is True or (raw_quantity is not None and raw_quantity > 0):
        return "in_stock"
    return "unknown"


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value <= 0:
        return None
    return decimal_value


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return decimal_value


def _currency_code(offer: Mapping[str, Any]) -> str:
    raw_currency = _first_text(
        offer.get("CurrencyCode"),
        offer.get("currencyCode"),
        offer.get("Currency"),
    )
    if raw_currency:
        normalized = raw_currency.upper().replace("S/.", "PEN").replace("S/", "PEN")
        if normalized in {"PEN", "USD"}:
            return normalized
    return "PEN"


__all__ = [
    "COOLBOX_HOSTS",
    "EXTRACTOR_VERSION",
    "CoolboxPayloadError",
    "build_coolbox_catalog_url",
    "canonical_payload_hash",
    "normalize_coolbox_product_url",
    "parse_coolbox_products",
]
