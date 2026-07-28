from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Session, configure_mappers

from bot_ofertas.storage.admin import (
    IdempotencyConflictError,
    OptimisticConcurrencyError,
    RuntimePolicyRepository,
    _check_expected_revision,
    _check_idempotent_fingerprint,
    _fingerprint,
)
from bot_ofertas.storage.models import (
    AdminConfigRevision,
    Base,
    CrawlJob,
    CrawlJobItem,
    DealDetection,
    TrackedProduct,
)


def _constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
        and constraint.name is not None
    }


def test_phase4_models_register_control_plane_tables_and_product_versioning() -> None:
    configure_mappers()

    assert {
        "admin_config_revisions",
        "crawl_jobs",
        "crawl_job_items",
    }.issubset(Base.metadata.tables)
    assert TrackedProduct.__table__.c.version.nullable is False
    assert TrackedProduct.__table__.c.archived_at.nullable is True
    assert "ck_tracked_products_archived_inactive" in _constraint_names(TrackedProduct)
    assert "uq_crawl_jobs_idempotency_hash" in _constraint_names(CrawlJob)
    assert "uq_crawl_job_items_job_product" in _constraint_names(CrawlJobItem)


def test_detection_identity_includes_the_effective_policy_fingerprint() -> None:
    constraint = next(
        item
        for item in DealDetection.__table__.constraints
        if item.name == "uq_deal_detections_observation_version_policy"
    )

    assert [column.name for column in constraint.columns] == [
        "observation_id",
        "detector_version",
        "policy_fingerprint",
    ]
    assert DealDetection.__table__.c.config_revision_id.nullable is True
    assert DealDetection.__table__.c.policy_fingerprint.nullable is False
    assert DealDetection.__table__.c.policy_fingerprint.default is None
    assert DealDetection.__table__.c.policy_fingerprint.server_default is None


def test_policy_fingerprint_is_canonical_and_decimal_safe() -> None:
    first = {
        "detection": {
            "good_deal_percent": Decimal("20.00"),
            "minimum_history_samples": 3,
        },
        "confirmation": {"required": True},
    }
    reordered = {
        "confirmation": {"required": True},
        "detection": {
            "minimum_history_samples": 3,
            "good_deal_percent": Decimal("20.00"),
        },
    }

    assert _fingerprint(first) == _fingerprint(reordered)
    assert len(_fingerprint(first)) == 64


@pytest.mark.parametrize(
    "policy",
    [
        {"telegram_bot_token": "secret"},
        {"database": {"password": "secret"}},
        {"nested": [{"provider_api_key": "secret"}]},
    ],
)
def test_runtime_policy_repository_rejects_secret_bearing_keys(
    policy: dict[str, object],
) -> None:
    repository = RuntimePolicyRepository(Mock(spec=Session))

    with pytest.raises(ValueError, match="must not contain secrets"):
        repository.replace(
            policy=policy,
            expected_revision=None,
            changed_by="local-admin",
        )


def test_optimistic_revision_guard_rejects_a_stale_editor() -> None:
    with pytest.raises(OptimisticConcurrencyError, match="current revision is 8"):
        _check_expected_revision(expected=7, actual=8)

    _check_expected_revision(expected=None, actual=None)
    _check_expected_revision(expected=8, actual=8)


def test_policy_replace_is_idempotent_before_taking_the_writer_lock() -> None:
    first_session = Mock(spec=Session)
    first_session.scalar.side_effect = [None, None, None]
    first_repository = RuntimePolicyRepository(first_session)
    first = first_repository.replace(
        policy={"detection": {"good_deal_percent": "20"}},
        expected_revision=None,
        changed_by="local-admin",
        change_reason="Configuración inicial",
        idempotency_key="policy-request-1",
    )
    first.revision.id = 1

    retry_session = Mock(spec=Session)
    retry_session.scalar.return_value = first.revision
    retry = RuntimePolicyRepository(retry_session).replace(
        policy={"detection": {"good_deal_percent": "20"}},
        expected_revision=None,
        changed_by="local-admin",
        change_reason="Configuración inicial",
        idempotency_key="policy-request-1",
    )

    assert first.inserted is True
    assert retry.inserted is False
    assert retry.revision is first.revision
    retry_session.execute.assert_not_called()


def test_idempotency_guard_rejects_the_same_key_for_another_payload() -> None:
    _check_idempotent_fingerprint(stored="a" * 64, requested="a" * 64)

    with pytest.raises(IdempotencyConflictError, match="different request"):
        _check_idempotent_fingerprint(stored="a" * 64, requested="b" * 64)


def test_admin_config_revision_keeps_a_complete_audit_chain() -> None:
    columns = AdminConfigRevision.__table__.c

    assert columns.previous_revision_id.nullable is True
    assert columns.restored_from_revision_id.nullable is True
    assert columns.changed_by.nullable is False
    assert columns.change_reason.nullable is True
    assert "ck_admin_config_revisions_policy_object" in _constraint_names(
        AdminConfigRevision
    )
