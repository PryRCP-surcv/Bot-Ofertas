from datetime import UTC, datetime
from types import SimpleNamespace

from bot_ofertas.catalog_balance import (
    BalanceEntry,
    balanced_indices,
    catalog_category,
)
from bot_ofertas.cli import _round_robin_candidates
from bot_ofertas.notifications import OfferNotification, render_telegram_message
from bot_ofertas.storage.discovery import lima_day_start_utc
from bot_ofertas.stores import build_store_registry


def test_broad_categories_use_path_label_and_reviewed_store_fallbacks() -> None:
    assert (
        catalog_category(
            store_slug="promart",
            label="Toma RJ45",
            category_path=["Electricidad", "Interruptores"],
        )
        == "home_improvement"
    )
    assert (
        catalog_category(
            store_slug="efe",
            label="Cafetera programable",
            category_path=["Electrohogar"],
        )
        == "appliances"
    )
    assert (
        catalog_category(
            store_slug="footloose",
            label="Modelo urbano azul",
        )
        == "footwear"
    )
    assert (
        catalog_category(
            store_slug="wong",
            label="Producto sin palabras clasificables",
        )
        == "supermarket"
    )


def test_balanced_indices_correct_store_and_category_underrepresentation() -> None:
    initial = [
        *(BalanceEntry("cassinelli", "home_improvement") for _ in range(5)),
        BalanceEntry("coolbox", "technology"),
    ]
    entries = [
        BalanceEntry("cassinelli", "home_improvement"),
        BalanceEntry("coolbox", "technology"),
        BalanceEntry("footloose", "footwear"),
        BalanceEntry("footloose", "footwear"),
        BalanceEntry("coolbox", "appliances"),
    ]

    selected = balanced_indices(entries, limit=4, initial_entries=initial)

    assert selected == [2, 4, 3, 1]


def test_catalog_expansion_uses_existing_counts_instead_of_equal_additions() -> None:
    active = [
        *(
            SimpleNamespace(store_slug="cassinelli", label=f"grifería {position}")
            for position in range(4)
        ),
        SimpleNamespace(store_slug="coolbox", label="laptop"),
    ]
    candidates = [
        SimpleNamespace(store_slug="cassinelli", label="ducha", marker=0),
        SimpleNamespace(store_slug="coolbox", label="audífonos", marker=1),
        SimpleNamespace(store_slug="footloose", label="sandalias", marker=2),
        SimpleNamespace(store_slug="footloose", label="zapatillas", marker=3),
        SimpleNamespace(store_slug="coolbox", label="parlante", marker=4),
    ]

    selected = _round_robin_candidates(
        candidates,
        limit=4,
        active_products=active,
    )

    assert [item.marker for item in selected] == [2, 1, 3, 4]


def test_balanced_indices_prevent_multiple_stores_in_one_vertical_from_dominating() -> None:
    entries = [
        BalanceEntry("metro", "supermarket"),
        BalanceEntry("plazavea", "supermarket"),
        BalanceEntry("wong", "supermarket"),
        BalanceEntry("coolbox", "technology"),
    ]

    selected = balanced_indices(entries, limit=2)

    assert selected == [0, 3]


def test_catalog_expansion_compensates_recently_overrepresented_alerts() -> None:
    candidates = [
        SimpleNamespace(store_slug="topitop", label="polo", marker=0),
        SimpleNamespace(store_slug="coolbox", label="audífonos", marker=1),
        SimpleNamespace(store_slug="footloose", label="sandalias", marker=2),
        SimpleNamespace(store_slug="promart", label="taladro", marker=3),
    ]
    recent_alerts = [
        *(BalanceEntry("topitop", "fashion") for _position in range(10)),
        *(BalanceEntry("footloose", "footwear") for _position in range(8)),
    ]

    selected = _round_robin_candidates(
        candidates,
        limit=2,
        recent_alerts=recent_alerts,
    )

    assert [item.marker for item in selected] == [1, 3]


def test_only_reviewed_variant_stores_allow_all_exact_skus() -> None:
    registry = build_store_registry(include_plugins=False)

    assert registry.get("topitop").policy.allow_all_exact_variants is True
    assert registry.get("footloose").policy.allow_all_exact_variants is True
    assert registry.get("coolbox").policy.allow_all_exact_variants is False


def test_telegram_message_explains_grouped_available_sizes() -> None:
    message = render_telegram_message(
        OfferNotification(
            classification="exceptional_deal",
            product_name="Zapatillas urbanas",
            current_price="79.90",
            currency="PEN",
            reason="descuento confirmado",
            product_url="https://www.footloose.pe/zapatillas/p",
            variant_summary="Tallas disponibles: 38, 39, 40",
        )
    )

    assert "📐 <b>Tallas:</b> 38, 39, 40" in message


def test_daily_discovery_quota_uses_the_lima_calendar_day() -> None:
    after_local_midnight = datetime(2026, 8, 1, 5, 30, tzinfo=UTC)

    assert lima_day_start_utc(after_local_midnight) == datetime(
        2026,
        8,
        1,
        5,
        0,
        tzinfo=UTC,
    )
