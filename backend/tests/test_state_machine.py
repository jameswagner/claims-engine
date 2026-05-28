import types
import uuid
from unittest.mock import Mock, patch

import pytest

from app.claims.exceptions import (
    DuplicateTransitionError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.claims.state_machine import ALLOWED_TRANSITIONS, transition
from app.models.enums import ClaimStatus
from app.rules.validator import ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_claim(**overrides) -> types.SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        patient_name="Jane Doe",
        provider_name="Dr. Smith",
        cpt_code="90837",
        diagnosis_code="F32.1",
        insurance_payer="Aetna",
        status=ClaimStatus.CREATED,
    )
    return types.SimpleNamespace(**{**defaults, **overrides})


def make_db(existing_event=None) -> Mock:
    """Mock Session. scalar() returns existing_event for the idempotency check."""
    db = Mock()
    db.scalar.return_value = existing_event
    return db


PASSING_RESULT = ValidationResult(is_valid=True, errors=[])
FAILING_RESULT = ValidationResult(is_valid=False, errors=["CPT code '99999' is not covered"])


# ---------------------------------------------------------------------------
# ALLOWED_TRANSITIONS table
# ---------------------------------------------------------------------------

def test_all_statuses_present_in_transition_table():
    for status in ClaimStatus:
        assert status in ALLOWED_TRANSITIONS


def test_paid_is_terminal():
    assert ALLOWED_TRANSITIONS[ClaimStatus.PAID] == frozenset()


def test_denied_allows_resubmission():
    assert ClaimStatus.SUBMITTED in ALLOWED_TRANSITIONS[ClaimStatus.DENIED]


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

@patch("app.claims.state_machine.validate_claim", return_value=PASSING_RESULT)
def test_created_to_validated(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    event = transition(claim, ClaimStatus.VALIDATED, make_db())
    assert event.from_status == ClaimStatus.CREATED
    assert event.to_status == ClaimStatus.VALIDATED
    assert claim.status == ClaimStatus.VALIDATED


def test_validated_to_submitted():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    event = transition(claim, ClaimStatus.SUBMITTED, make_db())
    assert event.to_status == ClaimStatus.SUBMITTED
    assert claim.status == ClaimStatus.SUBMITTED


def test_submitted_to_adjudicated():
    claim = make_claim(status=ClaimStatus.SUBMITTED)
    event = transition(claim, ClaimStatus.ADJUDICATED, make_db())
    assert event.to_status == ClaimStatus.ADJUDICATED


def test_adjudicated_to_paid():
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    event = transition(claim, ClaimStatus.PAID, make_db())
    assert event.to_status == ClaimStatus.PAID


def test_adjudicated_to_denied():
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    event = transition(claim, ClaimStatus.DENIED, make_db(), reason="Plan limit exceeded")
    assert event.to_status == ClaimStatus.DENIED
    assert event.reason == "Plan limit exceeded"


def test_denied_to_submitted_resubmission():
    claim = make_claim(status=ClaimStatus.DENIED)
    event = transition(claim, ClaimStatus.SUBMITTED, make_db(), reason="Corrected codes")
    assert event.to_status == ClaimStatus.SUBMITTED
    assert event.reason == "Corrected codes"
    assert claim.status == ClaimStatus.SUBMITTED


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("from_s, to_s", [
    (ClaimStatus.CREATED,     ClaimStatus.SUBMITTED),     # skip VALIDATED
    (ClaimStatus.CREATED,     ClaimStatus.PAID),           # jump to end
    (ClaimStatus.VALIDATED,   ClaimStatus.CREATED),        # backwards
    (ClaimStatus.VALIDATED,   ClaimStatus.ADJUDICATED),    # skip SUBMITTED
    (ClaimStatus.SUBMITTED,   ClaimStatus.VALIDATED),      # backwards
    (ClaimStatus.SUBMITTED,   ClaimStatus.PAID),           # skip ADJUDICATED
    (ClaimStatus.PAID,        ClaimStatus.DENIED),         # terminal → invalid
    (ClaimStatus.PAID,        ClaimStatus.CREATED),        # terminal → invalid
    (ClaimStatus.DENIED,      ClaimStatus.PAID),           # denied can only resubmit
])
def test_invalid_transition_raises(from_s, to_s):
    claim = make_claim(status=from_s)
    with pytest.raises(InvalidTransitionError):
        transition(claim, to_s, make_db())


def test_invalid_transition_error_message_includes_statuses():
    claim = make_claim(status=ClaimStatus.PAID)
    with pytest.raises(InvalidTransitionError, match="PAID"):
        transition(claim, ClaimStatus.CREATED, make_db())


def test_invalid_transition_does_not_mutate_claim():
    claim = make_claim(status=ClaimStatus.PAID)
    with pytest.raises(InvalidTransitionError):
        transition(claim, ClaimStatus.CREATED, make_db())
    assert claim.status == ClaimStatus.PAID


# ---------------------------------------------------------------------------
# Idempotency — client-supplied key
# ---------------------------------------------------------------------------

def test_duplicate_idempotency_key_raises():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    existing_event = Mock()
    db = make_db(existing_event=existing_event)
    with pytest.raises(DuplicateTransitionError):
        transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key="key-abc")


def test_duplicate_transition_error_message_includes_status():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db = make_db(existing_event=Mock())
    with pytest.raises(DuplicateTransitionError, match="SUBMITTED"):
        transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key="key-abc")


def test_no_duplicate_when_no_existing_event():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db = make_db(existing_event=None)
    event = transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key="key-abc")
    assert event is not None


def test_idempotency_key_written_to_event():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    key = str(uuid.uuid4())
    event = transition(claim, ClaimStatus.SUBMITTED, make_db(), idempotency_key=key)
    assert event.idempotency_key == key


def test_no_idempotency_key_skips_duplicate_check():
    """Without a key, the DB is never queried for duplicates."""
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db = make_db()
    transition(claim, ClaimStatus.SUBMITTED, db)
    db.scalar.assert_not_called()


def test_no_idempotency_key_event_has_none():
    claim = make_claim(status=ClaimStatus.VALIDATED)
    event = transition(claim, ClaimStatus.SUBMITTED, make_db())
    assert event.idempotency_key is None


# ---------------------------------------------------------------------------
# Validation gate (CREATED → VALIDATED only)
# ---------------------------------------------------------------------------

@patch("app.claims.state_machine.validate_claim", return_value=FAILING_RESULT)
def test_failed_validation_raises_validation_failed_error(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    with pytest.raises(ValidationFailedError) as exc_info:
        transition(claim, ClaimStatus.VALIDATED, make_db())
    assert "99999" in str(exc_info.value)


@patch("app.claims.state_machine.validate_claim", return_value=FAILING_RESULT)
def test_validation_failed_error_carries_errors_list(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    with pytest.raises(ValidationFailedError) as exc_info:
        transition(claim, ClaimStatus.VALIDATED, make_db())
    assert exc_info.value.errors == FAILING_RESULT.errors


@patch("app.claims.state_machine.validate_claim", return_value=PASSING_RESULT)
def test_validator_called_only_for_created_to_validated(mock_validate):
    claim = make_claim(status=ClaimStatus.VALIDATED)
    transition(claim, ClaimStatus.SUBMITTED, make_db())
    mock_validate.assert_not_called()


@patch("app.claims.state_machine.validate_claim", return_value=PASSING_RESULT)
def test_validator_receives_claim_fields(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    transition(claim, ClaimStatus.VALIDATED, make_db())
    call_args = mock_validate.call_args[0][0]
    assert call_args.patient_name == claim.patient_name
    assert call_args.cpt_code == claim.cpt_code
    assert call_args.insurance_payer == claim.insurance_payer


@patch("app.claims.state_machine.validate_claim", return_value=FAILING_RESULT)
def test_failed_validation_does_not_mutate_claim_status(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    with pytest.raises(ValidationFailedError):
        transition(claim, ClaimStatus.VALIDATED, make_db())
    assert claim.status == ClaimStatus.CREATED


# ---------------------------------------------------------------------------
# DB interactions
# ---------------------------------------------------------------------------

@patch("app.claims.state_machine.validate_claim", return_value=PASSING_RESULT)
def test_db_add_called_with_event(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    db = make_db()
    event = transition(claim, ClaimStatus.VALIDATED, db)
    db.add.assert_called_once_with(event)


@patch("app.claims.state_machine.validate_claim", return_value=PASSING_RESULT)
def test_db_flush_called(mock_validate):
    claim = make_claim(status=ClaimStatus.CREATED)
    db = make_db()
    transition(claim, ClaimStatus.VALIDATED, db)
    db.flush.assert_called_once()


def test_reason_is_none_by_default():
    claim = make_claim(status=ClaimStatus.SUBMITTED)
    event = transition(claim, ClaimStatus.ADJUDICATED, make_db())
    assert event.reason is None


def test_reason_passed_through_to_event():
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    event = transition(claim, ClaimStatus.DENIED, make_db(), reason="Exceeded benefit limit")
    assert event.reason == "Exceeded benefit limit"
