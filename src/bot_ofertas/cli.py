"""Command-line entry point for the local price-monitoring workflow."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Sequence
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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bot_ofertas.crawling import settings as crawling_settings
from bot_ofertas.storage.config import DatabaseSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from bot_ofertas.storage.models import (
    PriceObservationRecord,
    StoreCrawlState,
    TrackedProduct,
)
from bot_ofertas.storage.repositories import (
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
_CRAWL_LEASE_DURATION = timedelta(hours=2)


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bot-ofertas",
        description="Monitor responsable de precios públicos en tiendas online.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    db_parser = commands.add_parser("db", help="Administra el esquema de PostgreSQL.")
    db_commands = db_parser.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("upgrade", help="Aplica todas las migraciones pendientes.")

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
    add_parser.add_argument("--brand", help="Marca esperada para validaciones futuras.")
    add_parser.add_argument("--model", help="Modelo esperado para validaciones futuras.")
    add_parser.add_argument(
        "--interval",
        type=_integer_between(30, 525_600),
        default=60,
        metavar="MINUTOS",
        help="Minutos entre consultas (mínimo 30; predeterminado: 60).",
    )
    product_commands.add_parser("list", help="Lista los productos registrados.")

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
    return parser


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


def _add_product(args: argparse.Namespace) -> int:
    label = args.label.strip()
    if not label:
        raise ValueError("--label no puede estar vacío")

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
        print(f"  URL: {product.source_url}")
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
            f"SKU: {observation.sku} | Vendedor: {observation.seller_name}"
        )
        print(f"  Disponibilidad: {availability}")
        print(f"  URL: {observation.source_url}")
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


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "db" and args.db_command == "upgrade":
        return _upgrade_database()
    if args.command == "store" and args.store_command == "list":
        return _list_stores()
    if args.command == "product" and args.product_command == "add":
        return _add_product(args)
    if args.command == "product" and args.product_command == "list":
        return _list_products()
    if args.command == "crawl":
        return _crawl(args)
    if args.command == "history":
        return _history(args.limit)
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
