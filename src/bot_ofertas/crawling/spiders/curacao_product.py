"""Bounded La Curacao product spider."""

from bot_ofertas.crawling.curacao import CURACAO_HOSTS, CURACAO_PARSER_CONFIG
from bot_ofertas.crawling.spiders.magento_product import MagentoProductSpider


class CuracaoProductSpider(MagentoProductSpider):
    name = "curacao_product"
    store_slug = "curacao"
    display_name = "La Curacao"
    allowed_domains = ["lacuracao.pe", "www.lacuracao.pe"]
    request_hosts = CURACAO_HOSTS
    max_targets = 5
    parser_config = CURACAO_PARSER_CONFIG


__all__ = ["CuracaoProductSpider"]
