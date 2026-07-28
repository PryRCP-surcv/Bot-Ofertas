import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot_ofertas.crawling.oechsle import parse_oechsle_products
from bot_ofertas.crawling.promart import parse_promart_products
from bot_ofertas.detection import DetectorConfig
from bot_ofertas.domain import PriceObservation
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.services.detection import DetectionService
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import DealDetection
from bot_ofertas.storage.repositories import (
    CrawlRunRepository,
    PriceObservationRepository,
    TrackedProductRepository,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_phase2_parsers_persist_and_block_unverified_prices_before_alerting() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    observed_at = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)

    try:
        products = TrackedProductRepository(session)
        observations = PriceObservationRepository(session)
        saved_ids = []

        oechsle_url = "https://www.oechsle.pe/producto-demo-3000/p"
        oechsle_product = products.add(
            store_slug="oechsle",
            source_url=oechsle_url,
            label="Producto de integración Oechsle",
            check_interval_minutes=60,
        )
        oechsle_run = CrawlRunRepository(session).start(
            store_slug="oechsle",
            spider_name="oechsle_phase2_integration",
            requested_url_count=1,
        )
        oechsle_values = next(
            values
            for values in parse_oechsle_products(
                _load_fixture("oechsle_catalog_product.json"),
                source_url=oechsle_url,
                tracked_product_id=oechsle_product.id,
                observed_at=observed_at,
            )
            if values["sku"] == "sku-blanco" and values["seller_id"] == "1"
        )
        assert "conditional_promotion_price" in oechsle_values["quality_flags"]
        saved_ids.append(
            observations.save(
                run_id=oechsle_run.id,
                observation=PriceObservation(**oechsle_values),
            ).observation_id
        )

        promart_url = "https://www.promart.pe/producto-demo-promart/p"
        promart_product = products.add(
            store_slug="promart",
            source_url=promart_url,
            label="Producto de integración Promart",
            check_interval_minutes=60,
        )
        promart_run = CrawlRunRepository(session).start(
            store_slug="promart",
            spider_name="promart_phase2_integration",
            requested_url_count=1,
        )
        promart_values = next(
            values
            for values in parse_promart_products(
                _load_fixture("promart_catalog_product.json"),
                source_url=promart_url,
                tracked_product_id=promart_product.id,
                observed_at=observed_at,
            )
            if values["sku"] == "sku-negro" and values["seller_id"] == "1"
        )
        assert "location_context_unverified" in promart_values["quality_flags"]
        assert "unsupported_price_basis" not in promart_values["quality_flags"]
        saved_ids.append(
            observations.save(
                run_id=promart_run.id,
                observation=PriceObservation(**promart_values),
            ).observation_id
        )

        summary = DetectionService(
            session,
            RuntimeSettings(
                detector_config=DetectorConfig(minimum_history_samples=1)
            ),
        ).process_new(limit=10)
        detections = list(
            session.scalars(
                select(DealDetection).where(
                    DealDetection.observation_id.in_(saved_ids)
                )
            )
        )

        assert summary.processing_errors == 0
        assert len(detections) == 2
        assert all(detection.classification == "none" for detection in detections)
        assert all(
            "quality_flags_present" in detection.rejection_reasons
            for detection in detections
        )
        assert all(
            detection.notification_status == "not_applicable"
            for detection in detections
        )
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
