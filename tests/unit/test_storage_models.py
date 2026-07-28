from sqlalchemy import inspect
from sqlalchemy.orm import configure_mappers

from bot_ofertas.storage.models import DealDetection, OfferConfirmationState
from bot_ofertas.storage.models import PriceObservationRecord as ObservationRecord


def test_detection_observation_relationships_have_explicit_foreign_keys() -> None:
    configure_mappers()

    detection_relationships = inspect(DealDetection).relationships
    observation_relationships = inspect(ObservationRecord).relationships

    assert detection_relationships["observation"]._calculated_foreign_keys == {
        DealDetection.__table__.c.observation_id
    }
    assert detection_relationships["confirmation_observation"]._calculated_foreign_keys == {
        DealDetection.__table__.c.confirmation_observation_id
    }
    assert observation_relationships["detections"]._calculated_foreign_keys == {
        DealDetection.__table__.c.observation_id
    }


def test_phase3_model_defaults_and_confirmation_constraints_match_the_migration() -> None:
    detector_default = DealDetection.__table__.c.detector_version.server_default
    constraint_names = {
        constraint.name for constraint in OfferConfirmationState.__table__.constraints
    }

    assert detector_default is not None
    assert str(detector_default.arg) == "'phase3-v2'"
    assert {
        "ck_offer_confirmation_states_classification",
        "ck_offer_confirmation_states_expiry_order",
    } <= constraint_names
