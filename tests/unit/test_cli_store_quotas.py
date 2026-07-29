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
        "cassinelli": 4,
        "coolbox": 4,
        "curacao": 3,
        "efe": 3,
        "oechsle": 3,
        "promart": 3,
    }
    assert calls == [
        ("cassinelli", 4, 60),
        ("coolbox", 4, 30),
        ("curacao", 3, 60),
        ("efe", 3, 60),
        ("oechsle", 3, 60),
        ("promart", 3, 60),
    ]
    assert engine.disposed is True
