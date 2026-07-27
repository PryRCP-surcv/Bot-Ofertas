from types import SimpleNamespace
from uuid import uuid4

import pytest

from bot_ofertas.crawling.pipelines import (
    _should_pause_store,
    _spider_store_slug,
    _spider_targets,
)


def test_spider_targets_keep_scheduler_lease_tokens() -> None:
    first_id = uuid4()
    second_id = uuid4()
    lease_token = uuid4()
    second_lease_token = uuid4()
    spider = SimpleNamespace(
        targets=[
            {
                "tracked_product_id": str(first_id),
                "url": "https://example.test/first",
                "lease_token": str(lease_token),
            },
            {
                "tracked_product_id": second_id,
                "url": "https://example.test/second",
                "lease_token": second_lease_token,
            },
        ]
    )

    requested, target_contexts, invalid = _spider_targets(spider)

    assert requested == 2
    assert target_contexts[first_id].source_url == "https://example.test/first"
    assert target_contexts[first_id].lease_token == lease_token
    assert target_contexts[second_id].source_url == "https://example.test/second"
    assert target_contexts[second_id].lease_token == second_lease_token
    assert invalid == 0


def test_spider_targets_reject_invalid_leases_and_duplicate_products() -> None:
    product_id = uuid4()
    spider = SimpleNamespace(
        targets=[
            {
                "tracked_product_id": str(product_id),
                "url": "https://example.test/first",
                "lease_token": "not-a-uuid",
            },
            {
                "tracked_product_id": str(product_id),
                "url": "https://example.test/first",
                "lease_token": str(uuid4()),
            },
            {
                "tracked_product_id": str(product_id),
                "url": "https://example.test/duplicate",
                "lease_token": str(uuid4()),
            },
        ]
    )

    requested, target_contexts, invalid = _spider_targets(spider)

    assert requested == 3
    assert set(target_contexts) == {product_id}
    assert target_contexts[product_id].lease_token is not None
    assert invalid == 2


def test_spider_store_slug_is_required_and_normalized() -> None:
    assert _spider_store_slug(SimpleNamespace(store_slug=" CoolBox ")) == "coolbox"

    with pytest.raises(RuntimeError, match="store_slug"):
        _spider_store_slug(SimpleNamespace())


def test_spider_targets_require_a_scheduler_lease() -> None:
    product_id = uuid4()
    spider = SimpleNamespace(
        targets=[
            {
                "tracked_product_id": str(product_id),
                "url": "https://example.test/product",
            }
        ]
    )

    requested, target_contexts, invalid = _spider_targets(spider)

    assert requested == 1
    assert target_contexts == {}
    assert invalid == 1


def test_store_pause_detects_block_reasons_and_http_stats() -> None:
    assert _should_pause_store(
        reason="coolbox_blocked_http_429",
        stats={},
    )
    assert _should_pause_store(
        reason="finished",
        stats={"downloader/response_status_count/403": 1},
    )
    assert not _should_pause_store(
        reason="coolbox_invalid_payload",
        stats={"downloader/response_status_count/200": 1},
    )
