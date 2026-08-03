import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bot_ofertas.crawling.casaideas import (
    build_casaideas_catalog_url,
    normalize_casaideas_product_url,
    parse_casaideas_products,
)
from bot_ofertas.crawling.footloose import (
    build_footloose_catalog_url,
    normalize_footloose_product_url,
    parse_footloose_products,
)
from bot_ofertas.crawling.spiders.casaideas_product import CasaideasProductSpider
from bot_ofertas.crawling.spiders.footloose_product import FootlooseProductSpider
from bot_ofertas.crawling.spiders.wong_product import WongProductSpider
from bot_ofertas.crawling.wong import (
    build_wong_catalog_url,
    normalize_wong_product_url,
    parse_wong_products,
)
from bot_ofertas.detection import assess_quality_flags
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.casaideas import CasaideasAdapter
from bot_ofertas.stores.footloose import FootlooseAdapter
from bot_ofertas.stores.wong import WongAdapter

OBSERVED_AT = datetime(2026, 7, 31, 20, 0, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures" / "phase6_2_catalog_products.json"
WONG_URL = (
    "https://www.wong.pe/"
    "espumante-brut-zonin-prosecco-doc-botella-750ml-433571/p"
)
FOOTLOOSE_URL = (
    "https://www.footloose.pe/"
    "sandalias-footloose-mujeres-fch-nz006-marie-delux/p"
)
CASAIDEAS_URL = (
    "https://www.casaideas.com.pe/casa-dormitorio-plumon-micro-doble/p"
)


def reviewed_payload(
    *,
    product_id: str,
    product_name: str,
    slug: str,
    seller_name: str,
    measurement_unit: str = "un",
) -> list[dict]:
    payload = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["topitop"])
    product = payload[0]
    product["productId"] = product_id
    product["productName"] = product_name
    product["linkText"] = slug
    for item in product["items"]:
        item["measurementUnit"] = measurement_unit
        item["unitMultiplier"] = 1 if measurement_unit == "un" else 0.75
        for seller in item["sellers"]:
            seller["sellerId"] = "1"
            seller["sellerName"] = seller_name
    return payload


@pytest.mark.parametrize(
    ("source_url", "normalizer", "builder", "expected_api"),
    [
        (
            WONG_URL,
            normalize_wong_product_url,
            build_wong_catalog_url,
            "https://www.wong.pe/api/catalog_system/pub/products/search/"
            "espumante-brut-zonin-prosecco-doc-botella-750ml-433571/p",
        ),
        (
            FOOTLOOSE_URL,
            normalize_footloose_product_url,
            build_footloose_catalog_url,
            "https://www.footloose.pe/api/catalog_system/pub/products/search/"
            "sandalias-footloose-mujeres-fch-nz006-marie-delux/p",
        ),
        (
            CASAIDEAS_URL,
            normalize_casaideas_product_url,
            build_casaideas_catalog_url,
            "https://www.casaideas.com.pe/api/catalog_system/pub/products/search/"
            "casa-dormitorio-plumon-micro-doble/p",
        ),
    ],
)
def test_new_store_urls_are_canonical_and_map_to_public_catalog(
    source_url: str,
    normalizer,
    builder,
    expected_api: str,
) -> None:
    canonical = normalizer(source_url + "?utm_source=test#offer")

    assert canonical == source_url
    assert builder(canonical) == expected_api


@pytest.mark.parametrize(
    ("source_url", "payload", "parser", "expected_seller", "location_flag"),
    [
        (
            WONG_URL,
            reviewed_payload(
                product_id="6437",
                product_name="Espumante Brut Zonin Prosecco",
                slug="espumante-brut-zonin-prosecco-doc-botella-750ml-433571",
                seller_name="WongIO",
            ),
            parse_wong_products,
            "WongIO",
            True,
        ),
        (
            FOOTLOOSE_URL,
            reviewed_payload(
                product_id="7547",
                product_name="Sandalias Footloose Mujeres",
                slug="sandalias-footloose-mujeres-fch-nz006-marie-delux",
                seller_name="Inversiones Rubin's SAC",
            ),
            parse_footloose_products,
            "Inversiones Rubin's SAC",
            False,
        ),
        (
            CASAIDEAS_URL,
            reviewed_payload(
                product_id="2240",
                product_name="Plumon Microfibra Doble",
                slug="casa-dormitorio-plumon-micro-doble",
                seller_name="Casaideas Perú",
            ),
            parse_casaideas_products,
            "Casaideas Perú",
            True,
        ),
    ],
)
def test_new_stores_require_exact_own_seller_and_fixed_unit(
    source_url: str,
    payload: list[dict],
    parser,
    expected_seller: str,
    location_flag: bool,
) -> None:
    observations = [
        PriceObservation(**value)
        for value in parser(payload, source_url, None, OBSERVED_AT)
    ]

    assert observations
    assert {value.seller_name for value in observations} == {expected_seller}
    assert all(value.currency == "PEN" for value in observations)
    assert all(not value.is_marketplace for value in observations)
    assert all(
        ("delivery_location_confirmation" in value.quality_flags) is location_flag
        for value in observations
    )
    assert all(
        not assess_quality_flags(value.quality_flags).blocking_quality_flags
        for value in observations
    )


def test_wong_blocks_variable_weight_price_basis() -> None:
    payload = reviewed_payload(
        product_id="6437",
        product_name="Producto por peso",
        slug="espumante-brut-zonin-prosecco-doc-botella-750ml-433571",
        seller_name="WongIO",
        measurement_unit="kg",
    )
    observation = PriceObservation(
        **parse_wong_products(payload, WONG_URL, None, OBSERVED_AT)[0]
    )

    assert "unsupported_price_basis" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags


def test_casaideas_blocks_ambiguous_seller_identity() -> None:
    payload = reviewed_payload(
        product_id="2240",
        product_name="Plumon Microfibra Doble",
        slug="casa-dormitorio-plumon-micro-doble",
        seller_name="Vendedor desconocido",
    )
    observation = PriceObservation(
        **parse_casaideas_products(payload, CASAIDEAS_URL, None, OBSERVED_AT)[0]
    )

    assert "ambiguous_casaideas_seller_identity" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags


@pytest.mark.parametrize(
    ("adapter", "spider"),
    [
        (WongAdapter, WongProductSpider),
        (FootlooseAdapter, FootlooseProductSpider),
        (CasaideasAdapter, CasaideasProductSpider),
    ],
)
def test_second_expansion_stores_remain_hourly_and_bounded(
    adapter: type,
    spider: type,
) -> None:
    assert adapter.policy.enabled is True
    assert adapter.policy.minimum_interval_minutes == 60
    assert adapter.policy.max_targets_per_run == 10
    assert adapter.policy.requires_explicit_product_url is True
    assert spider.max_targets == 10
    assert adapter.discovery_sources[0].daily_approval_limit == 40
    assert adapter.discovery_sources[0].active_product_limit == 500
