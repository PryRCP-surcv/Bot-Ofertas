"""PostgreSQL persistence adapters."""

from bot_ofertas.storage.config import DatabaseSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from bot_ofertas.storage.models import (
    Base,
    CrawlRun,
    CrawlRunStatus,
    DealDetection,
    NotificationDelivery,
    OfferAlertState,
    PriceObservationRecord,
    StoreCrawlState,
    TrackedProduct,
)
from bot_ofertas.storage.repositories import (
    CrawlRunRepository,
    PriceObservationRepository,
    ProductClaimBatch,
    SaveObservationResult,
    StoreCrawlStateRepository,
    TrackedProductRepository,
)

__all__ = [
    "Base",
    "CrawlRun",
    "CrawlRunRepository",
    "CrawlRunStatus",
    "DatabaseSettings",
    "DealDetection",
    "NotificationDelivery",
    "OfferAlertState",
    "PriceObservationRecord",
    "PriceObservationRepository",
    "ProductClaimBatch",
    "SaveObservationResult",
    "StoreCrawlState",
    "StoreCrawlStateRepository",
    "TrackedProduct",
    "TrackedProductRepository",
    "create_database_engine",
    "create_session_factory",
    "session_scope",
]
