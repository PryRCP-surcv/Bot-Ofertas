"""Notification delivery channels."""

from bot_ofertas.notifications.base import (
    NotificationChannel,
    NotificationResult,
    NotificationStatus,
    OfferNotification,
)
from bot_ofertas.notifications.telegram import (
    TelegramNotifier,
    TelegramTransport,
    TelegramTransportError,
    UrllibTelegramTransport,
    render_telegram_message,
)

__all__ = [
    "NotificationChannel",
    "NotificationResult",
    "NotificationStatus",
    "OfferNotification",
    "TelegramNotifier",
    "TelegramTransport",
    "TelegramTransportError",
    "UrllibTelegramTransport",
    "render_telegram_message",
]
