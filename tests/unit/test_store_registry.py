import pytest

from bot_ofertas.crawling.spiders.base_product import BoundedProductSpider
from bot_ofertas.stores import (
    StoreAdapter,
    StoreDisabledError,
    StorePolicy,
    StoreRegistrationError,
    StoreRegistry,
    StoreRegistryError,
    UnsupportedStoreError,
    build_store_registry,
)
from bot_ofertas.stores import registry as registry_module


class ExampleSpider(BoundedProductSpider):
    name = "example_product"
    store_slug = "example"
    display_name = "Example"
    allowed_domains = ["shop.example.test"]
    request_hosts = frozenset({"shop.example.test"})
    max_targets = 20

    def normalize_product_url(self, url):
        return url

    def build_request_url(self, source_url):
        return source_url

    def parse_payload(self, **_kwargs):
        return []


class ExampleAdapter(StoreAdapter):
    slug = "example"
    display_name = "Example"
    hosts = frozenset({"shop.example.test"})
    policy = StorePolicy(enabled=True)
    spider_class = ExampleSpider

    def normalize_product_url(self, url: str) -> str:
        return url.split("?", maxsplit=1)[0]


class DisabledAdapter(StoreAdapter):
    slug = "disabled"
    display_name = "Disabled"
    hosts = frozenset({"disabled.example.test"})
    policy = StorePolicy(enabled=False, notes="Policy review pending.")

    class DisabledSpider(BoundedProductSpider):
        name = "disabled_product"
        store_slug = "disabled"
        display_name = "Disabled"
        allowed_domains = ["disabled.example.test"]
        request_hosts = frozenset({"disabled.example.test"})
        max_targets = 20

        def normalize_product_url(self, url):
            return url

        def build_request_url(self, source_url):
            return source_url

        def parse_payload(self, **_kwargs):
            return []

    spider_class = DisabledSpider

    def normalize_product_url(self, url: str) -> str:
        return url


def test_builtin_registry_detects_and_normalizes_coolbox_urls() -> None:
    registry = build_store_registry(include_plugins=False)

    adapter, canonical_url = registry.resolve("https://coolbox.pe/barra-sonido/p?utm_source=test")

    assert adapter.slug == "coolbox"
    assert canonical_url == "https://www.coolbox.pe/barra-sonido/p"
    assert registry.enabled_store_slugs == frozenset(
        {
            "cassinelli",
            "casaideas",
            "coolbox",
            "curacao",
            "efe",
            "estilos",
            "falabella",
            "footloose",
            "metro",
            "oechsle",
            "plazavea",
            "promart",
            "topitop",
            "tottus",
            "vega",
            "wong",
        }
    )

    oechsle, oechsle_url = registry.resolve(
        "https://oechsle.pe/producto-demo/p?utm_source=test"
    )
    assert oechsle_url == "https://www.oechsle.pe/producto-demo/p"
    assert oechsle.policy.minimum_interval_minutes == 60
    assert oechsle.policy.max_targets_per_run == 5

    promart, promart_url = registry.resolve(
        "https://promart.pe/producto-demo/p?utm_source=test"
    )
    assert promart_url == "https://www.promart.pe/producto-demo/p"
    assert promart.policy.enabled is True
    assert promart.policy.minimum_interval_minutes == 60
    assert promart.policy.max_targets_per_run == 5

    efe, efe_url = registry.resolve(
        "https://efe.com.pe/cafetera-demo.html?utm_source=test"
    )
    assert efe_url == "https://www.efe.com.pe/cafetera-demo.html"
    assert efe.policy.max_targets_per_run == 5

    curacao, curacao_url = registry.resolve(
        "https://lacuracao.pe/cafetera-demo.html#detalle"
    )
    assert curacao_url == "https://www.lacuracao.pe/cafetera-demo.html"
    assert curacao.policy.max_targets_per_run == 5

    cassinelli, cassinelli_url = registry.resolve(
        "https://cassinelli.com/porcelanato-demo/p?utm_source=test"
    )
    assert cassinelli_url == "https://www.cassinelli.com/porcelanato-demo/p"
    assert cassinelli.policy.max_targets_per_run == 10

    plazavea, plazavea_url = registry.resolve(
        "https://plazavea.com.pe/agua-demo/p?utm_source=test"
    )
    assert plazavea_url == "https://www.plazavea.com.pe/agua-demo/p"
    assert plazavea.policy.max_targets_per_run == 5

    topitop, topitop_url = registry.resolve(
        "https://topitop.pe/casaca-demo/p#detalle"
    )
    assert topitop_url == "https://www.topitop.pe/casaca-demo/p"
    assert topitop.policy.max_targets_per_run == 10

    vega, vega_url = registry.resolve(
        "https://vega.pe/gaseosa-demo/p?utm_source=test"
    )
    assert vega_url == "https://www.vega.pe/gaseosa-demo/p"
    assert vega.policy.max_targets_per_run == 5

    estilos, estilos_url = registry.resolve(
        "https://estilos.com.pe/cb008923-326/p?utm_source=test"
    )
    assert estilos_url == "https://www.estilos.com.pe/cb008923-326/p"
    assert estilos.policy.max_targets_per_run == 10

    falabella, falabella_url = registry.resolve(
        "https://falabella.com.pe/falabella-pe/product/80044160/"
        "televisor-samsung-65-mini-led/80044160?utm_source=test"
    )
    assert falabella_url == (
        "https://www.falabella.com.pe/falabella-pe/product/80044160/"
        "televisor-samsung-65-mini-led/80044160"
    )
    assert falabella.policy.max_targets_per_run == 10

    metro, metro_url = registry.resolve(
        "https://metro.pe/miniganchos-multiusos-pack-6-un-2/p?utm_source=test"
    )
    assert metro_url == (
        "https://www.metro.pe/miniganchos-multiusos-pack-6-un-2/p"
    )
    assert metro.policy.max_targets_per_run == 10

    tottus, tottus_url = registry.resolve(
        "https://tottus.com.pe/tottus-pe/articulo/100/"
        "producto-demo/101?utm_source=test"
    )
    assert tottus_url == (
        "https://www.tottus.com.pe/tottus-pe/articulo/100/producto-demo/101"
    )
    assert tottus.policy.max_targets_per_run == 10

    wong, wong_url = registry.resolve(
        "https://wong.pe/producto-demo/p?utm_source=test"
    )
    assert wong_url == "https://www.wong.pe/producto-demo/p"
    assert wong.policy.max_targets_per_run == 10

    footloose, footloose_url = registry.resolve(
        "https://footloose.pe/zapatilla-demo/p?utm_source=test"
    )
    assert footloose_url == "https://www.footloose.pe/zapatilla-demo/p"
    assert footloose.policy.max_targets_per_run == 10

    casaideas, casaideas_url = registry.resolve(
        "https://casaideas.com.pe/producto-demo/p?utm_source=test"
    )
    assert casaideas_url == "https://www.casaideas.com.pe/producto-demo/p"
    assert casaideas.policy.max_targets_per_run == 10


def test_registry_resolves_registered_hosts_without_guessing() -> None:
    registry = StoreRegistry([ExampleAdapter()])

    adapter, canonical_url = registry.resolve("https://shop.example.test/product?campaign=1")

    assert adapter.slug == "example"
    assert canonical_url == "https://shop.example.test/product"

    with pytest.raises(UnsupportedStoreError, match="no existe un adaptador"):
        registry.detect("https://almost-shop.example.test/product")


def test_registry_rejects_disabled_and_conflicting_adapters() -> None:
    registry = StoreRegistry([ExampleAdapter(), DisabledAdapter()])

    with pytest.raises(StoreDisabledError, match="deshabilitada"):
        registry.detect("https://disabled.example.test/product")

    assert (
        registry.detect(
            "https://disabled.example.test/product",
            require_enabled=False,
        ).slug
        == "disabled"
    )

    class DuplicateHostAdapter(StoreAdapter):
        slug = "other"
        display_name = "Other"
        hosts = frozenset({"shop.example.test"})
        policy = StorePolicy(enabled=True)

        class OtherSpider(BoundedProductSpider):
            name = "other_product"
            store_slug = "other"
            display_name = "Other"
            allowed_domains = ["shop.example.test"]
            request_hosts = frozenset({"shop.example.test"})
            max_targets = 20

            def normalize_product_url(self, url):
                return url

            def build_request_url(self, source_url):
                return source_url

            def parse_payload(self, **_kwargs):
                return []

        spider_class = OtherSpider

        def normalize_product_url(self, url: str) -> str:
            return url

    with pytest.raises(StoreRegistrationError, match="hostname already registered"):
        registry.register(DuplicateHostAdapter())


def test_plugin_discovery_keeps_valid_adapters_and_reports_broken_ones(
    monkeypatch,
) -> None:
    class EntryPoint:
        def __init__(self, name, loader) -> None:
            self.name = name
            self._loader = loader

        def load(self):
            return self._loader()

    def broken_loader():
        raise RuntimeError("broken plugin")

    entries = [
        EntryPoint("example", lambda: ExampleAdapter),
        EntryPoint("broken", broken_loader),
    ]
    monkeypatch.setattr(
        registry_module.metadata,
        "entry_points",
        lambda **_kwargs: entries,
    )

    registry = build_store_registry()

    assert registry.get("example").display_name == "Example"
    assert len(registry.plugin_errors) == 1
    assert "broken plugin" in registry.plugin_errors[0]


def test_registry_revalidates_the_canonical_url(monkeypatch) -> None:
    adapter = ExampleAdapter()
    registry = StoreRegistry([adapter])
    monkeypatch.setattr(
        adapter,
        "normalize_product_url",
        lambda _url: "http://untrusted.example.test/product",
    )

    with pytest.raises(StoreRegistryError, match="URL HTTPS"):
        registry.resolve("https://shop.example.test/product")
