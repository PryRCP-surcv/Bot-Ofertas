"""Public store adapter registry API."""

from bot_ofertas.stores.base import StoreAdapter, StorePolicy
from bot_ofertas.stores.registry import (
    STORE_ADAPTER_ENTRY_POINT,
    StoreDisabledError,
    StoreRegistrationError,
    StoreRegistry,
    StoreRegistryError,
    UnsupportedStoreError,
    build_store_registry,
    get_store_registry,
    resolve_store,
)

__all__ = [
    "STORE_ADAPTER_ENTRY_POINT",
    "StoreAdapter",
    "StoreDisabledError",
    "StorePolicy",
    "StoreRegistrationError",
    "StoreRegistry",
    "StoreRegistryError",
    "UnsupportedStoreError",
    "build_store_registry",
    "get_store_registry",
    "resolve_store",
]
