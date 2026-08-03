from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import bot_ofertas.cli as cli
from bot_ofertas.storage.repositories import ProductClaimBatch
from bot_ofertas.stores import build_store_registry


def test_claim_batches_enforce_phase2_store_caps_and_intervals(monkeypatch) -> None:
    calls: list[tuple[str, int, int]] = []

    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class FakeRepository:
        def __init__(self, _session) -> None:
            pass

        def claim_due(
            self,
            *,
            limit,
            store_slugs,
            minimum_interval_minutes,
            **_kwargs,
        ) -> ProductClaimBatch:
            store_slug = next(iter(store_slugs))
            calls.append((store_slug, limit, minimum_interval_minutes))
            products = tuple(
                SimpleNamespace(id=uuid4(), store_slug=store_slug)
                for _position in range(limit)
            )
            return ProductClaimBatch(
                token=uuid4(),
                products=products,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    engine = FakeEngine()

    @contextmanager
    def fake_session_scope(_factory):
        yield object()

    monkeypatch.setattr(cli, "_database_engine", lambda: engine)
    monkeypatch.setattr(cli, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(cli, "session_scope", fake_session_scope)
    monkeypatch.setattr(cli, "TrackedProductRepository", FakeRepository)
    monkeypatch.setattr(cli, "_rotated_adapters", lambda adapters: adapters)

    adapters = build_store_registry(include_plugins=False).enabled_adapters
    batches = cli._claim_due_batches(  # noqa: SLF001
        force=False,
        limit=20,
        adapters=adapters,
    )

    claimed_per_store: dict[str, int] = {}
    for batch in batches:
        for product in batch.products:
            claimed_per_store[product.store_slug] = (
                claimed_per_store.get(product.store_slug, 0) + 1
            )

    assert claimed_per_store == {
        "casaideas": 2,
        "cassinelli": 2,
        "coolbox": 2,
        "curacao": 2,
        "efe": 1,
        "estilos": 1,
        "falabella": 1,
        "footloose": 1,
        "metro": 1,
        "oechsle": 1,
        "plazavea": 1,
        "promart": 1,
        "topitop": 1,
        "tottus": 1,
        "vega": 1,
        "wong": 1,
    }
    assert calls == [
        ("casaideas", 2, 60),
        ("cassinelli", 2, 60),
        ("coolbox", 2, 30),
        ("curacao", 2, 60),
        ("efe", 1, 60),
        ("estilos", 1, 60),
        ("falabella", 1, 60),
        ("footloose", 1, 60),
        ("metro", 1, 60),
        ("oechsle", 1, 60),
        ("plazavea", 1, 60),
        ("promart", 1, 60),
        ("topitop", 1, 60),
        ("tottus", 1, 60),
        ("vega", 1, 60),
        ("wong", 1, 60),
    ]
    assert engine.disposed is True


def test_catalog_expansion_rotates_across_stores_without_starvation() -> None:
    candidates = [
        SimpleNamespace(store_slug=store_slug, marker=marker)
        for marker, store_slug in enumerate(
            (
                "coolbox",
                "coolbox",
                "coolbox",
                "efe",
                "efe",
                "promart",
            )
        )
    ]

    selected = cli._round_robin_candidates(candidates, limit=5)  # noqa: SLF001

    assert [(item.store_slug, item.marker) for item in selected] == [
        ("coolbox", 0),
        ("efe", 3),
        ("promart", 5),
        ("coolbox", 1),
        ("efe", 4),
    ]
