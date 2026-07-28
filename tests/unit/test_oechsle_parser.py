import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot_ofertas.crawling.oechsle import (
    OechslePayloadError,
    build_oechsle_catalog_url,
    normalize_oechsle_product_url,
    parse_oechsle_products,
)
from bot_ofertas.crawling.spiders.oechsle_product import OechsleProductSpider
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.oechsle import OechsleAdapter

FIXTURE = Path(__file__).parents[1] / "fixtures" / "oechsle_catalog_product.json"
SOURCE_URL = "https://www.oechsle.pe/producto-demo-3000/p"


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse_fixture() -> list[PriceObservation]:
    raw_observations = parse_oechsle_products(
        load_fixture(),
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    return [PriceObservation(**values) for values in raw_observations]


def test_url_is_canonical_and_catalog_endpoint_is_read_only() -> None:
    source = normalize_oechsle_product_url(
        "https://oechsle.pe/producto-demo-3000/p?utm_source=test#detalle"
    )

    assert source == SOURCE_URL
    assert (
        build_oechsle_catalog_url(source)
        == "https://www.oechsle.pe/api/catalog_system/pub/products/search/"
        "producto-demo-3000/p"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.oechsle.pe/producto-demo-3000/p",
        "https://example.com/producto-demo-3000/p",
        "https://www.oechsle.pe/checkout",
        "https://www.oechsle.pe/categoria/producto-demo-3000/p",
        "https://www.oechsle.pe/api/catalog_system/pub/products/search/producto-demo-3000/p",
        "https://usuario:clave@www.oechsle.pe/producto-demo-3000/p",
    ],
)
def test_url_rejects_unsafe_or_non_product_targets(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_oechsle_product_url(url)


def test_parser_separates_sku_seller_variant_and_installments() -> None:
    observations = parse_fixture()
    marketplace = next(item for item in observations if item.seller_id == "market-20")
    conditioned = next(item for item in observations if item.sku == "sku-blanco")

    assert len(observations) == 4
    assert marketplace.is_marketplace is True
    assert marketplace.seller_name == "Vendedor Marketplace"
    assert conditioned.is_marketplace is False
    assert conditioned.price == Decimal("149")
    assert conditioned.list_price == Decimal("199")
    assert conditioned.variant == {"Color": "Blanco"}
    assert conditioned.product_reference == "DEMO-3000"
    assert conditioned.sku_reference == "DEMO-3000-BLANCO"
    assert conditioned.installments[0].amount == Decimal("24.833333")
    assert conditioned.installments[0].total == Decimal("149")
    assert conditioned.price != conditioned.installments[0].amount


def test_parser_suppresses_out_of_stock_prices_even_for_own_seller() -> None:
    unavailable = next(
        item
        for item in parse_fixture()
        if item.sku == "sku-negro" and item.seller_id == "1"
    )

    assert unavailable.is_marketplace is False
    assert unavailable.availability.value == "out_of_stock"
    assert unavailable.price is None
    assert unavailable.list_price is None
    assert unavailable.installments == []
    assert "out_of_stock_prices_suppressed" in unavailable.quality_flags


def test_parser_marks_conditioned_promotions_and_ambiguous_own_sellers() -> None:
    observations = parse_fixture()
    conditioned = next(item for item in observations if item.sku == "sku-blanco")
    ambiguous = next(item for item in observations if item.sku == "sku-gris")

    assert "conditional_promotion_price" in conditioned.quality_flags
    assert ambiguous.is_marketplace is True
    assert "ambiguous_oechsle_seller_identity" in ambiguous.quality_flags


def test_parser_marks_standard_vtex_payment_method_teasers() -> None:
    payload = load_fixture()
    offer = payload[0]["items"][0]["sellers"][0]["commertialOffer"]
    offer.pop("PromotionTeasers", None)
    offer["Teasers"] = [
        {
            "<Conditions>k__BackingField": {
                "<Parameters>k__BackingField": [
                    {
                        "<Name>k__BackingField": "PaymentMethodId",
                        "<Value>k__BackingField": "205,210",
                    }
                ]
            }
        }
    ]

    observations = parse_oechsle_products(
        payload,
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    own = next(
        PriceObservation(**values)
        for values in observations
        if values["sku"] == "sku-blanco" and values["seller_id"] == "1"
    )

    assert "conditional_promotion_price" in own.quality_flags


def test_parser_rejects_a_product_that_does_not_match_requested_slug() -> None:
    payload = load_fixture()
    payload[0]["linkText"] = "otro-producto"

    with pytest.raises(OechslePayloadError, match="requested Oechsle slug"):
        parse_oechsle_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_parser_rejects_a_product_without_canonical_slug() -> None:
    payload = load_fixture()
    payload[0].pop("linkText")

    with pytest.raises(OechslePayloadError, match="canonical slug"):
        parse_oechsle_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_parser_rejects_non_list_payload() -> None:
    with pytest.raises(OechslePayloadError, match="JSON list"):
        parse_oechsle_products(
            {"productId": "bad"},
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_pilot_policy_and_spider_enforce_the_reviewed_bounds() -> None:
    policy = OechsleAdapter.policy

    assert policy.enabled is True
    assert policy.minimum_interval_minutes == 60
    assert policy.max_targets_per_run == 5
    assert policy.requires_explicit_product_url is True
    assert OechsleProductSpider.max_targets == 5

    targets = [{"url": f"https://www.oechsle.pe/producto-{index}/p"} for index in range(6)]
    with pytest.raises(ValueError, match="at most 5"):
        OechsleProductSpider(targets=targets)
