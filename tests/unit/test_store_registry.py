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
    assert registry.enabled_store_slugs == frozenset({"coolbox", "oechsle", "promart"})

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
