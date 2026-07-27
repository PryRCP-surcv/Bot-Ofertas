"""Store-specific and reusable bounded spiders."""

from bot_ofertas.crawling.spiders.base_product import (
    BoundedProductSpider,
    JsonProductSpider,
)
from bot_ofertas.crawling.spiders.coolbox_product import CoolboxProductSpider

__all__ = ["BoundedProductSpider", "CoolboxProductSpider", "JsonProductSpider"]
