"""Resolve and revise the non-secret runtime policy shared by CLI and API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session

from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.storage.admin import PolicyReplaceResult, RuntimePolicyRepository


@dataclass(frozen=True, slots=True)
class EffectiveRuntimePolicy:
    settings: RuntimeSettings
    revision_id: int | None
    changed_by: str | None = None
    change_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimePolicyChange:
    policy: EffectiveRuntimePolicy
    inserted: bool


def resolve_runtime_policy(session: Session) -> EffectiveRuntimePolicy:
    """Overlay the latest audited database snapshot on environment defaults."""

    base = RuntimeSettings.from_env()
    revision = RuntimePolicyRepository(session).current()
    if revision is None:
        return EffectiveRuntimePolicy(settings=base, revision_id=None)
    settings = base.with_policy_overrides(
        revision.policy,
        revision_id=revision.id,
    )
    return EffectiveRuntimePolicy(
        settings=settings,
        revision_id=revision.id,
        changed_by=revision.changed_by,
        change_reason=revision.change_reason,
    )


def replace_runtime_policy(
    session: Session,
    *,
    overrides: Mapping[str, object],
    expected_revision: int | None,
    changed_by: str,
    change_reason: str | None = None,
    idempotency_key: str | None = None,
) -> RuntimePolicyChange:
    """Validate a partial update and persist a complete immutable snapshot."""

    current = resolve_runtime_policy(session)
    updated = current.settings.with_policy_overrides(overrides)
    result: PolicyReplaceResult = RuntimePolicyRepository(session).replace(
        policy=updated.public_policy(),
        expected_revision=expected_revision,
        changed_by=changed_by,
        change_reason=change_reason,
        idempotency_key=idempotency_key,
    )
    effective = updated.with_policy_overrides(
        result.revision.policy,
        revision_id=result.revision.id,
    )
    return RuntimePolicyChange(
        policy=EffectiveRuntimePolicy(
            settings=effective,
            revision_id=result.revision.id,
            changed_by=result.revision.changed_by,
            change_reason=result.revision.change_reason,
        ),
        inserted=result.inserted,
    )


__all__ = [
    "EffectiveRuntimePolicy",
    "RuntimePolicyChange",
    "replace_runtime_policy",
    "resolve_runtime_policy",
]
