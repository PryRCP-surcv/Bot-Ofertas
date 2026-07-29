from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bot_ofertas.crawling.cassinelli import (
    normalize_cassinelli_product_url,
    parse_cassinelli_products,
)
from bot_ofertas.crawling.curacao import (
    normalize_curacao_product_url,
    parse_curacao_product,
)
from bot_ofertas.crawling.efe import normalize_efe_product_url, parse_efe_product
from bot_ofertas.crawling.magento import MagentoPayloadError
from bot_ofertas.domain import PriceObservation

OBSERVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
EFE_URL = "https://www.efe.com.pe/cafetera-thomas-demo.html"
CURACAO_URL = "https://www.lacuracao.pe/cafetera-thomas-demo.html"


def _magento_html(
    *,
    url: str,
    seller: str,
    price: str = "89.00",
    old_price: str = "159.00",
) -> str:
    product = {
        "@context": "https://schema.org/",
        "@graph": [
            {
                "@type": "Product",
                "@id": f"{url}#product",
                "name": "Cafetera Thomas 12TZS TH-138I",
                "sku": "CF-TH138IN",
                "url": url,
                "brand": {"@type": "Brand", "name": "Thomas"},
                "offers": {
                    "@type": "Offer",
                    "url": url,
                    "priceCurrency": "PEN",
                    "price": price,
                    "itemCondition": "https://schema.org/NewCondition",
                    "availability": "https://schema.org/InStock",
                    "seller": {"@type": "Organization", "name": seller},
                },
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home"},
                    {"@type": "ListItem", "position": 2, "name": "Electrohogar"},
                    {"@type": "ListItem", "position": 3, "name": "Cafeteras"},
                    {
                        "@type": "ListItem",
                        "position": 4,
                        "name": "Cafetera Thomas 12TZS TH-138I",
                    },
                ],
            },
        ],
    }
    return f"""<!doctype html><html><head>
      <script type="application/ld+json">{json.dumps(product)}</script>
      </head><body>
      <div data-role="priceBox" data-product-id="12">
        <span data-price-type="finalPrice" data-price-amount="{price}"></span>
        <span data-price-type="oldPrice" data-price-amount="{old_price}"></span>
      </div></body></html>"""


def test_efe_jsonld_parser_preserves_exact_product_seller_and_prices() -> None:
    values = parse_efe_product(
        _magento_html(url=EFE_URL, seller="Tiendas EFE"),
        EFE_URL,
        None,
        OBSERVED_AT,
    )
    observation = PriceObservation(**values[0])

    assert observation.store_slug == "efe"
    assert observation.external_product_id == "12"
    assert observation.sku == "CF-TH138IN"
    assert observation.seller_name == "Tiendas EFE"
    assert observation.is_marketplace is False
    assert observation.price == Decimal("89.00")
    assert observation.list_price == Decimal("159.00")
    assert observation.currency == "PEN"
    assert observation.category_path == ["Electrohogar", "Cafeteras"]
    assert observation.quality_flags == []


def test_curacao_parser_recognizes_own_seller_and_canonical_url() -> None:
    canonical = normalize_curacao_product_url(
        "https://lacuracao.pe/cafetera-thomas-demo.html?utm_source=test#detalle"
    )
    values = parse_curacao_product(
        _magento_html(url=CURACAO_URL, seller="La Curacao"),
        canonical,
        None,
        OBSERVED_AT,
    )
    observation = PriceObservation(**values[0])

    assert canonical == CURACAO_URL
    assert observation.store_slug == "curacao"
    assert observation.is_marketplace is False
    assert observation.availability.value == "in_stock"


def test_magento_parser_marks_marketplace_and_html_price_mismatch() -> None:
    html = _magento_html(
        url=EFE_URL,
        seller="Vendedor externo",
        price="89.00",
    ).replace('data-price-amount="89.00"', 'data-price-amount="79.00"')
    observation = PriceObservation(
        **parse_efe_product(html, EFE_URL, None, OBSERVED_AT)[0]
    )

    assert observation.is_marketplace is True
    assert observation.price == Decimal("89.00")
    assert "jsonld_html_price_mismatch" in observation.quality_flags


def test_magento_parser_rejects_ambiguous_or_wrong_product_evidence() -> None:
    html = _magento_html(
        url="https://www.efe.com.pe/otro-producto.html",
        seller="Tiendas EFE",
    )

    with pytest.raises(MagentoPayloadError, match="one matching"):
        parse_efe_product(html, EFE_URL, None, OBSERVED_AT)


@pytest.mark.parametrize(
    "normalizer,url",
    [
        (normalize_efe_product_url, "http://www.efe.com.pe/demo.html"),
        (normalize_efe_product_url, "https://www.efe.com.pe/categoria/demo.html"),
        (normalize_curacao_product_url, "https://example.com/demo.html"),
        (normalize_curacao_product_url, "https://www.lacuracao.pe/checkout"),
    ],
)
def test_magento_normalizers_reject_non_product_or_unreviewed_targets(
    normalizer,
    url: str,
) -> None:
    with pytest.raises(ValueError):
        normalizer(url)


def test_cassinelli_uses_public_vtex_and_flags_variable_measure_basis() -> None:
    source_url = normalize_cassinelli_product_url(
        "https://cassinelli.com/porcelanato-demo/p?campaign=1"
    )
    payload = [
        {
            "productId": "100",
            "productName": "Porcelanato Demo",
            "brand": "Marca Demo",
            "unitOriginal": "m2",
            "items": [
                {
                    "itemId": "sku-100",
                    "nameComplete": "Porcelanato Demo Gris",
                    "sellers": [
                        {
                            "sellerId": "1",
                            "sellerName": "VTEX",
                            "commertialOffer": {
                                "IsAvailable": True,
                                "AvailableQuantity": 12,
                                "Price": 49,
                                "ListPrice": 69,
                                "Installments": [],
                            },
                        }
                    ],
                }
            ],
        }
    ]
    observation = PriceObservation(
        **parse_cassinelli_products(
            payload,
            source_url,
            None,
            OBSERVED_AT,
        )[0]
    )

    assert source_url == "https://www.cassinelli.com/porcelanato-demo/p"
    assert observation.store_slug == "cassinelli"
    assert observation.is_marketplace is False
    assert observation.price == Decimal("49")
    assert "variable_measure_price_basis" in observation.quality_flags
