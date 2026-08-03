"""Notification delivery channels."""

from bot_ofertas.notifications.base import (
    NotificationChannel,
    NotificationResult,
    NotificationRoute,
    NotificationStatus,
    OfferNotification,
)
from bot_ofertas.notifications.remote_image import (
    DownloadedImage,
    RemoteImageError,
    RemoteImageFetcher,
    SafeRemoteImageFetcher,
)
from bot_ofertas.notifications.telegram import (
    TelegramNotifier,
    TelegramTransport,
    TelegramTransportError,
    UrllibTelegramTransport,
    render_telegram_caption,
    render_telegram_message,
)

__all__ = [
    "NotificationChannel",
    "NotificationRoute",
    "NotificationResult",
    "NotificationStatus",
    "OfferNotification",
    "DownloadedImage",
    "RemoteImageError",
    "RemoteImageFetcher",
    "SafeRemoteImageFetcher",
    "TelegramNotifier",
    "TelegramTransport",
    "TelegramTransportError",
    "UrllibTelegramTransport",
    "render_telegram_caption",
    "render_telegram_message",
]
