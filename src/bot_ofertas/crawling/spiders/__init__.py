"""Store-specific and reusable bounded spiders."""

from bot_ofertas.crawling.spiders.base_product import (
    BoundedProductSpider,
    JsonProductSpider,
)
from bot_ofertas.crawling.spiders.cassinelli_product import CassinelliProductSpider
from bot_ofertas.crawling.spiders.coolbox_product import CoolboxProductSpider
from bot_ofertas.crawling.spiders.curacao_product import CuracaoProductSpider
from bot_ofertas.crawling.spiders.efe_product import EfeProductSpider
from bot_ofertas.crawling.spiders.magento_product import MagentoProductSpider
from bot_ofertas.crawling.spiders.oechsle_product import OechsleProductSpider
from bot_ofertas.crawling.spiders.promart_product import PromartProductSpider

__all__ = [
    "BoundedProductSpider",
    "CassinelliProductSpider",
    "CoolboxProductSpider",
    "CuracaoProductSpider",
    "EfeProductSpider",
    "JsonProductSpider",
    "MagentoProductSpider",
    "OechsleProductSpider",
    "PromartProductSpider",
]
