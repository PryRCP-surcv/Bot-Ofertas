"""Command-line entry point for the local price-monitoring workflow."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bot_ofertas.crawling import settings as crawling_settings
from bot_ofertas.detection import assess_quality_flags, canonicalize_variant
from bot_ofertas.notifications import TelegramNotifier
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.scheduling import LocalScheduler
from bot_ofertas.services import (
    DetectionBatchSummary,
    DetectionService,
    NotificationDispatcher,
)
from bot_ofertas.storage.config import DatabaseSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from bot_ofertas.storage.models import (
    DealDetection,
    OfferConfirmationState,
    PriceObservationRecord,
    StoreCrawlState,
    TrackedProduct,
)
from bot_ofertas.storage.repositories import (
    EquivalentProductRepository,
    ProductClaimBatch,
    StoreCrawlStateRepository,
    TrackedProductRepository,
)
from bot_ofertas.stores import StoreAdapter, get_store_registry, resolve_store

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LIMA_TIMEZONE = ZoneInfo("America/Lima")
_DEFAULT_CRAWL_LIMIT = 20
_MAX_CRAWL_LIMIT = 20
_DEFAULT_HISTORY_LIMIT = 20
_MAX_HISTORY_LIMIT = 500
_DEFAULT_ANALYSIS_LIMIT = 100
_MAX_ANALYSIS_LIMIT = 1_000
_DEFAULT_NOTIFICATION_LIMIT = 20
_MAX_NOTIFICATION_LIMIT = 100
_CRAWL_LEASE_DURATION = timedelta(hours=2)
_CONDITION_FLAG_LABELS = {
    "conditional_card_price": "requiere tarjeta o medio de pago específico",
    "conditional_payment_method_price": "requiere tarjeta o medio de pago específico",
    "payment_method_price": "requiere tarjeta o medio de pago específico",
    "card_only_price": "requiere tarjeta o medio de pago específico",
    "tarjeta_only_price": "requiere tarjeta o medio de pago específico",
    "conditional_membership_price": "requiere membresía",
    "membership_price": "requiere membresía",
    "membership_only_price": "requiere membresía",
    "conditional_coupon_price": "requiere cupón o código promocional",
    "coupon_price": "requiere cupón o código promocional",
    "coupon_only_price": "requiere cupón o código promocional",
    "conditional_quantity_price": "requiere una cantidad mínima",
    "minimum_quantity_price": "requiere una cantidad mínima",
    "quantity_tier_price": "requiere una cantidad mínima",
    "conditional_promotion_price": "promoción con requisitos; revisar condiciones",
}


@dataclass(frozen=True, slots=True)
class _ClaimedProduct:
    product: TrackedProduct
    lease_token: UUID


def _integer_between(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("debe ser un número entero") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"debe estar entre {minimum} y {maximum}")
        return number

    return parse


def _variant_pair(value: str) -> tuple[str, str]:
    key, separator, variant_value = value.partition("=")
    key = key.strip()
    variant_value = variant_value.strip()
    if not separator or not key or not variant_value:
        raise argparse.ArgumentTypeError("debe usar el formato CLAVE=VALOR")
    return key, variant_value


def _uuid_argument(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un UUID válido") from exc


def _canonical_variant_pairs(
    pairs: Sequence[tuple[str, str]],
) -> dict[str, str]:
    expected_variant: dict[str, str] = {}
    for key, value in pairs:
        normalized_pair = canonicalize_variant({key: value})
        normalized_key, normalized_value = next(iter(normalized_pair.items()))
        if normalized_key in expected_variant:
            raise ValueError(
                "cada clave de --variant debe ser única, incluso con mayúsculas o acentos"
            )
        expected_variant[normalized_key] = normalized_value
    return expected_variant


def _quality_flag_labels(
    quality_flags: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    assessment = assess_quality_flags(quality_flags)
    conditions: list[str] = []
    has_specific_condition = any(
        flag.strip().casefold() in _CONDITION_FLAG_LABELS
        and flag.strip().casefold() != "conditional_promotion_price"
        for flag in quality_flags
    )
    for raw_flag in quality_flags:
        flag = raw_flag.strip().casefold()
        condition = _CONDITION_FLAG_LABELS.get(flag)
        if condition is not None and (
            flag != "conditional_promotion_price" or not has_specific_condition
        ):
            conditions.append(condition)
    return (
        tuple(dict.fromkeys(conditions)),
        assessment.blocking_quality_flags,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bot-ofertas",
        description="Monitor responsable de precios públicos en tiendas online.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    db_parser = commands.add_parser("db", help="Administra el esquema de PostgreSQL.")
    db_commands = db_parser.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("upgrade", help="Aplica todas las migraciones pendientes.")

    config_parser = commands.add_parser(
        "config",
        help="Muestra la configuración efectiva sin revelar secretos.",
    )
    config_commands = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    config_commands.add_parser("show", help="Muestra la política activa de Fase 3.")

    store_parser = commands.add_parser(
        "store",
        help="Muestra las integraciones de tiendas registradas.",
    )
    store_commands = store_parser.add_subparsers(dest="store_command", required=True)
    store_commands.add_parser(
        "list",
        help="Lista tiendas, dominios y límites habilitados.",
    )

    product_parser = commands.add_parser(
        "product",
        help="Administra los productos que se monitorean.",
    )
    product_commands = product_parser.add_subparsers(
        dest="product_command",
        required=True,
    )
    add_parser = product_commands.add_parser(
        "add",
        help="Agrega una URL y detecta automáticamente su tienda.",
    )
    add_parser.add_argument("url", metavar="URL")
    add_parser.add_argument("--label", required=True, help="Nombre reconocible del producto.")
    add_parser.add_argument("--brand", help="Marca esperada para validar la ficha.")
    add_parser.add_argument("--model", help="Modelo esperado para validar la ficha.")
    add_parser.add_argument(
        "--variant",
        action="append",
        default=[],
        type=_variant_pair,
        metavar="CLAVE=VALOR",
        help="Variante esperada; puede repetirse, por ejemplo Color=Negro.",
    )
    add_parser.add_argument(
        "--accessory",
        action="store_true",
        help="Confirma que el producto buscado sí es un accesorio.",
    )
    add_parser.add_argument(
        "--interval",
        type=_integer_between(30, 525_600),
        default=60,
        metavar="MINUTOS",
        help="Minutos entre consultas (mínimo 30; predeterminado: 60).",
    )
    product_commands.add_parser("list", help="Lista los productos registrados.")
    for action, help_text in (
        ("enable", "Activa nuevamente un producto registrado."),
        ("disable", "Detiene el monitoreo de un producto sin borrar su historial."),
    ):
        status_parser = product_commands.add_parser(action, help=help_text)
        status_parser.add_argument("product_id", type=_uuid_argument, metavar="ID")
    variant_parser = product_commands.add_parser(
        "variant",
        help="Selecciona la variante exacta de un producto ya registrado.",
    )
    variant_parser.add_argument("product_id", type=_uuid_argument, metavar="ID")
    variant_parser.add_argument(
        "--variant",
        action="append",
        required=True,
        type=_variant_pair,
        metavar="CLAVE=VALOR",
        help="Variante exacta; puede repetirse, por ejemplo Color=Negro.",
    )

    equivalence_parser = commands.add_parser(
        "equivalence",
        help="Administra equivalencias verificadas entre tiendas.",
    )
    equivalence_commands = equivalence_parser.add_subparsers(
        dest="equivalence_command",
        required=True,
    )
    equivalence_create = equivalence_commands.add_parser(
        "create",
        help="Crea un grupo canónico para un modelo y variante exactos.",
    )
    equivalence_create.add_argument("--name", required=True)
    equivalence_create.add_argument("--brand", required=True)
    equivalence_create.add_argument("--model", required=True)
    equivalence_create.add_argument(
        "--variant",
        action="append",
        default=[],
        type=_variant_pair,
        metavar="CLAVE=VALOR",
    )
    equivalence_commands.add_parser("list", help="Lista grupos y sus tiendas.")
    for action in ("add-product", "remove-product"):
        membership_parser = equivalence_commands.add_parser(
            action,
            help=(
                "Agrega un producto verificado al grupo."
                if action == "add-product"
                else "Retira un producto del grupo."
            ),
        )
        membership_parser.add_argument(
            "group_id",
            type=_uuid_argument,
            metavar="GRUPO_ID",
        )
        membership_parser.add_argument(
            "product_id",
            type=_uuid_argument,
            metavar="PRODUCTO_ID",
        )

    crawl_parser = commands.add_parser(
        "crawl",
        help="Consulta productos activos cuyo intervalo ya venció.",
    )
    crawl_parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora el intervalo, pero conserva los demás límites de consulta.",
    )
    crawl_parser.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_CRAWL_LIMIT),
        default=_DEFAULT_CRAWL_LIMIT,
        metavar="N",
        help=f"Máximo de productos por corrida (1-{_MAX_CRAWL_LIMIT}).",
    )

    history_parser = commands.add_parser(
        "history",
        help="Muestra las observaciones de precio más recientes.",
    )
    history_parser.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_HISTORY_LIMIT),
        default=_DEFAULT_HISTORY_LIMIT,
        metavar="N",
        help=f"Número de observaciones (1-{_MAX_HISTORY_LIMIT}).",
    )

    analyze_parser = commands.add_parser(
        "analyze",
        help="Analiza observaciones nuevas y registra decisiones auditables.",
    )
    analyze_parser.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_ANALYSIS_LIMIT),
        default=_DEFAULT_ANALYSIS_LIMIT,
        metavar="N",
        help=f"Máximo de observaciones (1-{_MAX_ANALYSIS_LIMIT}).",
    )

    notify_parser = commands.add_parser(
        "notify",
        help="Entrega por Telegram las alertas pendientes.",
    )
    notify_parser.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_NOTIFICATION_LIMIT),
        default=_DEFAULT_NOTIFICATION_LIMIT,
        metavar="N",
        help=f"Máximo de alertas (1-{_MAX_NOTIFICATION_LIMIT}).",
    )

    alert_parser = commands.add_parser(
        "alert",
        help="Consulta las ofertas y posibles errores detectados.",
    )
    alert_commands = alert_parser.add_subparsers(
        dest="alert_command",
        required=True,
    )
    alert_list_parser = alert_commands.add_parser(
        "list",
        help="Lista las detecciones que calificaron como oferta.",
    )
    alert_list_parser.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_HISTORY_LIMIT),
        default=_DEFAULT_HISTORY_LIMIT,
        metavar="N",
    )
    alert_list_parser.add_argument(
        "--all",
        action="store_true",
        help="Incluye decisiones sin oferta, descartes y errores aislados.",
    )

    confirmation_parser = commands.add_parser(
        "confirmation",
        help="Consulta candidatas que esperan otra observación independiente.",
    )
    confirmation_commands = confirmation_parser.add_subparsers(
        dest="confirmation_command",
        required=True,
    )
    confirmation_list = confirmation_commands.add_parser(
        "list",
        help="Lista estados de confirmación activos.",
    )
    confirmation_list.add_argument(
        "--limit",
        type=_integer_between(1, _MAX_HISTORY_LIMIT),
        default=_DEFAULT_HISTORY_LIMIT,
        metavar="N",
    )

    cycle_parser = commands.add_parser(
        "cycle",
        help="Ejecuta un ciclo: rastreo, análisis y notificaciones.",
    )
    _add_cycle_arguments(cycle_parser)

    run_parser = commands.add_parser(
        "run",
        help="Mantiene el monitor en ejecución con ciclos periódicos.",
    )
    _add_cycle_arguments(run_parser)
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta un solo ciclo y termina.",
    )
    run_parser.add_argument(
        "--poll-seconds",
        type=_integer_between(30, 86_400),
        metavar="SEGUNDOS",
        help="Frecuencia del scheduler; por defecto usa BOT_SCHEDULER_POLL_SECONDS.",
    )
    return parser


def _add_cycle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--crawl-limit",
        type=_integer_between(1, _MAX_CRAWL_LIMIT),
        default=_DEFAULT_CRAWL_LIMIT,
        metavar="N",
    )
    parser.add_argument(
        "--analysis-limit",
        type=_integer_between(1, _MAX_ANALYSIS_LIMIT),
        default=_DEFAULT_ANALYSIS_LIMIT,
        metavar="N",
    )
    parser.add_argument(
        "--notification-limit",
        type=_integer_between(1, _MAX_NOTIFICATION_LIMIT),
        default=_DEFAULT_NOTIFICATION_LIMIT,
        metavar="N",
    )


def _database_engine():
    settings = DatabaseSettings.from_env()
    return create_database_engine(settings)


def _upgrade_database() -> int:
    # Loading settings here fails early with a concise message when .env is incomplete.
    DatabaseSettings.from_env()
    alembic_config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(_PROJECT_ROOT / "migrations"),
    )
    command.upgrade(alembic_config, "head")
    print("Base de datos actualizada correctamente.")
    return 0


def _show_config() -> int:
    settings = RuntimeSettings.from_env()
    print("Configuración efectiva de Fase 3:")
    print(f"- Detector: {settings.detector_version}")
    print(
        "- Historial: "
        f"{settings.detection_history_days} días; "
        f"máximo {settings.detection_history_limit} observaciones por oferta"
    )
    print(
        "- Medianas: 7, 30 y 90 días; "
        f"mínimo {settings.detector_config.minimum_history_samples} muestras"
    )
    print(
        "- Equivalentes: "
        f"mínimo {settings.detector_config.minimum_equivalent_samples} tiendas; "
        f"frescura {settings.equivalent_max_age_hours} horas"
    )
    print(
        "- Confirmación: "
        f"{'obligatoria' if settings.confirmation_required else 'desactivada'}; "
        f"tolerancia {settings.confirmation_price_tolerance_ratio * 100}%"
    )
    print(
        "- Confianza mínima para alertar: "
        f"{settings.minimum_alert_confidence}/100; "
        f"bono por confirmación {settings.confirmation_confidence_bonus}"
    )
    print(
        "- Ofertas condicionadas: permitidas con aviso explícito; "
        "una cuota nunca sustituye al precio total"
    )
    print(
        "- Telegram: "
        f"{'habilitado' if settings.telegram_enabled else 'deshabilitado'}; "
        f"token={'configurado' if settings.telegram_token else 'ausente'}; "
        f"chat_id={'configurado' if settings.telegram_chat_id else 'ausente'}"
    )
    return 0


def _add_product(args: argparse.Namespace) -> int:
    label = args.label.strip()
    if not label:
        raise ValueError("--label no puede estar vacío")
    expected_variant = _canonical_variant_pairs(args.variant)

    adapter, canonical_url = resolve_store(args.url)
    if args.interval < adapter.policy.minimum_interval_minutes:
        raise ValueError(
            f"{adapter.display_name} requiere un intervalo mínimo de "
            f"{adapter.policy.minimum_interval_minutes} minutos"
        )

    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        try:
            with session_scope(factory) as session:
                product = TrackedProductRepository(session).add(
                    store_slug=adapter.slug,
                    source_url=canonical_url,
                    label=label,
                    expected_brand=args.brand,
                    expected_model=args.model,
                    expected_variant=expected_variant,
                    expected_is_accessory=args.accessory,
                    check_interval_minutes=args.interval,
                )
                product_id = product.id
        except IntegrityError:
            print(
                f"Ese producto de {adapter.display_name} ya está registrado.",
                file=sys.stderr,
            )
            return 2
    finally:
        engine.dispose()

    print("Producto agregado.")
    print(f"ID: {product_id}")
    print(f"Tienda detectada: {adapter.display_name} ({adapter.slug})")
    print(f"Etiqueta: {label}")
    print(f"Intervalo: {args.interval} minutos")
    print(f"URL: {canonical_url}")
    return 0


def _list_stores() -> int:
    registry = get_store_registry()
    adapters = registry.adapters
    if not adapters:
        print("No hay adaptadores de tiendas registrados.")
        return 0

    print(f"Tiendas registradas: {len(adapters)}")
    for adapter in adapters:
        state = "habilitada" if adapter.policy.enabled else "deshabilitada"
        print()
        print(f"- {adapter.display_name} ({adapter.slug}) [{state}]")
        print(f"  Dominios: {', '.join(sorted(adapter.hosts))}")
        print(
            "  Límites: "
            f"{adapter.policy.max_targets_per_run} productos por corrida; "
            f"mínimo {adapter.policy.minimum_interval_minutes} minutos"
        )
        if adapter.policy.notes:
            print(f"  Política: {adapter.policy.notes}")

    if registry.plugin_errors:
        print()
        print("Adaptadores externos que no pudieron cargarse:")
        for error in registry.plugin_errors:
            print(f"- {error}")
    return 0


def _list_products() -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            statement = select(TrackedProduct).order_by(
                TrackedProduct.active.desc(),
                TrackedProduct.created_at.asc(),
            )
            products = list(session.scalars(statement))
    finally:
        engine.dispose()

    if not products:
        print("Todavía no hay productos registrados.")
        return 0

    print(f"Productos registrados: {len(products)}")
    for product in products:
        state = "activo" if product.active else "inactivo"
        last_check = _format_datetime(product.last_checked_at)
        print()
        print(f"- {product.label} [{state}]")
        print(f"  ID: {product.id}")
        print(f"  Tienda: {product.store_slug}")
        print(f"  Cada: {product.check_interval_minutes} minutos")
        print(f"  Última consulta: {last_check}")
        print(f"  Fallos consecutivos: {product.consecutive_failures}")
        if product.expected_brand:
            print(f"  Marca esperada: {product.expected_brand}")
        if product.expected_model:
            print(f"  Modelo esperado: {product.expected_model}")
        if product.expected_variant:
            variant = ", ".join(
                f"{key}={value}" for key, value in sorted(product.expected_variant.items())
            )
            print(f"  Variante esperada: {variant}")
        print(
            "  Tipo esperado: "
            f"{'accesorio' if product.expected_is_accessory else 'producto principal'}"
        )
        print(f"  URL: {product.source_url}")
    return 0


def _set_product_active(product_id: UUID, *, active: bool) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            product = TrackedProductRepository(session).set_active(
                product_id,
                active=active,
            )
            label = product.label if product is not None else None
    finally:
        engine.dispose()
    if label is None:
        print(f"No existe un producto con ID {product_id}.", file=sys.stderr)
        return 2
    state = "activado" if active else "desactivado"
    print(f"Producto {state}: {label} ({product_id}).")
    return 0


def _set_product_variant(
    product_id: UUID,
    variant_pairs: Sequence[tuple[str, str]],
) -> int:
    expected_variant = _canonical_variant_pairs(variant_pairs)
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            product = TrackedProductRepository(session).set_expected_variant(
                product_id,
                expected_variant=expected_variant,
            )
            label = product.label if product is not None else None
    finally:
        engine.dispose()
    if label is None:
        print(f"No existe un producto con ID {product_id}.", file=sys.stderr)
        return 2
    print(f"Variante seleccionada para {label}: {_format_variant(expected_variant)}")
    return 0


def _create_equivalence(args: argparse.Namespace) -> int:
    canonical_variant = _canonical_variant_pairs(args.variant)
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        try:
            with session_scope(factory) as session:
                group = EquivalentProductRepository(session).create_group(
                    name=args.name,
                    brand=args.brand,
                    model=args.model,
                    canonical_variant=canonical_variant,
                )
                group_id = group.id
        except IntegrityError:
            print("Ya existe un grupo de equivalencia con ese nombre.", file=sys.stderr)
            return 2
    finally:
        engine.dispose()
    print(f"Grupo de equivalencia creado: {args.name} ({group_id}).")
    return 0


def _list_equivalences() -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    rows: list[tuple[Any, list[TrackedProduct]]] = []
    try:
        with session_scope(factory) as session:
            repository = EquivalentProductRepository(session)
            rows = [(group, repository.members(group.id)) for group in repository.list_groups()]
    finally:
        engine.dispose()
    if not rows:
        print("Todavía no hay equivalencias verificadas.")
        return 0
    print(f"Grupos de equivalencia: {len(rows)}")
    for group, members in rows:
        print()
        print(f"- {group.name} ({group.id})")
        print(f"  Identidad: {group.brand} {group.model}")
        if group.canonical_variant:
            print(f"  Variante: {_format_variant(group.canonical_variant)}")
        print(f"  Miembros: {len(members)}")
        for product in members:
            print(f"    - {product.store_slug}: {product.label} ({product.id})")
    return 0


def _change_equivalence_membership(
    *,
    group_id: UUID,
    product_id: UUID,
    add: bool,
) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        try:
            with session_scope(factory) as session:
                repository = EquivalentProductRepository(session)
                if add:
                    repository.add_product(
                        group_id=group_id,
                        tracked_product_id=product_id,
                    )
                    changed = True
                else:
                    changed = repository.remove_product(
                        group_id=group_id,
                        tracked_product_id=product_id,
                    )
        except IntegrityError:
            print(
                "El producto ya pertenece a un grupo de equivalencia.",
                file=sys.stderr,
            )
            return 2
    finally:
        engine.dispose()
    if not changed:
        print("No existe esa membresía de equivalencia.", file=sys.stderr)
        return 2
    action = "agregado al" if add else "retirado del"
    print(f"Producto {action} grupo de equivalencia.")
    return 0


def _claim_due_batches(
    *,
    force: bool,
    limit: int,
    adapters: tuple[StoreAdapter, ...],
) -> list[ProductClaimBatch]:
    ordered_adapters = _rotated_adapters(adapters)
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            repository = TrackedProductRepository(session)
            batches: list[ProductClaimBatch] = []
            claimed_per_store: dict[str, int] = defaultdict(int)
            exhausted_stores: set[str] = set()
            base_quota, extra_slots = divmod(limit, len(ordered_adapters))

            for position, adapter in enumerate(ordered_adapters):
                fair_quota = base_quota + (1 if position < extra_slots else 0)
                quota = min(fair_quota, adapter.policy.max_targets_per_run)
                if quota <= 0:
                    continue
                batch = repository.claim_due(
                    force=force,
                    limit=quota,
                    store_slugs={adapter.slug},
                    minimum_interval_minutes=adapter.policy.minimum_interval_minutes,
                    lease_duration=_CRAWL_LEASE_DURATION,
                )
                if batch.products:
                    batches.append(batch)
                    claimed_per_store[adapter.slug] += len(batch.products)
                if len(batch.products) < quota:
                    exhausted_stores.add(adapter.slug)

            remaining = limit - sum(len(batch.products) for batch in batches)
            for adapter in ordered_adapters:
                if remaining <= 0:
                    break
                capacity = adapter.policy.max_targets_per_run - claimed_per_store[adapter.slug]
                if capacity <= 0 or adapter.slug in exhausted_stores:
                    continue
                quota = min(remaining, capacity)
                batch = repository.claim_due(
                    force=force,
                    limit=quota,
                    store_slugs={adapter.slug},
                    minimum_interval_minutes=adapter.policy.minimum_interval_minutes,
                    lease_duration=_CRAWL_LEASE_DURATION,
                )
                if batch.products:
                    batches.append(batch)
                    claimed_per_store[adapter.slug] += len(batch.products)
                    remaining -= len(batch.products)
            return batches
    finally:
        engine.dispose()


def _rotated_adapters(
    adapters: tuple[StoreAdapter, ...],
) -> tuple[StoreAdapter, ...]:
    if len(adapters) < 2:
        return adapters
    start = int(datetime.now(UTC).timestamp() // 60) % len(adapters)
    return adapters[start:] + adapters[:start]


def _release_claim_batches(batches: Sequence[ProductClaimBatch]) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            repository = TrackedProductRepository(session)
            return sum(repository.release_batch(batch) for batch in batches)
    finally:
        engine.dispose()


def _active_store_pauses(store_slugs: frozenset[str]) -> list[StoreCrawlState]:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            return StoreCrawlStateRepository(session).active_pauses(store_slugs=set(store_slugs))
    finally:
        engine.dispose()


def _crawl(args: argparse.Namespace) -> int:
    registry = get_store_registry()
    for plugin_error in registry.plugin_errors:
        print(
            f"Aviso: adaptador externo omitido: {plugin_error}",
            file=sys.stderr,
        )
    enabled_adapters = registry.enabled_adapters
    if not enabled_adapters:
        raise RuntimeError("no hay tiendas habilitadas para consultar")

    batches = _claim_due_batches(
        force=args.force,
        limit=args.limit,
        adapters=enabled_adapters,
    )
    claimed_products = [
        _ClaimedProduct(product=product, lease_token=batch.token)
        for batch in batches
        for product in batch.products
    ]
    if not claimed_products:
        active_pauses = _active_store_pauses(registry.enabled_store_slugs)
        if active_pauses:
            print("Tiendas pausadas por una señal de bloqueo:")
            for pause in active_pauses:
                adapter = registry.get(pause.store_slug)
                print(
                    f"- {adapter.display_name}: hasta "
                    f"{_format_datetime(pause.paused_until)} "
                    f"({pause.pause_reason})"
                )
            print("La opción --force tampoco omite una pausa de seguridad.")
            return 0
        if args.force:
            print("No hay productos activos de tiendas habilitadas para consultar.")
        else:
            print("No hay productos pendientes según su intervalo.")
        return 0

    products_by_store: dict[str, list[_ClaimedProduct]] = defaultdict(list)
    for claimed_product in claimed_products:
        products_by_store[claimed_product.product.store_slug].append(claimed_product)

    print(
        "Iniciando una consulta controlada de "
        f"{len(claimed_products)} producto(s) en {len(products_by_store)} tienda(s)..."
    )

    crawlers: list[tuple[str, Any]] = []
    try:
        scrapy_settings = Settings()
        scrapy_settings.setmodule(crawling_settings, priority="project")
        process = CrawlerProcess(settings=scrapy_settings)

        for store_slug, store_claims in sorted(products_by_store.items()):
            adapter = registry.get(store_slug)
            if len(store_claims) > adapter.policy.max_targets_per_run:
                raise RuntimeError(
                    f"el lote de {adapter.display_name} supera su límite de seguridad"
                )
            targets = [
                {
                    "tracked_product_id": str(claimed.product.id),
                    "url": claimed.product.source_url,
                    "lease_token": str(claimed.lease_token),
                }
                for claimed in store_claims
            ]
            crawler = process.create_crawler(adapter.spider_class)
            process.crawl(crawler, targets=targets)
            crawlers.append((adapter.display_name, crawler))

        process.start()
    finally:
        # Completed targets already cleared their token. This only releases work
        # left behind by construction errors, cancellation, or finalization failure.
        _release_claim_batches(batches)

    succeeded = True
    total_persisted = 0
    total_errors = 0
    for display_name, crawler in crawlers:
        status = str(crawler.stats.get_value("bot_ofertas/run_status", "unknown"))
        persisted = int(crawler.stats.get_value("bot_ofertas/persisted_observations", 0) or 0)
        errors = int(crawler.stats.get_value("bot_ofertas/error_count", 0) or 0)
        run_id = crawler.stats.get_value("bot_ofertas/crawl_run_id")
        paused_until = crawler.stats.get_value("bot_ofertas/store_paused_until")
        total_persisted += persisted
        total_errors += errors
        succeeded = succeeded and status == "succeeded"
        print(f"{display_name}: estado={status}, observaciones={persisted}, errores={errors}.")
        if run_id:
            print(f"  Corrida: {run_id}")
        if paused_until:
            print(f"  Tienda pausada automáticamente hasta: {paused_until}")

    print(f"Consulta terminada: observaciones={total_persisted}, errores={total_errors}.")
    return 0 if succeeded else 1


def _history(limit: int) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            statement = (
                select(PriceObservationRecord)
                .order_by(
                    PriceObservationRecord.observed_at.desc(),
                    PriceObservationRecord.id.desc(),
                )
                .limit(limit)
            )
            observations = list(session.scalars(statement))
    finally:
        engine.dispose()

    if not observations:
        print("Todavía no hay observaciones de precio.")
        return 0

    print(f"Observaciones recientes: {len(observations)}")
    for observation in observations:
        price = _format_price(observation.currency, observation.price)
        list_price = _format_price(observation.currency, observation.list_price)
        availability = observation.availability.value
        print()
        print(f"- {_format_datetime(observation.observed_at)} | {observation.title}")
        print(f"  Precio: {price} | Precio de lista: {list_price}")
        print(
            f"  Tienda: {observation.store_slug} | "
            f"SKU: {observation.sku} | "
            f"Vendedor: {observation.seller_name} ({observation.seller_id})"
        )
        print(
            f"  Disponibilidad: {availability} | "
            f"Condición: {observation.condition.value} | "
            f"Marketplace: {'sí' if observation.is_marketplace else 'no'}"
        )
        if observation.variant:
            print(f"  Variante: {_format_variant(observation.variant)}")
        if observation.installments:
            print(f"  Cuotas registradas: {len(observation.installments)}")
        conditions, blocking_flags = _quality_flag_labels(observation.quality_flags)
        if conditions:
            print(f"  Condiciones: {'; '.join(conditions)}")
        if blocking_flags:
            print(f"  Advertencias de calidad: {', '.join(blocking_flags)}")
        print(f"  URL: {observation.source_url}")
    return 0


def _analyze(limit: int) -> int:
    settings = RuntimeSettings.from_env()
    engine = _database_engine()
    factory = create_session_factory(engine)
    counters = {
        "processed": 0,
        "processing_errors": 0,
        "rejected": 0,
        "no_deal": 0,
        "alert_candidates": 0,
        "awaiting_confirmation": 0,
        "confirmed_candidates": 0,
        "low_confidence_suppressed": 0,
        "notifications_reserved": 0,
        "duplicates_suppressed": 0,
    }
    try:
        for _position in range(limit):
            with session_scope(factory) as session:
                batch = DetectionService(session, settings).process_new(limit=1)
            if batch.processed == 0:
                break
            for field_name in counters:
                counters[field_name] += getattr(batch, field_name)
    finally:
        engine.dispose()
    summary = DetectionBatchSummary(**counters)

    print(
        "Análisis terminado: "
        f"procesadas={summary.processed}, "
        f"errores_aislados={summary.processing_errors}, "
        f"descartadas={summary.rejected}, "
        f"sin_oferta={summary.no_deal}, "
        f"candidatas={summary.alert_candidates}, "
        f"esperando_confirmación={summary.awaiting_confirmation}, "
        f"confirmadas={summary.confirmed_candidates}, "
        f"confianza_insuficiente={summary.low_confidence_suppressed}, "
        f"alertas_pendientes={summary.notifications_reserved}, "
        f"duplicadas_omitidas={summary.duplicates_suppressed}."
    )
    return 0


def _notify(limit: int) -> int:
    settings = RuntimeSettings.from_env()
    notifier = TelegramNotifier(
        token=settings.telegram_token,
        chat_id=settings.telegram_chat_id,
        enabled=settings.telegram_enabled,
    )
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        summary = NotificationDispatcher(
            factory,
            settings,
            notifier,
        ).dispatch_due(limit=limit)
    finally:
        engine.dispose()

    if not summary.configured:
        print(
            "Telegram no está configurado. Las alertas permanecen pendientes; "
            "define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env."
        )
        return 0
    print(
        "Notificaciones terminadas: "
        f"reclamadas={summary.claimed}, enviadas={summary.sent}, "
        f"reintentables={summary.retrying}, fallidas={summary.failed}, "
        f"liberadas={summary.released}."
    )
    return 0 if summary.failed == 0 else 1


def _list_alerts(limit: int, *, include_all: bool = False) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            statement = (
                select(
                    DealDetection,
                    PriceObservationRecord,
                    TrackedProduct.label,
                )
                .join(
                    PriceObservationRecord,
                    PriceObservationRecord.id == DealDetection.observation_id,
                )
                .outerjoin(
                    TrackedProduct,
                    TrackedProduct.id == DealDetection.tracked_product_id,
                )
            )
            if not include_all:
                statement = statement.where(DealDetection.classification != "none")
            statement = statement.order_by(
                DealDetection.detected_at.desc(),
                DealDetection.id.desc(),
            ).limit(limit)
            alerts = list(session.execute(statement).all())
    finally:
        engine.dispose()

    if not alerts:
        if include_all:
            print("Todavía no hay decisiones del detector.")
        else:
            print("Todavía no hay ofertas ni posibles errores detectados.")
        return 0
    label = "Decisiones del detector" if include_all else "Detecciones de oferta"
    print(f"{label}: {len(alerts)}")
    for detection, observation, tracked_label in alerts:
        print()
        print(f"- {_format_datetime(detection.detected_at)} | {tracked_label or observation.title}")
        print(
            f"  Clasificación: {detection.classification} | "
            f"Severidad: {detection.score}/100 | "
            f"Confianza: {detection.confidence_score}/100 "
            f"({detection.confidence_level})"
        )
        print(
            f"  Precio: {_format_price(observation.currency, detection.current_price)} | "
            "Referencia: "
            f"{_format_price(observation.currency, detection.reference_price)}"
        )
        print(
            f"  Confirmación: {detection.confirmation_status} "
            f"({detection.confirmation_count} observaciones) | "
            f"Alerta: {detection.notification_status}"
        )
        print(f"  Detector: {detection.detector_version}")
        if detection.reasons:
            print(f"  Motivos: {', '.join(detection.reasons)}")
        if detection.rejection_reasons:
            print(f"  Descartes: {', '.join(detection.rejection_reasons)}")
        print(
            f"  Vendedor: {observation.seller_name} ({observation.seller_id}) | "
            f"Condición: {observation.condition.value} | "
            f"Marketplace: {'sí' if observation.is_marketplace else 'no'}"
        )
        if observation.variant:
            print(f"  Variante: {_format_variant(observation.variant)}")
        if observation.installments:
            print(f"  Cuotas registradas: {len(observation.installments)}")
        conditions, blocking_flags = _quality_flag_labels(observation.quality_flags)
        if conditions:
            print(f"  Condiciones: {'; '.join(conditions)}")
        if blocking_flags:
            print(f"  Advertencias de calidad: {', '.join(blocking_flags)}")
        print(f"  URL: {observation.source_url}")
    return 0


def _list_confirmations(limit: int) -> int:
    engine = _database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            statement = (
                select(
                    OfferConfirmationState,
                    TrackedProduct.label,
                )
                .outerjoin(
                    TrackedProduct,
                    TrackedProduct.id == OfferConfirmationState.tracked_product_id,
                )
                .join(
                    DealDetection,
                    DealDetection.id == OfferConfirmationState.candidate_detection_id,
                )
                .where(
                    DealDetection.confirmation_status == "awaiting",
                    OfferConfirmationState.expires_at > func.now(),
                )
                .order_by(
                    OfferConfirmationState.expires_at.asc(),
                    OfferConfirmationState.offer_key.asc(),
                )
                .limit(limit)
            )
            rows = list(session.execute(statement))
    finally:
        engine.dispose()
    if not rows:
        print("No hay ofertas esperando confirmación.")
        return 0
    print(f"Confirmaciones activas: {len(rows)}")
    for state, label in rows:
        print()
        print(f"- {label or state.offer_key}")
        print(
            f"  Clasificación candidata: {state.candidate_classification} | "
            f"Precio: PEN {state.candidate_price}"
        )
        print(
            f"  Evidencias válidas: {state.confirmation_count} | "
            f"Última: {_format_datetime(state.last_seen_at)}"
        )
        print(f"  Expira: {_format_datetime(state.expires_at)}")
    return 0


def _cycle(args: argparse.Namespace) -> int:
    print("=== Rastreo ===")
    crawl_status = _isolated_cycle_stage(
        "rastreo",
        lambda: _crawl(argparse.Namespace(force=False, limit=args.crawl_limit)),
    )
    print()
    print("=== Detección ===")
    analysis_status = _isolated_cycle_stage(
        "detección",
        lambda: _analyze(args.analysis_limit),
    )
    print()
    print("=== Alertas ===")
    notification_status = _isolated_cycle_stage(
        "alertas",
        lambda: _notify(args.notification_limit),
    )
    return max(crawl_status, analysis_status, notification_status)


def _isolated_cycle_stage(name: str, operation: Callable[[], int]) -> int:
    try:
        return int(operation())
    except SQLAlchemyError:
        print(
            f"Error en {name}: PostgreSQL no pudo completar la etapa; el ciclo continuará.",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError) as error:
        print(f"Error en {name}: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"Error inesperado en {name} ({type(error).__name__}); el ciclo continuará.",
            file=sys.stderr,
        )
        return 1


def _run_monitor(args: argparse.Namespace) -> int:
    if args.once:
        return _cycle(args)

    settings = RuntimeSettings.from_env()
    poll_seconds = args.poll_seconds or settings.scheduler_poll_seconds
    command_line = [
        sys.executable,
        "-m",
        "bot_ofertas.cli",
        "cycle",
        "--crawl-limit",
        str(args.crawl_limit),
        "--analysis-limit",
        str(args.analysis_limit),
        "--notification-limit",
        str(args.notification_limit),
    ]

    def execute_cycle() -> None:
        completed = subprocess.run(
            command_line,
            cwd=_PROJECT_ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"el ciclo terminó con código {completed.returncode}")

    print(
        f"Monitor iniciado; ejecutará un ciclo cada {poll_seconds} segundos. "
        "Presiona Ctrl+C para detenerlo."
    )
    LocalScheduler(execute_cycle, poll_seconds).run()
    print("Monitor detenido.")
    return 0


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "nunca"
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_LIMA_TIMEZONE).isoformat(timespec="minutes")


def _format_price(currency: str, value: object | None) -> str:
    if value is None:
        return "no disponible"
    return f"{currency} {value}"


def _format_variant(variant: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(variant.items()))


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "db" and args.db_command == "upgrade":
        return _upgrade_database()
    if args.command == "config" and args.config_command == "show":
        return _show_config()
    if args.command == "store" and args.store_command == "list":
        return _list_stores()
    if args.command == "product" and args.product_command == "add":
        return _add_product(args)
    if args.command == "product" and args.product_command == "list":
        return _list_products()
    if args.command == "product" and args.product_command == "enable":
        return _set_product_active(args.product_id, active=True)
    if args.command == "product" and args.product_command == "disable":
        return _set_product_active(args.product_id, active=False)
    if args.command == "product" and args.product_command == "variant":
        return _set_product_variant(args.product_id, args.variant)
    if args.command == "equivalence" and args.equivalence_command == "create":
        return _create_equivalence(args)
    if args.command == "equivalence" and args.equivalence_command == "list":
        return _list_equivalences()
    if args.command == "equivalence" and args.equivalence_command == "add-product":
        return _change_equivalence_membership(
            group_id=args.group_id,
            product_id=args.product_id,
            add=True,
        )
    if args.command == "equivalence" and args.equivalence_command == "remove-product":
        return _change_equivalence_membership(
            group_id=args.group_id,
            product_id=args.product_id,
            add=False,
        )
    if args.command == "crawl":
        return _crawl(args)
    if args.command == "history":
        return _history(args.limit)
    if args.command == "analyze":
        return _analyze(args.limit)
    if args.command == "notify":
        return _notify(args.limit)
    if args.command == "alert" and args.alert_command == "list":
        return _list_alerts(args.limit, include_all=args.all)
    if args.command == "confirmation" and args.confirmation_command == "list":
        return _list_confirmations(args.limit)
    if args.command == "cycle":
        return _cycle(args)
    if args.command == "run":
        return _run_monitor(args)
    raise RuntimeError("comando no reconocido")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("\nOperación cancelada.", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print(
            "Error: no se pudo completar la operación en PostgreSQL. "
            "Verifica que Docker esté iniciado y que el contenedor esté saludable.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
