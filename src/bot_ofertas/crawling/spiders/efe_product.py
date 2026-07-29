"""Bounded EFE product spider."""

from bot_ofertas.crawling.efe import EFE_HOSTS, EFE_PARSER_CONFIG
from bot_ofertas.crawling.spiders.magento_product import MagentoProductSpider


class EfeProductSpider(MagentoProductSpider):
    name = "efe_product"
    store_slug = "efe"
    display_name = "EFE"
    allowed_domains = ["efe.com.pe", "www.efe.com.pe"]
    request_hosts = EFE_HOSTS
    max_targets = 5
    parser_config = EFE_PARSER_CONFIG


__all__ = ["EfeProductSpider"]
