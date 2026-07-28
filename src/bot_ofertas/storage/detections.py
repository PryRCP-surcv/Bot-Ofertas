"""Persistence and deduplication for pure deal-detector decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bot_ofertas.detection import (
    DealClassification,
    DetectionDecision,
    SignalAssessment,
    SignalKind,
    canonicalize_variant,
    commercial_condition_signatures,
    conditional_price_families,
)
from bot_ofertas.domain import Availability
from bot_ofertas.storage.models import (
    DealDetection,
    EquivalentProductGroup,
    EquivalentProductMembership,
    NotificationDelivery,
    OfferAlertState,
    OfferConfirmationState,
    PriceObservationRecord,
    TrackedProduct,
)

_CLASSIFICATION_RANK = {
    DealClassification.NONE.value: 0,
    DealClassification.GOOD_DEAL.value: 1,
    DealClassification.EXCEPTIONAL_DEAL.value: 2,
    DealClassification.POSSIBLE_PRICE_ERROR.value: 3,
}
_LEGACY_POLICY_FINGERPRINT = "0" * 64


def _normalized_policy_fingerprint(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("policy_fingerprint must be a lowercase SHA-256 digest")
    return normalized
_CLASSIFICATION_SCORE = {
    DealClassification.NONE.value: 0,
    DealClassification.GOOD_DEAL.value: 55,
    DealClassification.EXCEPTIONAL_DEAL.value: 80,
    DealClassification.POSSIBLE_PRICE_ERROR.value: 95,
}


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return resolved.astimezone(UTC)


def _timestamp(session: Session, value: datetime | None) -> datetime:
    if value is not None:
        return _utc(value)
    timestamp = session.scalar(select(func.clock_timestamp()))
    if timestamp is None:  # pragma: no cover - PostgreSQL always returns a value
        raise RuntimeError("database clock did not return a timestamp")
    return _utc(timestamp)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _signal_metrics(signal: SignalAssessment) -> dict[str, Any]:
    return {
        "eligible": signal.eligible,
        "reference_price": _decimal_text(signal.reference_price),
        "discount_ratio": _decimal_text(signal.discount_ratio),
        "discount_percent": _decimal_text(signal.discount_percent),
        "classification": signal.classification.value,
        "sample_count": signal.sample_count,
        "window_days": signal.window_days,
    }


def _positive_discount(signal: SignalAssessment) -> Decimal | None:
    discount = signal.discount_percent
    return discount if discount is not None and discount > 0 else None


def _offer_key(
    observation: PriceObservationRecord,
    *,
    condition_families: tuple[str, ...] = (),
    condition_signatures: tuple[str, ...] = (),
) -> str:
    identity = {
        "tracked_product_id": str(observation.tracked_product_id or ""),
        "store_slug": observation.store_slug,
        "external_product_id": observation.external_product_id,
        "sku": observation.sku,
        "seller_id": observation.seller_id,
        "variant": sorted(canonicalize_variant(observation.variant).items()),
        "condition": observation.condition.value,
        "currency": observation.currency,
    }
    # Preserve the original hash for ordinary prices while isolating commercial
    # conditions. Different cards, coupons, or quantity thresholds must never
    # confirm (or suppress) each other for the same product.
    if condition_families or condition_signatures:
        identity["commercial_conditions"] = {
            "families": list(condition_families),
            "signatures": list(condition_signatures),
        }
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _signal(
    decision: DetectionDecision,
    kind: SignalKind,
) -> SignalAssessment:
    return next(signal for signal in decision.signals if signal.kind is kind)


def _primary_signal(decision: DetectionDecision) -> SignalAssessment | None:
    eligible = [
        signal
        for signal in decision.signals
        if signal.eligible and signal.reference_price is not None
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            _CLASSIFICATION_RANK[item.classification.value],
            (item.discount_ratio if item.discount_ratio is not None else Decimal("-1")),
        ),
    )


def _score(decision: DetectionDecision) -> int:
    base = _CLASSIFICATION_SCORE[decision.classification.value]
    supporting_signals = sum(
        1 for signal in decision.signals if signal.classification is not DealClassification.NONE
    )
    return min(100, base + max(0, supporting_signals - 1) * 2)


def _confidence_level(score: int) -> str:
    if score <= 0:
        return "none"
    if score < 40:
        return "low"
    if score < 70:
        return "medium"
    return "high"


@dataclass(slots=True)
class _ConfirmationOutcome:
    status: str
    count: int = 0
    reference_observation_id: int | None = None
    state: OfferConfirmationState | None = None
    state_tracks_current: bool = False
    previous_detection: DealDetection | None = None
    previous_status: str | None = None

    @property
    def pending(self) -> bool:
        return self.status == "awaiting"

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass(frozen=True, slots=True)
class DetectionSaveResult:
    detection: DealDetection
    inserted: bool
    notification_reserved: bool
    confirmation_pending: bool = False
    confirmed: bool = False
    low_confidence_suppressed: bool = False


class DetectionRepository:
    """Claim observations, persist decisions, and serialize alert deduplication."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def unprocessed_observations(
        self,
        *,
        detector_version: str,
        policy_fingerprint: str = _LEGACY_POLICY_FINGERPRINT,
        reanalyze_policy: bool = False,
        limit: int = 100,
    ) -> list[PriceObservationRecord]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        normalized_version = detector_version.strip()
        if not normalized_version:
            raise ValueError("detector_version must not be empty")
        normalized_fingerprint = _normalized_policy_fingerprint(policy_fingerprint)
        if not isinstance(reanalyze_policy, bool):
            raise TypeError("reanalyze_policy must be a boolean")
        processed_filters = [
            DealDetection.observation_id == PriceObservationRecord.id,
            DealDetection.detector_version == normalized_version,
        ]
        if reanalyze_policy:
            processed_filters.append(
                DealDetection.policy_fingerprint == normalized_fingerprint
            )
        statement: Select[tuple[PriceObservationRecord]] = (
            select(PriceObservationRecord)
            .where(
                ~exists(
                    select(DealDetection.id).where(*processed_filters)
                )
            )
            .order_by(
                PriceObservationRecord.observed_at.asc(),
                PriceObservationRecord.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(statement))

    def history_before(
        self,
        observation: PriceObservationRecord,
        *,
        limit: int = 2_500,
        max_age_days: int = 90,
    ) -> list[PriceObservationRecord]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        if max_age_days <= 0 or max_age_days > 3_650:
            raise ValueError("max_age_days must be between 1 and 3650")
        if observation.tracked_product_id is None:
            return []
        earliest = observation.observed_at - timedelta(days=max_age_days)
        statement = (
            select(PriceObservationRecord)
            .where(
                PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
                PriceObservationRecord.store_slug == observation.store_slug,
                PriceObservationRecord.external_product_id == observation.external_product_id,
                PriceObservationRecord.sku == observation.sku,
                PriceObservationRecord.seller_id == observation.seller_id,
                PriceObservationRecord.condition == observation.condition,
                PriceObservationRecord.currency == observation.currency,
                PriceObservationRecord.observed_at < observation.observed_at,
                PriceObservationRecord.observed_at >= earliest,
                PriceObservationRecord.price.is_not(None),
                PriceObservationRecord.price > 0,
                PriceObservationRecord.availability == Availability.IN_STOCK,
                PriceObservationRecord.is_marketplace.is_(False),
                PriceObservationRecord.quality_flags == [],
            )
            .order_by(
                PriceObservationRecord.observed_at.desc(),
                PriceObservationRecord.id.desc(),
            )
            .limit(min(limit * 4, 10_000))
        )
        expected_variant = canonicalize_variant(observation.variant)
        history: list[PriceObservationRecord] = []
        for item in self._session.scalars(statement):
            try:
                comparable_variant = canonicalize_variant(item.variant)
            except ValueError:
                continue
            if comparable_variant == expected_variant:
                history.append(item)
            if len(history) == limit:
                break
        history.reverse()
        return history

    def lifetime_minimum_before(
        self,
        observation: PriceObservationRecord,
    ) -> Decimal | None:
        """Return the all-time minimum for the same exact persisted offer."""

        if observation.tracked_product_id is None:
            return None
        return self._session.scalar(
            select(func.min(PriceObservationRecord.price)).where(
                PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
                PriceObservationRecord.store_slug == observation.store_slug,
                PriceObservationRecord.external_product_id == observation.external_product_id,
                PriceObservationRecord.sku == observation.sku,
                PriceObservationRecord.seller_id == observation.seller_id,
                PriceObservationRecord.condition == observation.condition,
                PriceObservationRecord.currency == observation.currency,
                PriceObservationRecord.variant == observation.variant,
                PriceObservationRecord.observed_at < observation.observed_at,
                PriceObservationRecord.price.is_not(None),
                PriceObservationRecord.price > 0,
                PriceObservationRecord.availability == Availability.IN_STOCK,
                PriceObservationRecord.is_marketplace.is_(False),
                PriceObservationRecord.quality_flags == [],
            )
        )

    def equivalent_observations_before(
        self,
        observation: PriceObservationRecord,
        *,
        max_age_hours: int = 24,
        limit: int = 20,
    ) -> list[PriceObservationRecord]:
        """Return at most one fresh verified equivalent from each other store."""

        if observation.tracked_product_id is None:
            return []
        if max_age_hours <= 0 or max_age_hours > 720:
            raise ValueError("max_age_hours must be between 1 and 720")
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        group_row = self._session.execute(
            select(
                EquivalentProductMembership.group_id,
                EquivalentProductGroup.canonical_variant,
            )
            .join(
                EquivalentProductGroup,
                EquivalentProductGroup.id == EquivalentProductMembership.group_id,
            )
            .where(
                EquivalentProductMembership.tracked_product_id == observation.tracked_product_id,
                EquivalentProductGroup.active.is_(True),
            )
        ).one_or_none()
        if group_row is None:
            return []
        group_id, canonical_variant = group_row
        member_ids = select(EquivalentProductMembership.tracked_product_id).where(
            EquivalentProductMembership.group_id == group_id,
            EquivalentProductMembership.tracked_product_id != observation.tracked_product_id,
        )
        earliest = observation.observed_at - timedelta(hours=max_age_hours)
        statement = (
            select(PriceObservationRecord)
            .where(
                PriceObservationRecord.tracked_product_id.in_(member_ids),
                PriceObservationRecord.store_slug != observation.store_slug,
                PriceObservationRecord.observed_at < observation.observed_at,
                PriceObservationRecord.observed_at >= earliest,
                PriceObservationRecord.currency == observation.currency,
                PriceObservationRecord.condition == observation.condition,
                PriceObservationRecord.price.is_not(None),
                PriceObservationRecord.price > 0,
                PriceObservationRecord.availability == Availability.IN_STOCK,
                PriceObservationRecord.is_marketplace.is_(False),
                PriceObservationRecord.quality_flags == [],
            )
            .order_by(
                PriceObservationRecord.observed_at.desc(),
                PriceObservationRecord.id.desc(),
            )
            .limit(min(limit * 20, 1_000))
        )
        expected_variant = canonicalize_variant(canonical_variant)
        seen_stores: set[str] = set()
        equivalents: list[PriceObservationRecord] = []
        for item in self._session.scalars(statement):
            if item.store_slug in seen_stores:
                continue
            try:
                comparable_variant = canonicalize_variant(item.variant)
            except ValueError:
                continue
            if comparable_variant != expected_variant:
                continue
            equivalents.append(item)
            seen_stores.add(item.store_slug)
            if len(equivalents) == limit:
                break
        return equivalents

    def has_ambiguous_variants(
        self,
        observation: PriceObservationRecord,
    ) -> bool:
        """Detect multiple SKU/variant identities returned for one tracked page."""

        if observation.tracked_product_id is None:
            return False
        statement = select(
            PriceObservationRecord.sku,
            PriceObservationRecord.variant,
        ).where(
            PriceObservationRecord.run_id == observation.run_id,
            PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
            PriceObservationRecord.external_product_id == observation.external_product_id,
            PriceObservationRecord.is_marketplace.is_(False),
        )
        identities: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        for sku, variant in self._session.execute(statement):
            try:
                canonical_variant = canonicalize_variant(variant)
            except ValueError:
                continue
            identities.add((sku, tuple(sorted(canonical_variant.items()))))
            if len(identities) > 1:
                return True
        return False

    def tracked_product(
        self,
        observation: PriceObservationRecord,
    ) -> TrackedProduct | None:
        if observation.tracked_product_id is None:
            return None
        return self._session.scalar(
            select(TrackedProduct)
            .where(TrackedProduct.id == observation.tracked_product_id)
            .with_for_update()
        )

    def is_latest_snapshot(self, observation: PriceObservationRecord) -> bool:
        """Return whether no newer crawl snapshot exists for the tracked URL."""

        if observation.tracked_product_id is None:
            return False
        newer_id = self._session.scalar(
            select(PriceObservationRecord.id)
            .where(
                PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
                PriceObservationRecord.observed_at > observation.observed_at,
            )
            .limit(1)
        )
        return newer_id is None

    def save(
        self,
        *,
        observation: PriceObservationRecord,
        decision: DetectionDecision,
        detector_version: str,
        policy_fingerprint: str = _LEGACY_POLICY_FINGERPRINT,
        config_revision_id: int | None = None,
        cooldown: timedelta,
        significant_improvement_ratio: Decimal,
        confirmation_required: bool = True,
        confirmation_minimum_interval: timedelta = timedelta(minutes=30),
        confirmation_max_age: timedelta = timedelta(hours=3),
        confirmation_price_tolerance_ratio: Decimal = Decimal("0.03"),
        confirmation_confidence_bonus: int = 20,
        minimum_alert_confidence: int = 50,
        channel: str = "telegram",
        allow_notification: bool = True,
        detected_at: datetime | None = None,
    ) -> DetectionSaveResult:
        normalized_version = detector_version.strip()
        if not normalized_version:
            raise ValueError("detector_version must not be empty")
        normalized_fingerprint = _normalized_policy_fingerprint(policy_fingerprint)
        if config_revision_id is not None and config_revision_id <= 0:
            raise ValueError("config_revision_id must be positive")
        if cooldown <= timedelta(0):
            raise ValueError("cooldown must be positive")
        if not Decimal("0") <= significant_improvement_ratio < Decimal("1"):
            raise ValueError("significant_improvement_ratio must be between 0 and 1")
        if confirmation_minimum_interval < timedelta(minutes=30):
            raise ValueError("confirmation_minimum_interval must be at least 30 minutes")
        if confirmation_max_age <= confirmation_minimum_interval:
            raise ValueError("confirmation_max_age must be greater than the minimum interval")
        if not Decimal("0") <= confirmation_price_tolerance_ratio < Decimal("1"):
            raise ValueError("confirmation_price_tolerance_ratio must be between 0 and 1")
        if not 0 <= confirmation_confidence_bonus <= 100:
            raise ValueError("confirmation_confidence_bonus must be between 0 and 100")
        if not 0 <= minimum_alert_confidence <= 100:
            raise ValueError("minimum_alert_confidence must be between 0 and 100")
        normalized_channel = channel.strip().lower()
        if not normalized_channel:
            raise ValueError("channel must not be empty")
        timestamp = _timestamp(self._session, detected_at)

        existing = self._session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == observation.id,
                DealDetection.detector_version == normalized_version,
                DealDetection.policy_fingerprint == normalized_fingerprint,
            )
        )
        if existing is not None:
            return DetectionSaveResult(
                detection=existing,
                inserted=False,
                notification_reserved=existing.notification_status == "pending",
                confirmation_pending=existing.confirmation_status == "awaiting",
                confirmed=existing.confirmation_status == "confirmed",
            )

        condition_families = tuple(
            family.value for family in conditional_price_families(observation.quality_flags)
        )
        exact_condition_signatures = commercial_condition_signatures(observation.quality_flags)
        if exact_condition_signatures:
            condition_signatures = tuple(
                f"evidence:{signature}" for signature in exact_condition_signatures
            )
        elif condition_families:
            # Legacy or manually built observations may predate condition-evidence
            # signatures. Requiring the full public payload to repeat is a safe
            # fallback: unrelated conditions in the same family cannot confirm it.
            condition_signatures = (f"payload:{observation.source_payload_hash}",)
        else:
            condition_signatures = ()
        offer_key = _offer_key(
            observation,
            condition_families=condition_families,
            condition_signatures=condition_signatures,
        )
        confirmation = self._confirmation_outcome(
            observation=observation,
            decision=decision,
            offer_key=offer_key,
            required=confirmation_required,
            allow_state_change=allow_notification,
            minimum_interval=confirmation_minimum_interval,
            max_age=confirmation_max_age,
            price_tolerance_ratio=confirmation_price_tolerance_ratio,
            policy_fingerprint=normalized_fingerprint,
            timestamp=timestamp,
        )
        confidence_score = min(
            100,
            decision.confidence_score
            + (confirmation_confidence_bonus if confirmation.confirmed else 0),
        )
        confidence_level = _confidence_level(confidence_score)
        confirmation_gate_open = confirmation.status in {
            "confirmed",
            "not_required",
        }
        confidence_gate_open = confidence_score >= minimum_alert_confidence
        should_notify = False
        if (
            decision.should_alert
            and allow_notification
            and confirmation_gate_open
            and confidence_gate_open
        ):
            should_notify = self._reserve_notification(
                observation=observation,
                decision=decision,
                offer_key=offer_key,
                channel=normalized_channel,
                cooldown=cooldown,
                significant_improvement_ratio=significant_improvement_ratio,
                timestamp=timestamp,
            )

        primary = _primary_signal(decision)
        previous = _signal(decision, SignalKind.PREVIOUS_PRICE)
        median_7d = _signal(decision, SignalKind.MEDIAN_7D)
        median_30d = _signal(decision, SignalKind.MEDIAN_30D)
        median_90d = _signal(decision, SignalKind.MEDIAN_90D)
        historical_minimum = _signal(decision, SignalKind.HISTORICAL_MINIMUM)
        equivalent_median = _signal(decision, SignalKind.EQUIVALENT_MEDIAN)
        list_price = _signal(decision, SignalKind.LIST_PRICE)
        notification_status = (
            "pending"
            if should_notify
            else "awaiting_confirmation"
            if decision.should_alert and confirmation.pending
            else "suppressed"
            if decision.should_alert
            else "not_applicable"
        )
        reasons = [
            f"{signal.kind.value}:{signal.classification.value}"
            for signal in decision.signals
            if signal.classification is not DealClassification.NONE
        ]
        detection = DealDetection(
            observation_id=observation.id,
            detector_version=normalized_version,
            policy_fingerprint=normalized_fingerprint,
            config_revision_id=config_revision_id,
            tracked_product_id=observation.tracked_product_id,
            offer_key=offer_key,
            classification=decision.classification.value,
            eligible=decision.is_valid,
            score=_score(decision),
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            current_price=decision.current_price,
            reference_price=primary.reference_price if primary is not None else None,
            previous_price=previous.reference_price,
            median_price=median_90d.reference_price,
            median_price_7d=median_7d.reference_price,
            median_price_30d=median_30d.reference_price,
            median_price_90d=median_90d.reference_price,
            historical_min_price=historical_minimum.reference_price,
            equivalent_median_price=equivalent_median.reference_price,
            drop_from_previous_pct=_positive_discount(previous),
            drop_from_median_pct=_positive_discount(median_90d),
            drop_from_median_7d_pct=_positive_discount(median_7d),
            drop_from_median_30d_pct=_positive_discount(median_30d),
            drop_from_median_90d_pct=_positive_discount(median_90d),
            drop_from_equivalent_pct=_positive_discount(equivalent_median),
            list_discount_pct=_positive_discount(list_price),
            reasons=reasons,
            rejection_reasons=[reason.value for reason in decision.rejection_reasons],
            metrics={
                "history_samples_used": decision.history_samples_used,
                "history_samples_ignored": decision.history_samples_ignored,
                "detector_version": normalized_version,
                "policy_fingerprint": normalized_fingerprint,
                "config_revision_id": config_revision_id,
                "quality_flags": {
                    "informational": list(decision.informational_quality_flags),
                    "blocking": list(decision.blocking_quality_flags),
                    "commercial_condition_families": list(condition_families),
                    "commercial_condition_signatures": list(condition_signatures),
                },
                "confidence": {
                    "base_score": decision.confidence_score,
                    "confirmation_bonus": (
                        confirmation_confidence_bonus if confirmation.confirmed else 0
                    ),
                    "final_score": confidence_score,
                    "level": confidence_level,
                    "minimum_to_alert": minimum_alert_confidence,
                    "corroborating_signal_count": (decision.corroborating_signal_count),
                },
                "confirmation": {
                    "status": confirmation.status,
                    "count": confirmation.count,
                    "reference_observation_id": (confirmation.reference_observation_id),
                    "minimum_interval_seconds": int(confirmation_minimum_interval.total_seconds()),
                    "maximum_age_seconds": int(confirmation_max_age.total_seconds()),
                    "price_tolerance_ratio": str(confirmation_price_tolerance_ratio),
                },
                "primary_signal_kind": (primary.kind.value if primary is not None else None),
                "signals": {
                    signal.kind.value: _signal_metrics(signal) for signal in decision.signals
                },
            },
            notification_status=notification_status,
            confirmation_status=confirmation.status,
            confirmation_count=confirmation.count,
            confirmation_observation_id=confirmation.reference_observation_id,
            confirmed_at=timestamp if confirmation.confirmed else None,
            detected_at=timestamp,
        )
        self._session.add(detection)
        self._session.flush()
        if confirmation.state is not None and confirmation.state_tracks_current:
            confirmation.state.candidate_detection_id = detection.id
            confirmation.state.updated_at = timestamp
        if confirmation.previous_detection is not None:
            confirmation.previous_detection.confirmation_status = (
                confirmation.previous_status or confirmation.previous_detection.confirmation_status
            )
            if confirmation.confirmed:
                confirmation.previous_detection.confirmation_count = confirmation.count
                confirmation.previous_detection.confirmation_observation_id = observation.id
                confirmation.previous_detection.confirmed_at = timestamp
        if should_notify:
            self._session.add(
                NotificationDelivery(
                    detection_id=detection.id,
                    channel=normalized_channel,
                    status="pending",
                    next_attempt_at=timestamp,
                )
            )
            self._session.flush()
        return DetectionSaveResult(
            detection=detection,
            inserted=True,
            notification_reserved=should_notify,
            confirmation_pending=confirmation.pending,
            confirmed=confirmation.confirmed,
            low_confidence_suppressed=(
                decision.should_alert and confirmation_gate_open and not confidence_gate_open
            ),
        )

    def _confirmation_outcome(
        self,
        *,
        observation: PriceObservationRecord,
        decision: DetectionDecision,
        offer_key: str,
        required: bool,
        allow_state_change: bool,
        minimum_interval: timedelta,
        max_age: timedelta,
        price_tolerance_ratio: Decimal,
        policy_fingerprint: str,
        timestamp: datetime,
    ) -> _ConfirmationOutcome:
        if not decision.should_alert:
            if allow_state_change:
                state = self._session.scalar(
                    select(OfferConfirmationState)
                    .where(OfferConfirmationState.offer_key == offer_key)
                    .with_for_update()
                )
                if state is not None:
                    previous = (
                        self._session.get(DealDetection, state.candidate_detection_id)
                        if state.candidate_detection_id is not None
                        else None
                    )
                    if previous is not None:
                        previous.confirmation_status = "expired"
                    self._session.delete(state)
            return _ConfirmationOutcome(status="not_applicable")
        if not allow_state_change:
            return _ConfirmationOutcome(status="not_applicable")
        if not required:
            return _ConfirmationOutcome(
                status="not_required",
                count=1,
            )
        price = observation.price
        if price is None or price <= 0:  # pragma: no cover - guarded by decision
            raise ValueError("an alert candidate must have a positive price")

        self._session.execute(
            insert(OfferConfirmationState)
            .values(
                offer_key=offer_key,
                tracked_product_id=observation.tracked_product_id,
                candidate_observation_id=observation.id,
                candidate_detection_id=None,
                candidate_classification=decision.classification.value,
                candidate_price=price,
                confirmation_count=1,
                first_seen_at=observation.observed_at,
                last_seen_at=observation.observed_at,
                expires_at=observation.observed_at + max_age,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=[OfferConfirmationState.offer_key])
        )
        state = self._session.scalar(
            select(OfferConfirmationState)
            .where(OfferConfirmationState.offer_key == offer_key)
            .with_for_update()
        )
        if state is None:  # pragma: no cover - insert/select share one transaction
            raise RuntimeError("confirmation state could not be acquired")
        previous_detection = (
            self._session.get(DealDetection, state.candidate_detection_id)
            if state.candidate_detection_id is not None
            else None
        )
        if (
            previous_detection is not None
            and previous_detection.policy_fingerprint != policy_fingerprint
        ):
            previous_observation_id = state.candidate_observation_id
            previous_detection.confirmation_status = "replaced"
            state.tracked_product_id = observation.tracked_product_id
            state.candidate_observation_id = observation.id
            state.candidate_detection_id = None
            state.candidate_classification = decision.classification.value
            state.candidate_price = price
            state.confirmation_count = 1
            state.first_seen_at = observation.observed_at
            state.last_seen_at = observation.observed_at
            state.expires_at = observation.observed_at + max_age
            state.updated_at = timestamp
            return _ConfirmationOutcome(
                status="awaiting",
                count=1,
                reference_observation_id=previous_observation_id,
                state=state,
                state_tracks_current=True,
                previous_detection=previous_detection,
                previous_status="replaced",
            )
        if state.candidate_observation_id == observation.id:
            return _ConfirmationOutcome(
                status="awaiting",
                count=1,
                state=state,
                state_tracks_current=True,
            )

        previous_observation = self._session.get(
            PriceObservationRecord,
            state.candidate_observation_id,
        )
        if previous_observation is None:  # pragma: no cover - protected by FK
            raise RuntimeError("confirmation observation no longer exists")
        reference_observation_id = previous_observation.id
        elapsed = observation.observed_at - state.last_seen_at
        if (
            observation.run_id == previous_observation.run_id
            or elapsed <= timedelta(0)
            or elapsed < minimum_interval
        ):
            return _ConfirmationOutcome(
                status="awaiting",
                count=state.confirmation_count,
                reference_observation_id=reference_observation_id,
                state=state,
                previous_detection=previous_detection,
            )

        expired = observation.observed_at > state.expires_at
        relative_change = abs(price - state.candidate_price) / state.candidate_price
        if expired or relative_change > price_tolerance_ratio:
            previous_status = "expired" if expired else "replaced"
            state.candidate_observation_id = observation.id
            state.candidate_detection_id = None
            state.candidate_classification = decision.classification.value
            state.candidate_price = price
            state.confirmation_count = 1
            state.first_seen_at = observation.observed_at
            state.last_seen_at = observation.observed_at
            state.expires_at = observation.observed_at + max_age
            state.updated_at = timestamp
            return _ConfirmationOutcome(
                status="awaiting",
                count=1,
                reference_observation_id=reference_observation_id,
                state=state,
                state_tracks_current=True,
                previous_detection=previous_detection,
                previous_status=previous_status,
            )

        confirmation_count = state.confirmation_count + 1
        state.candidate_observation_id = observation.id
        state.candidate_detection_id = None
        state.candidate_classification = decision.classification.value
        state.candidate_price = price
        state.confirmation_count = confirmation_count
        state.last_seen_at = observation.observed_at
        state.expires_at = observation.observed_at + max_age
        state.updated_at = timestamp
        return _ConfirmationOutcome(
            status="confirmed",
            count=confirmation_count,
            reference_observation_id=reference_observation_id,
            state=state,
            state_tracks_current=True,
            previous_detection=previous_detection,
            previous_status="confirmed",
        )

    def _reserve_notification(
        self,
        *,
        observation: PriceObservationRecord,
        decision: DetectionDecision,
        offer_key: str,
        channel: str,
        cooldown: timedelta,
        significant_improvement_ratio: Decimal,
        timestamp: datetime,
    ) -> bool:
        self._session.execute(
            insert(OfferAlertState)
            .values(
                offer_key=offer_key,
                channel=channel,
                tracked_product_id=observation.tracked_product_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    OfferAlertState.offer_key,
                    OfferAlertState.channel,
                ]
            )
        )
        state = self._session.scalar(
            select(OfferAlertState)
            .where(
                OfferAlertState.offer_key == offer_key,
                OfferAlertState.channel == channel,
            )
            .with_for_update()
        )
        if state is None:  # pragma: no cover - insert/select share one transaction
            raise RuntimeError("alert state could not be acquired")

        cooldown_expired = (
            state.last_reserved_at is None or state.last_reserved_at <= timestamp - cooldown
        )
        severity_increased = _CLASSIFICATION_RANK[
            decision.classification.value
        ] > _CLASSIFICATION_RANK.get(state.last_classification or "none", 0)
        price_improved = (
            observation.price is not None
            and state.last_price is not None
            and observation.price
            <= state.last_price * (Decimal("1") - significant_improvement_ratio)
        )
        active_deliveries = self._session.execute(
            select(DealDetection, NotificationDelivery)
            .join(
                NotificationDelivery,
                NotificationDelivery.detection_id == DealDetection.id,
            )
            .where(
                DealDetection.offer_key == offer_key,
                NotificationDelivery.channel == channel,
                NotificationDelivery.status.in_(("pending", "retrying")),
            )
            .with_for_update(of=NotificationDelivery)
        ).all()
        has_leased_delivery = any(
            delivery.lease_token is not None
            and delivery.lease_expires_at is not None
            and delivery.lease_expires_at > timestamp
            for _detection, delivery in active_deliveries
        )
        improved_candidate = severity_increased or price_improved
        should_notify = False
        if active_deliveries:
            should_notify = improved_candidate and not has_leased_delivery
            if should_notify:
                for previous_detection, delivery in active_deliveries:
                    previous_detection.notification_status = "superseded"
                    delivery.status = "superseded"
                    delivery.lease_token = None
                    delivery.lease_expires_at = None
                    delivery.updated_at = timestamp
        else:
            should_notify = cooldown_expired or improved_candidate
        if should_notify:
            state.last_classification = decision.classification.value
            state.last_price = observation.price
            state.last_reserved_at = timestamp
            state.updated_at = timestamp
        return should_notify

    def save_processing_error(
        self,
        *,
        observation: PriceObservationRecord,
        detector_version: str,
        policy_fingerprint: str = _LEGACY_POLICY_FINGERPRINT,
        config_revision_id: int | None = None,
        error_type: str,
        detected_at: datetime | None = None,
    ) -> DetectionSaveResult:
        """Dead-letter one malformed observation without persisting error details."""

        normalized_version = detector_version.strip()
        if not normalized_version:
            raise ValueError("detector_version must not be empty")
        normalized_fingerprint = _normalized_policy_fingerprint(policy_fingerprint)
        if config_revision_id is not None and config_revision_id <= 0:
            raise ValueError("config_revision_id must be positive")
        existing = self._session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == observation.id,
                DealDetection.detector_version == normalized_version,
                DealDetection.policy_fingerprint == normalized_fingerprint,
            )
        )
        if existing is not None:
            return DetectionSaveResult(
                detection=existing,
                inserted=False,
                notification_reserved=False,
            )
        timestamp = _timestamp(self._session, detected_at)
        safe_error_type = (
            "".join(
                character
                for character in error_type.strip()
                if character.isalnum() or character in {"_", "."}
            )[:100]
            or "unknown"
        )
        error_key = hashlib.sha256(f"processing-error:{observation.id}".encode()).hexdigest()
        detection = DealDetection(
            observation_id=observation.id,
            detector_version=normalized_version,
            policy_fingerprint=normalized_fingerprint,
            config_revision_id=config_revision_id,
            tracked_product_id=observation.tracked_product_id,
            offer_key=error_key,
            classification=DealClassification.NONE.value,
            eligible=False,
            score=0,
            confidence_score=0,
            confidence_level="none",
            current_price=None,
            reference_price=None,
            reasons=[],
            rejection_reasons=["processing_error"],
            metrics={"processing_error_type": safe_error_type},
            notification_status="not_applicable",
            confirmation_status="not_applicable",
            confirmation_count=0,
            detected_at=timestamp,
        )
        self._session.add(detection)
        self._session.flush()
        return DetectionSaveResult(
            detection=detection,
            inserted=True,
            notification_reserved=False,
        )

    def recent(self, *, limit: int = 50, alerts_only: bool = False) -> list[DealDetection]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        statement = select(DealDetection)
        if alerts_only:
            statement = statement.where(
                DealDetection.classification != DealClassification.NONE.value
            )
        statement = statement.order_by(
            DealDetection.detected_at.desc(),
            DealDetection.id.desc(),
        ).limit(limit)
        return list(self._session.scalars(statement))


__all__ = [
    "DetectionRepository",
    "DetectionSaveResult",
]
