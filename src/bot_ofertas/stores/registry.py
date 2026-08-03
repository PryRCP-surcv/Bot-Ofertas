"""Store adapter registration, plugin discovery, and URL resolution."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from importlib import metadata
from urllib.parse import urlsplit

from bot_ofertas.crawling.spiders.base_product import BoundedProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy

STORE_ADAPTER_ENTRY_POINT = "bot_ofertas.store_adapters"
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class StoreRegistryError(ValueError):
    """Base error for invalid or unsupported store integrations."""


class StoreRegistrationError(StoreRegistryError):
    """Raised when an adapter conflicts with or violates the registry contract."""


class UnsupportedStoreError(StoreRegistryError):
    """Raised when no registered adapter owns a URL or store slug."""


class StoreDisabledError(StoreRegistryError):
    """Raised when an adapter exists but its policy does not allow crawling."""


class StoreRegistry:
    """In-memory registry with unambiguous ownership of exact hostnames."""

    def __init__(self, adapters: Iterable[StoreAdapter] = ()) -> None:
        self._adapters: dict[str, StoreAdapter] = {}
        self._hosts: dict[str, str] = {}
        self._plugin_errors: list[str] = []
        for adapter in adapters:
            self.register(adapter)

    @property
    def adapters(self) -> tuple[StoreAdapter, ...]:
        return tuple(self._adapters[slug] for slug in sorted(self._adapters))

    @property
    def enabled_adapters(self) -> tuple[StoreAdapter, ...]:
        return tuple(adapter for adapter in self.adapters if adapter.policy.enabled)

    @property
    def enabled_store_slugs(self) -> frozenset[str]:
        return frozenset(adapter.slug for adapter in self.enabled_adapters)

    @property
    def plugin_errors(self) -> tuple[str, ...]:
        return tuple(self._plugin_errors)

    def register(self, adapter: StoreAdapter) -> None:
        """Register one adapter, rejecting duplicate slugs or hostname ownership."""

        if not isinstance(adapter, StoreAdapter):
            raise StoreRegistrationError("store adapters must extend StoreAdapter")

        slug = getattr(adapter, "slug", "").strip().lower()
        display_name = getattr(adapter, "display_name", "").strip()
        raw_hosts = getattr(adapter, "hosts", ())
        policy = getattr(adapter, "policy", None)
        spider_class = getattr(adapter, "spider_class", None)

        if not _SLUG_PATTERN.fullmatch(slug):
            raise StoreRegistrationError(
                "adapter slug must contain only lowercase letters, numbers, '-' or '_'"
            )
        if slug in self._adapters:
            raise StoreRegistrationError(f"duplicate store slug: {slug}")
        if not display_name:
            raise StoreRegistrationError(f"adapter {slug!r} must declare display_name")
        if not isinstance(policy, StorePolicy):
            raise StoreRegistrationError(f"adapter {slug!r} must declare a StorePolicy")
        if not isinstance(spider_class, type) or not issubclass(
            spider_class,
            BoundedProductSpider,
        ):
            raise StoreRegistrationError(
                f"adapter {slug!r} must declare a BoundedProductSpider subclass"
            )
        if policy.enabled and not policy.requires_explicit_product_url:
            raise StoreRegistrationError(
                f"enabled adapter {slug!r} must require explicit product URLs"
            )
        spider_store_slug = getattr(spider_class, "store_slug", "").strip().lower()
        if spider_store_slug != slug:
            raise StoreRegistrationError(
                f"adapter {slug!r} and its spider must declare the same store_slug"
            )
        spider_max_targets = getattr(spider_class, "max_targets", 0)
        if (
            not isinstance(spider_max_targets, int)
            or isinstance(spider_max_targets, bool)
            or spider_max_targets < policy.max_targets_per_run
        ):
            raise StoreRegistrationError(f"adapter {slug!r} policy exceeds its spider target limit")

        hosts = _normalize_hosts(raw_hosts)
        discovery_sources = getattr(adapter, "discovery_sources", ())
        if not isinstance(discovery_sources, tuple):
            raise StoreRegistrationError(
                f"adapter {slug!r} discovery_sources must be a tuple"
            )
        source_keys: set[str] = set()
        source_urls: set[str] = set()
        for source in discovery_sources:
            if not isinstance(source, DiscoverySourceSpec):
                raise StoreRegistrationError(
                    f"adapter {slug!r} has an invalid discovery source"
                )
            source_host = (urlsplit(source.url).hostname or "").rstrip(".").lower()
            if source_host not in hosts:
                raise StoreRegistrationError(
                    f"adapter {slug!r} discovery source belongs to an unowned host"
                )
            if source.key in source_keys:
                raise StoreRegistrationError(
                    f"adapter {slug!r} has duplicate discovery source key {source.key!r}"
                )
            if source.url in source_urls:
                raise StoreRegistrationError(
                    f"adapter {slug!r} has duplicate discovery source URL"
                )
            try:
                re.compile(source.child_path_pattern)
            except re.error as exc:
                raise StoreRegistrationError(
                    f"adapter {slug!r} has an invalid discovery child pattern"
                ) from exc
            source_keys.add(source.key)
            source_urls.add(source.url)
        request_hosts = _normalize_hosts(getattr(spider_class, "request_hosts", ()))
        allowed_domains = _normalize_hosts(getattr(spider_class, "allowed_domains", ()))
        if not hosts:
            raise StoreRegistrationError(f"adapter {slug!r} must own at least one hostname")
        if not request_hosts:
            raise StoreRegistrationError(
                f"adapter {slug!r} spider must declare reviewed request_hosts"
            )
        uncovered_request_hosts = sorted(
            request_host
            for request_host in request_hosts
            if not any(
                request_host == allowed_domain or request_host.endswith(f".{allowed_domain}")
                for allowed_domain in allowed_domains
            )
        )
        if uncovered_request_hosts:
            raise StoreRegistrationError(
                f"adapter {slug!r} request_hosts are not covered by allowed_domains: "
                f"{', '.join(uncovered_request_hosts)}"
            )
        conflicts = sorted(host for host in hosts if host in self._hosts)
        if conflicts:
            owners = ", ".join(f"{host} ({self._hosts[host]})" for host in conflicts)
            raise StoreRegistrationError(f"hostname already registered: {owners}")

        self._adapters[slug] = adapter
        for host in hosts:
            self._hosts[host] = slug

    def get(self, slug: str, *, require_enabled: bool = True) -> StoreAdapter:
        normalized_slug = slug.strip().lower()
        adapter = self._adapters.get(normalized_slug)
        if adapter is None:
            supported = ", ".join(item.slug for item in self.adapters) or "ninguna"
            raise UnsupportedStoreError(
                f"tienda no registrada: {normalized_slug or slug!r}; registradas: {supported}"
            )
        if require_enabled and not adapter.policy.enabled:
            raise StoreDisabledError(
                f"{adapter.display_name} está registrada pero deshabilitada por política"
            )
        return adapter

    def detect(self, url: str, *, require_enabled: bool = True) -> StoreAdapter:
        """Resolve an exact registered hostname without guessing similar domains."""

        candidate = url.strip()
        try:
            parts = urlsplit(candidate)
            hostname = (parts.hostname or "").rstrip(".").lower()
            port = parts.port
        except ValueError as exc:
            raise UnsupportedStoreError("la URL no tiene un hostname válido") from exc

        if (
            parts.scheme.lower() != "https"
            or not hostname
            or parts.username is not None
            or parts.password is not None
            or port not in (None, 443)
        ):
            raise UnsupportedStoreError(
                "se requiere una URL HTTPS pública sin credenciales ni puerto no estándar"
            )

        slug = self._hosts.get(hostname)
        if slug is None:
            supported_hosts = sorted(
                host
                for host, owner_slug in self._hosts.items()
                if not require_enabled or self._adapters[owner_slug].policy.enabled
            )
            supported = ", ".join(supported_hosts) or "ninguno"
            raise UnsupportedStoreError(
                f"no existe un adaptador para {hostname}; dominios habilitados: {supported}"
            )
        return self.get(slug, require_enabled=require_enabled)

    def resolve(
        self,
        url: str,
        *,
        require_enabled: bool = True,
    ) -> tuple[StoreAdapter, str]:
        adapter = self.detect(url, require_enabled=require_enabled)
        canonical_url = adapter.normalize_product_url(url)
        if not isinstance(canonical_url, str) or canonical_url != canonical_url.strip():
            raise StoreRegistryError(
                f"el adaptador {adapter.slug!r} devolvió una URL canónica inválida"
            )

        canonical_adapter = self.detect(
            canonical_url,
            require_enabled=require_enabled,
        )
        if canonical_adapter.slug != adapter.slug:
            raise StoreRegistryError(f"el adaptador {adapter.slug!r} cambió la URL a otra tienda")
        if adapter.normalize_product_url(canonical_url) != canonical_url:
            raise StoreRegistryError(
                f"el adaptador {adapter.slug!r} no canonicaliza URLs de forma estable"
            )
        return adapter, canonical_url

    def _record_plugin_error(self, message: str) -> None:
        self._plugin_errors.append(" ".join(message.split())[:500])


def _normalize_hosts(raw_hosts: object) -> frozenset[str]:
    if isinstance(raw_hosts, str):
        raise StoreRegistrationError("adapter hosts must be a collection, not a string")
    try:
        candidates = tuple(raw_hosts)  # type: ignore[arg-type]
    except TypeError as exc:
        raise StoreRegistrationError("adapter hosts must be an iterable") from exc

    normalized: set[str] = set()
    for raw_host in candidates:
        if not isinstance(raw_host, str):
            raise StoreRegistrationError("adapter hostnames must be strings")
        host = raw_host.strip().rstrip(".").lower()
        if not host or "://" in host or "/" in host or ":" in host or host.startswith("."):
            raise StoreRegistrationError(f"invalid adapter hostname: {raw_host!r}")
        normalized.add(host)
    return frozenset(normalized)


def _plugin_adapter(loaded: object) -> StoreAdapter:
    if isinstance(loaded, StoreAdapter):
        return loaded
    if isinstance(loaded, type) and issubclass(loaded, StoreAdapter):
        return loaded()
    if callable(loaded):
        resolved = loaded()
        if isinstance(resolved, StoreAdapter):
            return resolved
    raise StoreRegistrationError(
        "entry point must load a StoreAdapter instance, subclass, or zero-argument factory"
    )


def build_store_registry(*, include_plugins: bool = True) -> StoreRegistry:
    """Build the built-in registry and optionally add installed adapter plugins."""

    from bot_ofertas.stores.casaideas import CasaideasAdapter
    from bot_ofertas.stores.cassinelli import CassinelliAdapter
    from bot_ofertas.stores.coolbox import CoolboxAdapter
    from bot_ofertas.stores.curacao import CuracaoAdapter
    from bot_ofertas.stores.efe import EfeAdapter
    from bot_ofertas.stores.estilos import EstilosAdapter
    from bot_ofertas.stores.falabella import FalabellaAdapter
    from bot_ofertas.stores.footloose import FootlooseAdapter
    from bot_ofertas.stores.metro import MetroAdapter
    from bot_ofertas.stores.oechsle import OechsleAdapter
    from bot_ofertas.stores.plazavea import PlazaVeaAdapter
    from bot_ofertas.stores.promart import PromartAdapter
    from bot_ofertas.stores.topitop import TopitopAdapter
    from bot_ofertas.stores.tottus import TottusAdapter
    from bot_ofertas.stores.vega import VegaAdapter
    from bot_ofertas.stores.wong import WongAdapter

    registry = StoreRegistry(
        [
            CassinelliAdapter(),
            CasaideasAdapter(),
            CoolboxAdapter(),
            CuracaoAdapter(),
            EfeAdapter(),
            EstilosAdapter(),
            FalabellaAdapter(),
            FootlooseAdapter(),
            MetroAdapter(),
            OechsleAdapter(),
            PlazaVeaAdapter(),
            PromartAdapter(),
            TopitopAdapter(),
            TottusAdapter(),
            VegaAdapter(),
            WongAdapter(),
        ]
    )
    if not include_plugins:
        return registry

    for entry_point in metadata.entry_points(group=STORE_ADAPTER_ENTRY_POINT):
        try:
            registry.register(_plugin_adapter(entry_point.load()))
        except Exception as exc:
            registry._record_plugin_error(  # noqa: SLF001 - kept private to registry assembly.
                f"{entry_point.name}: {type(exc).__name__}: {exc}"
            )
    return registry


@cache
def get_store_registry() -> StoreRegistry:
    """Return one immutable-by-convention application registry."""

    return build_store_registry()


def resolve_store(url: str) -> tuple[StoreAdapter, str]:
    return get_store_registry().resolve(url)


__all__ = [
    "STORE_ADAPTER_ENTRY_POINT",
    "StoreDisabledError",
    "StoreRegistrationError",
    "StoreRegistry",
    "StoreRegistryError",
    "UnsupportedStoreError",
    "build_store_registry",
    "get_store_registry",
    "resolve_store",
]
