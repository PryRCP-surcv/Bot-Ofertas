"""Store-specific and reusable bounded spiders."""

from bot_ofertas.crawling.spiders.base_product import (
    BoundedProductSpider,
    JsonProductSpider,
)
from bot_ofertas.crawling.spiders.coolbox_product import CoolboxProductSpider
from bot_ofertas.crawling.spiders.oechsle_product import OechsleProductSpider
from bot_ofertas.crawling.spiders.promart_product import PromartProductSpider

__all__ = [
    "BoundedProductSpider",
    "CoolboxProductSpider",
    "JsonProductSpider",
    "OechsleProductSpider",
    "PromartProductSpider",
]
