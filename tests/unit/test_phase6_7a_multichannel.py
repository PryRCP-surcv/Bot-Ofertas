from __future__ import annotations

from datetime import timedelta

from bot_ofertas.catalog_balance import catalog_category
from bot_ofertas.notifications import NotificationRoute
from bot_ofertas.runtime_config import RuntimeSettings


def test_legacy_chat_id_remains_the_free_destination() -> None:
    settings = RuntimeSettings(
        telegram_chat_id="-100111",
        telegram_enabled=True,
    )

    destinations = settings.telegram_offer_destinations()
    routes = settings.telegram_offer_routes()

    assert len(destinations) == 1
    assert destinations[0].channel == "telegram_free"
    assert destinations[0].audience == "free"
    assert destinations[0].chat_id == "-100111"
    assert routes[0].routing_rule == "phase6.7a_free_primary"
    assert routes[0].dispatch_mode == "immediate"


def test_free_and_vip_destinations_are_routed_independently() -> None:
    settings = RuntimeSettings(
        telegram_free_chat_id="-100111",
        telegram_vip_chat_id="-100222",
        telegram_vip_mirror_enabled=True,
    )

    destinations = settings.telegram_offer_destinations()
    routes = settings.telegram_offer_routes()

    assert [destination.channel for destination in destinations] == [
        "telegram_free",
        "telegram_vip",
    ]
    assert [route.audience for route in routes] == ["free", "vip"]
    assert routes[1].dispatch_mode == "mirrored"
    assert routes[1].routing_rule == "phase6.7a_vip_mirror"


def test_vip_route_is_not_created_when_the_mirror_is_disabled() -> None:
    settings = RuntimeSettings(
        telegram_free_chat_id="-100111",
        telegram_vip_chat_id="-100222",
        telegram_vip_mirror_enabled=False,
    )

    assert [
        destination.channel
        for destination in settings.telegram_offer_destinations()
    ] == ["telegram_free"]


def test_notification_route_rejects_invalid_schedules() -> None:
    try:
        NotificationRoute(
            channel="telegram_vip",
            provider="telegram",
            audience="vip",
            dispatch_mode="immediate",
            routing_rule="invalid_immediate_delay",
            routing_reason="prueba",
            delay=timedelta(minutes=5),
        )
    except ValueError as error:
        assert "delayed" in str(error)
    else:  # pragma: no cover - protects the routing contract
        raise AssertionError("an immediate route with delay must fail")


def test_catalog_categories_cover_common_commercial_terms() -> None:
    assert (
        catalog_category(
            store_slug="efe",
            label="Memoria USB 128 GB",
            category_path=[],
        )
        == "technology"
    )
    assert (
        catalog_category(
            store_slug="tottus",
            label="Cama acolchada para gato",
            category_path=[],
        )
        == "home"
    )
    assert (
        catalog_category(
            store_slug="estilos",
            label="Mochila urbana",
            category_path=[],
        )
        == "fashion"
    )
