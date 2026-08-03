import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot_ofertas.crawling.estilos import (
    build_estilos_catalog_url,
    normalize_estilos_product_url,
    parse_estilos_products,
)
from bot_ofertas.crawling.metro import (
    build_metro_catalog_url,
    normalize_metro_product_url,
    parse_metro_products,
)
from bot_ofertas.crawling.spiders.estilos_product import EstilosProductSpider
from bot_ofertas.crawling.spiders.metro_product import MetroProductSpider
from bot_ofertas.crawling.spiders.tottus_product import TottusProductSpider
from bot_ofertas.crawling.tottus import (
    TottusPayloadError,
    normalize_tottus_product_url,
    parse_tottus_product,
)
from bot_ofertas.detection import assess_quality_flags
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.estilos import EstilosAdapter
from bot_ofertas.stores.metro import MetroAdapter
from bot_ofertas.stores.tottus import TottusAdapter

OBSERVED_AT = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
ESTILOS_URL = "https://www.estilos.com.pe/cb008923-326/p"
METRO_URL = "https://www.metro.pe/miniganchos-multiusos-pack-6-un-2/p"
TOTTUS_URL = (
    "https://www.tottus.com.pe/tottus-pe/articulo/150323334/"
    "lavadora-samsung-wa40f13e4cpe-ecobubble-13kg/150323336"
)
VTEX_FIXTURE = Path(__file__).parents[1] / "fixtures" / "phase6_2_catalog_products.json"


def estilos_payload() -> list[dict]:
    payload = copy.deepcopy(
        json.loads(VTEX_FIXTURE.read_text(encoding="utf-8"))["topitop"]
    )
    payload[0]["productId"] = "326"
    payload[0]["productName"] = "Producto Estilos de prueba"
    payload[0]["linkText"] = "cb008923-326"
    for item in payload[0]["items"]:
        for seller in item["sellers"]:
            seller["sellerId"] = "1"
            seller["sellerName"] = "ESTILOS PERU"
    return payload


def metro_payload(*, measurement_unit: str = "un") -> list[dict]:
    payload = copy.deepcopy(
        json.loads(VTEX_FIXTURE.read_text(encoding="utf-8"))["vega"]
    )
    payload[0]["productId"] = "7924"
    payload[0]["productName"] = "Miniganchos Multiusos Pack 6 Un"
    payload[0]["linkText"] = "miniganchos-multiusos-pack-6-un-2"
    for item in payload[0]["items"]:
        item["measurementUnit"] = measurement_unit
        item["unitMultiplier"] = 1 if measurement_unit == "un" else 0.15
        for seller in item["sellers"]:
            seller["sellerId"] = "1"
            seller["sellerName"] = "CENCOSUD RETAIL PERU S.A."
    return payload


def tottus_html(
    *,
    sale_unit: str = "UN",
    seller_id: str = "TOTTUS_PERU",
    seller_name: str = "TOTTUS",
) -> str:
    variant = {
        "id": "150323336",
        "name": "LAVADORA ECOBUBBLE 13KG",
        "isPurchaseable": True,
        "prices": [
            {
                "crossed": False,
                "type": "internetPrice",
                "price": "999",
            },
            {
                "crossed": True,
                "type": "normalPrice",
                "price": "1,099",
            },
        ],
        "offerings": [
            {
                "sellerId": seller_id,
                "sellerName": seller_name,
                "offeringId": "150323336",
                "isActive": True,
                "sellerSkuId": "43603445",
            }
        ],
        "attributes": {
            "specifications": [
                {"id": "saleUnit", "name": "saleUnit", "value": sale_unit}
            ]
        },
        "medias": [
            {
                "mediaType": "image",
                "url": "https://media.example.test/lavadora.jpg",
            }
        ],
    }
    product_data = {
        "id": "150323334",
        "name": "Lavadora Samsung Ecobubble 13Kg",
        "brandName": "SAMSUNG",
        "slug": "lavadora-samsung-wa40f13e4cpe-ecobubble-13kg",
        "currentVariant": "150323336",
        "variants": [variant],
        "sellerInfo": {"sellerId": seller_id, "sellerName": seller_name},
        "breadCrumb": [{"name": "Electrohogar"}, {"name": "Lavadoras"}],
        "isOutOfStock": False,
    }
    next_data = {"props": {"pageProps": {"productData": product_data}}}
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product_data["name"],
        "sku": "150323336",
        "image": ["https://media.example.test/lavadora.jpg"],
        "offers": [
            {
                "@type": "Offer",
                "sku": "150323336",
                "price": "999",
                "priceCurrency": "PEN",
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": seller_name},
            },
            {
                "@type": "Offer",
                "sku": "150323336",
                "price": "1099",
                "priceCurrency": "PEN",
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": seller_name},
            },
        ],
    }
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
        f'<script id="__NEXT_DATA__">{json.dumps(next_data)}</script>'
        "</head><body></body></html>"
    )


def test_estilos_uses_exact_public_vtex_product_and_own_seller() -> None:
    canonical = normalize_estilos_product_url(ESTILOS_URL + "?utm_source=test")
    observations = [
        PriceObservation(**item)
        for item in parse_estilos_products(
            estilos_payload(),
            canonical,
            None,
            OBSERVED_AT,
        )
    ]

    assert canonical == ESTILOS_URL
    assert build_estilos_catalog_url(canonical) == (
        "https://www.estilos.com.pe/api/catalog_system/pub/products/search/"
        "cb008923-326/p"
    )
    assert observations
    assert {item.seller_name for item in observations} == {"ESTILOS PERU"}
    assert all(not item.is_marketplace for item in observations)
    assert all(
        not assess_quality_flags(item.quality_flags).blocking_quality_flags
        for item in observations
    )


def test_metro_preserves_fixed_unit_price_stock_and_own_seller() -> None:
    canonical = normalize_metro_product_url(METRO_URL + "?utm_source=test#price")
    observation = PriceObservation(
        **parse_metro_products(metro_payload(), canonical, None, OBSERVED_AT)[0]
    )

    assert canonical == METRO_URL
    assert build_metro_catalog_url(canonical) == (
        "https://www.metro.pe/api/catalog_system/pub/products/search/"
        "miniganchos-multiusos-pack-6-un-2/p"
    )
    assert observation.external_product_id == "7924"
    assert observation.seller_name == "CENCOSUD RETAIL PERU S.A."
    assert observation.currency == "PEN"
    assert observation.availability.value == "in_stock"
    assert observation.is_marketplace is False
    assert "delivery_location_confirmation" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags == ()


def test_metro_blocks_variable_weight_price_basis() -> None:
    observation = PriceObservation(
        **parse_metro_products(
            metro_payload(measurement_unit="kg"),
            METRO_URL,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert "unsupported_price_basis" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags


def test_tottus_preserves_exact_variant_seller_and_normal_price() -> None:
    canonical = normalize_tottus_product_url(TOTTUS_URL + "?utm_source=test#price")
    observation = PriceObservation(
        **parse_tottus_product(tottus_html(), canonical, None, OBSERVED_AT)[0]
    )

    assert canonical == TOTTUS_URL
    assert observation.external_product_id == "150323334"
    assert observation.sku == "150323336"
    assert observation.variant["variant_id"] == "150323336"
    assert observation.seller_id == "TOTTUS_PERU"
    assert observation.seller_name == "TOTTUS"
    assert observation.price == Decimal("999")
    assert observation.list_price == Decimal("1099")
    assert observation.currency == "PEN"
    assert observation.image_url == "https://media.example.test/lavadora.jpg"
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags == ()


def test_tottus_blocks_variable_price_basis_and_ambiguous_seller() -> None:
    unit_observation = PriceObservation(
        **parse_tottus_product(
            tottus_html(sale_unit="KG"),
            TOTTUS_URL,
            None,
            OBSERVED_AT,
        )[0]
    )
    seller_html = tottus_html(seller_id="MARKET-1", seller_name="Marketplace Demo")
    seller_html = seller_html.replace(
        '"sellerName": "Marketplace Demo", "offeringId"',
        '"sellerName": "Otro vendedor", "offeringId"',
        1,
    )
    seller_observation = PriceObservation(
        **parse_tottus_product(seller_html, TOTTUS_URL, None, OBSERVED_AT)[0]
    )

    assert "unsupported_price_basis" in unit_observation.quality_flags
    assert assess_quality_flags(unit_observation.quality_flags).blocking_quality_flags
    assert "ambiguous_tottus_seller_identity" in seller_observation.quality_flags
    assert assess_quality_flags(seller_observation.quality_flags).blocking_quality_flags


def test_tottus_rejects_an_unexpected_product_identity() -> None:
    payload = tottus_html().replace(
        '"currentVariant": "150323336"',
        '"currentVariant": "999999999"',
    )

    with pytest.raises(TottusPayloadError, match="different product or variant"):
        parse_tottus_product(payload, TOTTUS_URL, None, OBSERVED_AT)


@pytest.mark.parametrize("placeholder", ("null", "undefined"))
def test_tottus_rejects_placeholder_sitemap_slugs(placeholder: str) -> None:
    with pytest.raises(ValueError, match="explicit HTTPS"):
        normalize_tottus_product_url(
            f"https://www.tottus.com.pe/tottus-pe/articulo/100/{placeholder}/101"
        )


def test_tottus_normalizes_public_sitemap_slugs_with_encoded_spaces() -> None:
    assert normalize_tottus_product_url(
        "https://www.tottus.com.pe/tottus-pe/articulo/145809757/"
        "FUR%20DJ%20FURBLETS%20AST/145809758"
    ) == (
        "https://www.tottus.com.pe/tottus-pe/articulo/145809757/"
        "FUR%20DJ%20FURBLETS%20AST/145809758"
    )


@pytest.mark.parametrize(
    ("adapter", "spider"),
    [
        (EstilosAdapter, EstilosProductSpider),
        (MetroAdapter, MetroProductSpider),
        (TottusAdapter, TottusProductSpider),
    ],
)
def test_expansion_store_policies_remain_hourly_and_bounded(
    adapter: type,
    spider: type,
) -> None:
    assert adapter.policy.enabled is True
    assert adapter.policy.minimum_interval_minutes == 60
    assert adapter.policy.max_targets_per_run == 10
    assert adapter.policy.requires_explicit_product_url is True
    assert spider.max_targets == 10
