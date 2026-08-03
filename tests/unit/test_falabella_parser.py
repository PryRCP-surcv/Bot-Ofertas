import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bot_ofertas.crawling.falabella import (
    FalabellaPayloadError,
    normalize_falabella_product_url,
    parse_falabella_product,
)
from bot_ofertas.crawling.spiders.falabella_product import FalabellaProductSpider
from bot_ofertas.detection import assess_quality_flags
from bot_ofertas.domain import PriceObservation
from bot_ofertas.stores.falabella import FalabellaAdapter

OBSERVED_AT = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
FALABELLA_URL = (
    "https://www.falabella.com.pe/falabella-pe/product/80044160/"
    "televisor-samsung-65-mini-led-m70h-vision-ai-smart-tv-2026/80044160"
)


def falabella_html(
    *,
    seller_id: str = "FALABELLA_PERU",
    seller_name: str = "FALABELLA",
    offering_seller_name: str | None = None,
    currency: str = "PEN",
    current_variant: str = "80044160",
    product_out: bool = False,
    purchasable: bool = True,
    online_sellable: bool = True,
) -> str:
    offering_name = offering_seller_name or seller_name
    variant = {
        "id": "80044160",
        "name": "65 Mini LED M70H Smart TV 2026",
        "isPurchaseable": purchasable,
        "isOnlineSellable": online_sellable,
        "prices": [
            {
                "crossed": False,
                "type": "cmrPrice",
                "price": ["1,699"],
            },
            {
                "crossed": False,
                "type": "internetPrice",
                "price": ["1,799"],
            },
            {
                "crossed": True,
                "type": "normalPrice",
                "price": ["2,299"],
            },
        ],
        "offerings": [
            {
                "sellerId": seller_id,
                "sellerName": offering_name,
                "offeringId": "80044160",
                "isActive": True,
                "sellerSkuId": "80044160",
            }
        ],
        "attributes": {
            "specifications": [],
            "topSpecifications": [],
        },
        "medias": [
            {
                "mediaType": "image",
                "url": "https://media.falabella.com/falabellaPE/80044160_1/public",
            }
        ],
    }
    product_data = {
        "id": "80044160",
        "name": "Televisor Samsung 65 Mini LED M70H Vision AI Smart TV 2026",
        "brandName": "SAMSUNG",
        "slug": "televisor-samsung-65-mini-led-m70h-vision-ai-smart-tv-2026",
        "currentVariant": current_variant,
        "variants": [variant],
        "sellerInfo": {"sellerId": seller_id, "sellerName": seller_name},
        "breadCrumb": [
            {"label": "Televisores Smart TV"},
            {"label": "Tecnología - TV Televisores"},
        ],
        "attributes": {
            "specifications": [
                {
                    "id": "10_condicion_del_producto",
                    "name": "Condicion del producto",
                    "value": "Nuevo",
                },
                {"id": "6_model", "name": "Modelo", "value": "M70H"},
                {
                    "id": "saleUnit",
                    "name": "Unidad de venta",
                    "value": "UN",
                },
            ]
        },
        "isOutOfStock": product_out,
    }
    next_data = {"props": {"pageProps": {"productData": product_data}}}
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product_data["name"],
        "sku": "80044160",
        "image": [
            "https://media.falabella.com/falabellaPE/80044160_1/public"
        ],
        "offers": [
            {
                "@type": "Offer",
                "sku": "80044160",
                "price": "1799",
                "priceCurrency": currency,
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": seller_name},
            },
            {
                "@type": "Offer",
                "price": "1699",
                "priceCurrency": currency,
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": seller_name},
            },
        ],
    }
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
        f'<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script>"
        "</head><body></body></html>"
    )


def test_falabella_preserves_direct_seller_cmr_price_and_exact_sku() -> None:
    canonical = normalize_falabella_product_url(
        FALABELLA_URL.replace("www.", "") + "?utm_source=test#price"
    )
    observation = PriceObservation(
        **parse_falabella_product(
            falabella_html(),
            canonical,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert canonical == FALABELLA_URL
    assert observation.external_product_id == "80044160"
    assert observation.sku == "80044160"
    assert observation.variant["variant_id"] == "80044160"
    assert observation.seller_id == "FALABELLA_PERU"
    assert observation.seller_name == "FALABELLA"
    assert observation.is_marketplace is False
    assert observation.price == Decimal("1699")
    assert observation.list_price == Decimal("2299")
    assert observation.currency == "PEN"
    assert observation.condition.value == "new"
    assert observation.model == "M70H"
    assert observation.category_path[-1] == "Tecnología - TV Televisores"
    assert observation.image_url == (
        "https://media.falabella.com/falabellaPE/80044160_1/public"
    )
    assert "conditional_card_price" in observation.quality_flags
    assert "delivery_location_confirmation" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags == ()


def test_falabella_keeps_marketplace_evidence_but_detector_can_reject_it() -> None:
    observation = PriceObservation(
        **parse_falabella_product(
            falabella_html(
                seller_id="SCC6988",
                seller_name="RECORD TIENDA OFICIAL",
            ),
            FALABELLA_URL,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert observation.is_marketplace is True
    assert observation.seller_id == "SCC6988"
    assert "delivery_location_confirmation" not in observation.quality_flags


def test_falabella_marks_inconsistent_seller_evidence_as_blocking() -> None:
    observation = PriceObservation(
        **parse_falabella_product(
            falabella_html(offering_seller_name="OTRO VENDEDOR"),
            FALABELLA_URL,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert "ambiguous_falabella_seller_identity" in observation.quality_flags
    assert assess_quality_flags(observation.quality_flags).blocking_quality_flags


def test_falabella_rejects_non_pen_and_unexpected_variant() -> None:
    with pytest.raises(FalabellaPayloadError, match="currency"):
        parse_falabella_product(
            falabella_html(currency="USD"),
            FALABELLA_URL,
            None,
            OBSERVED_AT,
        )

    with pytest.raises(FalabellaPayloadError, match="different product or variant"):
        parse_falabella_product(
            falabella_html(current_variant="99999999"),
            FALABELLA_URL,
            None,
            OBSERVED_AT,
        )


def test_falabella_out_of_stock_suppresses_prices() -> None:
    observation = PriceObservation(
        **parse_falabella_product(
            falabella_html(
                product_out=True,
                purchasable=False,
                online_sellable=False,
            ),
            FALABELLA_URL,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert observation.availability.value == "out_of_stock"
    assert observation.price is None
    assert observation.list_price is None


@pytest.mark.parametrize("placeholder", ("null", "undefined"))
def test_falabella_rejects_placeholder_sitemap_slugs(placeholder: str) -> None:
    with pytest.raises(ValueError, match="exact HTTPS"):
        normalize_falabella_product_url(
            "https://www.falabella.com.pe/falabella-pe/product/"
            f"100/{placeholder}/101"
        )


def test_falabella_policy_is_hourly_bounded_and_uses_official_pdp_sitemap() -> None:
    source = FalabellaAdapter.discovery_sources[0]

    assert FalabellaAdapter.policy.enabled is True
    assert FalabellaAdapter.policy.minimum_interval_minutes == 60
    assert FalabellaAdapter.policy.max_targets_per_run == 10
    assert FalabellaProductSpider.max_targets == 10
    assert source.url.endswith("pdp_pe_FA_COM-index.xml")
    assert source.daily_approval_limit == 20
    assert source.active_product_limit == 300
