import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot_ofertas.crawling.coolbox import (
    CoolboxPayloadError,
    build_coolbox_catalog_url,
    normalize_coolbox_product_url,
    parse_coolbox_products,
)
from bot_ofertas.domain import PriceObservation

FIXTURE = Path(__file__).parents[1] / "fixtures" / "coolbox_catalog_product.json"
SOURCE_URL = "https://www.coolbox.pe/audifonos-demo-1000/p"


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse_fixture() -> list[PriceObservation]:
    raw_observations = parse_coolbox_products(
        load_fixture(),
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 26, 15, 0, tzinfo=UTC),
    )
    return [PriceObservation(**values) for values in raw_observations]


def test_url_is_canonical_and_catalog_endpoint_is_read_only() -> None:
    source = normalize_coolbox_product_url(
        "https://coolbox.pe/audifonos-demo-1000/p?utm_source=test#detalle"
    )

    assert source == SOURCE_URL
    assert (
        build_coolbox_catalog_url(source)
        == "https://www.coolbox.pe/api/catalog_system/pub/products/search/"
        "audifonos-demo-1000/p"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.coolbox.pe/producto/p",
        "https://example.com/producto/p",
        "https://www.coolbox.pe/checkout",
        "https://usuario:clave@www.coolbox.pe/producto/p",
    ],
)
def test_url_rejects_unsafe_or_non_product_targets(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_coolbox_product_url(url)


def test_parser_separates_sku_seller_variant_and_installments() -> None:
    observations = parse_fixture()
    own = next(item for item in observations if item.sku == "sku-negro" and item.seller_id == "1")
    marketplace = next(
        item for item in observations if item.sku == "sku-negro" and item.seller_id == "market-7"
    )

    assert len(observations) == 4
    assert own.price == Decimal("199.9")
    assert own.list_price == Decimal("249.9")
    assert own.variant == {"Color": "Negro"}
    assert own.category_path == ["Tecnología", "Audio", "Audífonos"]
    assert own.product_reference == "DEMO-1000"
    assert own.sku_reference == "DEMO-1000-NEGRO"
    assert own.is_marketplace is False
    assert marketplace.is_marketplace is True
    assert marketplace.seller_name == "Tienda Marketplace"

    # The financing amount is evidence only; it never becomes the product price.
    assert own.installments[0].amount == Decimal("49.975")
    assert own.installments[0].count == 4
    assert own.installments[0].total == Decimal("199.9")
    assert own.price != own.installments[0].amount


def test_parser_suppresses_unavailable_sentinel_prices() -> None:
    unavailable = next(item for item in parse_fixture() if item.sku == "sku-azul")

    assert unavailable.availability.value == "out_of_stock"
    assert unavailable.price is None
    assert unavailable.list_price is None
    assert unavailable.installments == []
    assert "out_of_stock_prices_suppressed" in unavailable.quality_flags
    assert "non_positive_list_price" in unavailable.quality_flags


def test_parser_marks_quantity_sentinel_and_open_box() -> None:
    open_box = next(item for item in parse_fixture() if item.sku == "sku-open-box")

    assert open_box.available_quantity is None
    assert "available_quantity_sentinel" in open_box.quality_flags
    assert open_box.condition.value == "open_box"


def test_parser_rejects_non_list_payload() -> None:
    with pytest.raises(CoolboxPayloadError, match="JSON list"):
        parse_coolbox_products(
            {"productId": "bad"},
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )
