import pytest
from scrapy.http import HtmlResponse, TextResponse

from bot_ofertas.crawling.spiders.base_product import (
    BoundedProductSpider,
    JsonProductSpider,
    _validate_public_request_url,
)


class HtmlProductSpider(BoundedProductSpider):
    name = "html_product_test"
    store_slug = "html-test"
    display_name = "HTML Test"
    allowed_domains = ["example.test"]
    request_hosts = frozenset({"example.test"})

    def normalize_product_url(self, url):
        return url

    def build_request_url(self, source_url):
        return source_url

    def parse_payload(self, **_kwargs):
        return []


class JsonEndpointSpider(JsonProductSpider):
    name = "json_product_test"
    store_slug = "json-test"
    display_name = "JSON Test"
    allowed_domains = ["example.test"]
    request_hosts = frozenset({"example.test"})

    def normalize_product_url(self, url):
        return url

    def build_request_url(self, source_url):
        return source_url

    def parse_payload(self, **_kwargs):
        return []


def test_bounded_spider_can_decode_normal_store_html() -> None:
    spider = HtmlProductSpider(
        url="https://example.test/product",
        tracked_product_id="product-id",
        lease_token="lease-id",
    )
    response = HtmlResponse(
        url="https://example.test/product",
        body=b"<html><body><h1>Producto</h1></body></html>",
        encoding="utf-8",
    )

    assert "<h1>Producto</h1>" in spider.decode_response(response)
    assert spider.accepts_html is True


def test_json_spider_decodes_public_json_payloads() -> None:
    spider = JsonEndpointSpider(
        url="https://example.test/product",
        tracked_product_id="product-id",
        lease_token="lease-id",
    )
    response = TextResponse(
        url="https://example.test/api/product",
        body=b'{"price": 199.90}',
        encoding="utf-8",
    )

    assert spider.decode_response(response) == {"price": 199.9}
    assert spider.accepts_html is False


def test_request_url_must_remain_on_a_reviewed_https_host() -> None:
    assert (
        _validate_public_request_url(
            "https://api.example.test/public/product?id=1",
            frozenset({"api.example.test"}),
        )
        == "https://api.example.test/public/product?id=1"
    )

    with pytest.raises(ValueError, match="reviewed hostname"):
        _validate_public_request_url(
            "https://unreviewed.example.test/product",
            frozenset({"api.example.test"}),
        )
