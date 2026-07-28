import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot_ofertas.crawling.promart import (
    PromartPayloadError,
    build_promart_catalog_url,
    normalize_promart_product_url,
    parse_promart_products,
)
from bot_ofertas.crawling.spiders.promart_product import PromartProductSpider
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.promart import PromartAdapter

FIXTURE = Path(__file__).parents[1] / "fixtures" / "promart_catalog_product.json"
SOURCE_URL = "https://www.promart.pe/producto-demo-promart/p"


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse_fixture() -> list[PriceObservation]:
    raw_observations = parse_promart_products(
        load_fixture(),
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    return [PriceObservation(**values) for values in raw_observations]


def test_url_is_canonical_and_catalog_endpoint_is_read_only() -> None:
    source = normalize_promart_product_url(
        "https://promart.pe/producto-demo-promart/p?utm_source=test#detalle"
    )

    assert source == SOURCE_URL
    assert (
        build_promart_catalog_url(source)
        == "https://www.promart.pe/api/catalog_system/pub/products/search/"
        "producto-demo-promart/p"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.promart.pe/producto-demo-promart/p",
        "https://example.com/producto-demo-promart/p",
        "https://www.promart.pe/checkout",
        "https://www.promart.pe/categoria/producto-demo-promart/p",
        "https://www.promart.pe/api/catalog_system/pub/products/search/producto-demo-promart/p",
        "https://usuario:clave@www.promart.pe/producto-demo-promart/p",
    ],
)
def test_url_rejects_unsafe_or_non_product_targets(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_promart_product_url(url)


def test_parser_separates_sku_seller_variant_and_installments() -> None:
    observations = parse_fixture()
    own = next(
        item
        for item in observations
        if item.sku == "sku-negro" and item.seller_id == "1"
    )
    marketplace = next(item for item in observations if item.seller_id == "market-7")

    assert len(observations) == 4
    assert own.is_marketplace is False
    assert own.currency == "PEN"
    assert own.price == Decimal("199.9")
    assert own.list_price == Decimal("249.9")
    assert own.variant == {"Color": "Negro"}
    assert own.product_reference == "PROMART-DEMO-4100"
    assert own.sku_reference == "PROMART-DEMO-NEGRO"
    assert own.installments[0].amount == Decimal("49.975")
    assert own.installments[0].total == Decimal("199.9")
    assert own.price != own.installments[0].amount
    assert "location_context_unverified" in own.quality_flags
    assert "unsupported_price_basis" not in own.quality_flags
    assert marketplace.is_marketplace is True
    assert marketplace.seller_name == "Vendedor Marketplace"
    assert marketplace.sku == own.sku


def test_parser_marks_conditioned_promotion_as_blocking_quality_flag() -> None:
    conditioned = next(item for item in parse_fixture() if item.sku == "sku-blanco")

    assert conditioned.price == Decimal("149")
    assert conditioned.installments[0].amount == Decimal("24.833333")
    assert conditioned.price != conditioned.installments[0].amount
    assert "conditional_promotion_price" in conditioned.quality_flags


@pytest.mark.parametrize(
    ("measurement_unit", "unit_multiplier"),
    [
        ("kg", 1),
        ("m2", 1),
        ("un", "0.5"),
        (None, None),
    ],
)
def test_parser_blocks_unverified_or_variable_price_bases(
    measurement_unit: str | None,
    unit_multiplier: object,
) -> None:
    payload = load_fixture()
    item = payload[0]["items"][0]
    if measurement_unit is None:
        item.pop("measurementUnit")
    else:
        item["measurementUnit"] = measurement_unit
    if unit_multiplier is None:
        item.pop("unitMultiplier")
    else:
        item["unitMultiplier"] = unit_multiplier

    observations = parse_promart_products(
        payload,
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    own = next(
        PriceObservation(**values)
        for values in observations
        if values["sku"] == "sku-negro" and values["seller_id"] == "1"
    )

    assert "unsupported_price_basis" in own.quality_flags


def test_parser_preserves_explicit_currency_and_flags_an_invalid_code() -> None:
    payload = load_fixture()
    offer = payload[0]["items"][0]["sellers"][0]["commertialOffer"]
    offer["CurrencyCode"] = "EUR"

    explicit = next(
        PriceObservation(**values)
        for values in parse_promart_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        )
        if values["sku"] == "sku-negro" and values["seller_id"] == "1"
    )
    assert explicit.currency == "EUR"
    assert explicit.installments[0].currency == "EUR"
    assert "invalid_currency_code" not in explicit.quality_flags

    offer["CurrencyCode"] = "soles"
    invalid = next(
        PriceObservation(**values)
        for values in parse_promart_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        )
        if values["sku"] == "sku-negro" and values["seller_id"] == "1"
    )
    assert invalid.currency == "PEN"
    assert "invalid_currency_code" in invalid.quality_flags


def test_parser_also_marks_standard_vtex_teasers() -> None:
    payload = load_fixture()
    offer = payload[0]["items"][2]["sellers"][0]["commertialOffer"]
    offer["Teasers"] = offer.pop("PromotionTeasers")

    observations = parse_promart_products(
        payload,
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    conditioned = next(
        PriceObservation(**values)
        for values in observations
        if values["sku"] == "sku-blanco"
    )

    assert "conditional_promotion_price" in conditioned.quality_flags


def test_parser_marks_an_ambiguous_first_party_seller_as_marketplace() -> None:
    payload = load_fixture()
    seller = payload[0]["items"][0]["sellers"][0]
    seller["sellerName"] = "Otro vendedor"

    observations = parse_promart_products(
        payload,
        source_url=SOURCE_URL,
        tracked_product_id=None,
        observed_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )
    ambiguous = next(
        PriceObservation(**values)
        for values in observations
        if values["sku"] == "sku-negro" and values["seller_id"] == "1"
    )

    assert ambiguous.is_marketplace is True
    assert "ambiguous_promart_seller_identity" in ambiguous.quality_flags


def test_parser_rejects_a_product_that_does_not_match_requested_slug() -> None:
    payload = load_fixture()
    payload[0]["linkText"] = "otro-producto"

    with pytest.raises(PromartPayloadError, match="requested Promart slug"):
        parse_promart_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_parser_rejects_a_product_without_canonical_slug() -> None:
    payload = load_fixture()
    payload[0].pop("linkText")

    with pytest.raises(PromartPayloadError, match="canonical slug"):
        parse_promart_products(
            payload,
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_parser_suppresses_out_of_stock_zero_prices() -> None:
    unavailable = next(item for item in parse_fixture() if item.sku == "sku-azul")

    assert unavailable.is_marketplace is False
    assert unavailable.availability.value == "out_of_stock"
    assert unavailable.price is None
    assert unavailable.list_price is None
    assert unavailable.installments == []
    assert "non_positive_price" in unavailable.quality_flags
    assert "non_positive_list_price" in unavailable.quality_flags
    assert "out_of_stock_prices_suppressed" in unavailable.quality_flags


def test_parser_rejects_non_list_payload() -> None:
    with pytest.raises(PromartPayloadError, match="JSON list"):
        parse_promart_products(
            {"productId": "bad"},
            source_url=SOURCE_URL,
            tracked_product_id=None,
            observed_at=datetime.now(UTC),
        )


def test_pilot_policy_and_spider_enforce_the_reviewed_bounds() -> None:
    policy = PromartAdapter.policy

    assert policy.enabled is True
    assert policy.minimum_interval_minutes == 60
    assert policy.max_targets_per_run == 5
    assert policy.requires_explicit_product_url is True
    assert PromartProductSpider.max_targets == 5

    targets = [{"url": f"https://www.promart.pe/producto-{index}/p"} for index in range(6)]
    with pytest.raises(ValueError, match="at most 5"):
        PromartProductSpider(targets=targets)
