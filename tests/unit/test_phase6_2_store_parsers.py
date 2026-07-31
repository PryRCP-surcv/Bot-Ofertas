import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot_ofertas.crawling.plazavea import (
    PlazaVeaPayloadError,
    build_plazavea_catalog_url,
    normalize_plazavea_product_url,
    parse_plazavea_products,
)
from bot_ofertas.crawling.spiders.plazavea_product import PlazaVeaProductSpider
from bot_ofertas.crawling.spiders.topitop_product import TopitopProductSpider
from bot_ofertas.crawling.spiders.vega_product import VegaProductSpider
from bot_ofertas.crawling.topitop import (
    TopitopPayloadError,
    build_topitop_catalog_url,
    normalize_topitop_product_url,
    parse_topitop_products,
)
from bot_ofertas.crawling.vega import (
    VegaPayloadError,
    build_vega_catalog_url,
    normalize_vega_product_url,
    parse_vega_products,
)
from bot_ofertas.detection import assess_quality_flags
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.plazavea import PlazaVeaAdapter
from bot_ofertas.stores.topitop import TopitopAdapter
from bot_ofertas.stores.vega import VegaAdapter

FIXTURE = Path(__file__).parents[1] / "fixtures" / "phase6_2_catalog_products.json"
OBSERVED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
STORE_CASES = {
    "vega": {
        "url": "https://www.vega.pe/gaseosa-demo-botella-1-5l-720235/p",
        "normalizer": normalize_vega_product_url,
        "catalog": build_vega_catalog_url,
        "parser": parse_vega_products,
        "error": VegaPayloadError,
        "catalog_url": (
            "https://www.vega.pe/api/catalog_system/pub/products/search/"
            "gaseosa-demo-botella-1-5l-720235/p"
        ),
        "seller": "CORPORACIÓN VEGA",
        "price": Decimal("4.5"),
        "list_price": Decimal("6"),
    },
    "plazavea": {
        "url": "https://www.plazavea.com.pe/agua-mineral-demo-botella-600ml/p",
        "normalizer": normalize_plazavea_product_url,
        "catalog": build_plazavea_catalog_url,
        "parser": parse_plazavea_products,
        "error": PlazaVeaPayloadError,
        "catalog_url": (
            "https://www.plazavea.com.pe/api/catalog_system/pub/products/search/"
            "agua-mineral-demo-botella-600ml/p"
        ),
        "seller": "Plaza Vea",
        "price": Decimal("1.9"),
        "list_price": Decimal("2"),
    },
    "topitop": {
        "url": "https://www.topitop.pe/casaca-mujer-demo-negro-3220777/p",
        "normalizer": normalize_topitop_product_url,
        "catalog": build_topitop_catalog_url,
        "parser": parse_topitop_products,
        "error": TopitopPayloadError,
        "catalog_url": (
            "https://www.topitop.pe/api/catalog_system/pub/products/search/"
            "casaca-mujer-demo-negro-3220777/p"
        ),
        "seller": "TRADING FASHION LINE S.A.",
        "price": Decimal("129.95"),
        "list_price": Decimal("259.9"),
    },
}


def load_fixture(store_slug: str) -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return copy.deepcopy(data[store_slug])


def parse_fixture(store_slug: str) -> list[PriceObservation]:
    case = STORE_CASES[store_slug]
    raw = case["parser"](
        load_fixture(store_slug),
        case["url"],
        None,
        OBSERVED_AT,
    )
    return [PriceObservation(**values) for values in raw]


@pytest.mark.parametrize("store_slug", STORE_CASES)
def test_reviewed_store_urls_are_canonical_and_use_exact_public_catalogue(
    store_slug: str,
) -> None:
    case = STORE_CASES[store_slug]
    canonical = case["normalizer"](case["url"] + "?utm_source=test#detalle")

    assert canonical == case["url"]
    assert case["catalog"](canonical) == case["catalog_url"]


@pytest.mark.parametrize("store_slug", STORE_CASES)
def test_reviewed_store_parser_preserves_price_seller_and_fixed_unit(
    store_slug: str,
) -> None:
    case = STORE_CASES[store_slug]
    observations = parse_fixture(store_slug)
    own = next(item for item in observations if not item.is_marketplace)

    assert own.store_slug == store_slug
    assert own.seller_name == case["seller"]
    assert own.price == case["price"]
    assert own.list_price == case["list_price"]
    assert own.currency == "PEN"
    assert "unsupported_price_basis" not in own.quality_flags

    assessment = assess_quality_flags(own.quality_flags)
    assert assessment.blocking_quality_flags == ()


@pytest.mark.parametrize("store_slug", ("vega", "plazavea"))
def test_location_dependent_retailers_emit_an_informational_lima_reminder(
    store_slug: str,
) -> None:
    own = next(item for item in parse_fixture(store_slug) if not item.is_marketplace)

    assert "delivery_location_confirmation" in own.quality_flags
    assert assess_quality_flags(own.quality_flags).blocking_quality_flags == ()


def test_topitop_keeps_each_size_as_an_exact_variant() -> None:
    observations = parse_fixture("topitop")

    assert len(observations) == 2
    assert {item.variant["Talla"] for item in observations} == {"XS", "S"}
    assert {item.sku for item in observations} == {"3220777", "3220778"}


def test_plazavea_preserves_marketplace_without_treating_it_as_own_stock() -> None:
    observations = parse_fixture("plazavea")
    marketplace = next(item for item in observations if item.seller_id == "market-8")

    assert marketplace.is_marketplace is True
    assert marketplace.seller_name == "Tienda Marketplace"


@pytest.mark.parametrize("store_slug", STORE_CASES)
def test_seller_identity_requires_the_reviewed_id_and_legal_name(store_slug: str) -> None:
    case = STORE_CASES[store_slug]
    payload = load_fixture(store_slug)
    payload[0]["items"][0]["sellers"][0]["sellerName"] = "Nombre no revisado"

    observations = [
        PriceObservation(**values)
        for values in case["parser"](payload, case["url"], None, OBSERVED_AT)
    ]
    mismatched = observations[0]

    assert mismatched.is_marketplace is True
    assert any(flag.startswith("ambiguous_") for flag in mismatched.quality_flags)
    assert assess_quality_flags(mismatched.quality_flags).blocking_quality_flags


@pytest.mark.parametrize("store_slug", STORE_CASES)
def test_variable_or_missing_unit_basis_is_blocking(store_slug: str) -> None:
    case = STORE_CASES[store_slug]
    payload = load_fixture(store_slug)
    payload[0]["items"][0]["measurementUnit"] = "kg"

    observations = [
        PriceObservation(**values)
        for values in case["parser"](payload, case["url"], None, OBSERVED_AT)
    ]
    own = next(item for item in observations if not item.is_marketplace)

    assert "unsupported_price_basis" in own.quality_flags
    assert assess_quality_flags(own.quality_flags).blocking_quality_flags


@pytest.mark.parametrize("store_slug", STORE_CASES)
def test_payload_identity_is_fenced_to_the_requested_slug(store_slug: str) -> None:
    case = STORE_CASES[store_slug]
    payload = load_fixture(store_slug)
    payload[0]["linkText"] = "otro-producto"

    with pytest.raises(case["error"], match="requested"):
        case["parser"](payload, case["url"], None, OBSERVED_AT)


@pytest.mark.parametrize(
    ("adapter", "spider", "maximum"),
    [
        (VegaAdapter, VegaProductSpider, 5),
        (PlazaVeaAdapter, PlazaVeaProductSpider, 5),
        (TopitopAdapter, TopitopProductSpider, 10),
    ],
)
def test_new_store_policies_keep_bounded_explicit_targets(
    adapter: type,
    spider: type,
    maximum: int,
) -> None:
    assert adapter.policy.enabled is True
    assert adapter.policy.minimum_interval_minutes == 60
    assert adapter.policy.max_targets_per_run == maximum
    assert adapter.policy.requires_explicit_product_url is True
    assert spider.max_targets == maximum
