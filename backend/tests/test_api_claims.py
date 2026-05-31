import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.enums import ClaimStatus
from tests.conftest import make_claim

VALID_CLAIM_BODY = {
    "patient_name": "Jane Doe",
    "provider_name": "Dr. Smith",
    "cpt_code": "90837",
    "diagnosis_code": "F32.1",
    "insurance_payer": "Aetna",
    "billed_amount": 200.00,
}

IK = {"Idempotency-Key": str(uuid.uuid4())}


def _stamp(obj):
    """Simulate db.refresh populating server_default fields."""
    import uuid as _uuid
    from datetime import datetime, timezone
    obj.id = obj.id or _uuid.uuid4()
    obj.created_at = datetime.now(timezone.utc)
    obj.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# POST /claims
# ---------------------------------------------------------------------------

def test_create_claim_returns_201(client, db):
    db.refresh.side_effect = _stamp
    response = client.post("/claims", json=VALID_CLAIM_BODY)
    assert response.status_code == 201
    assert response.json()["status"] == "CREATED"
    assert response.json()["billed_amount"] == 200.0


def test_create_claim_missing_billed_amount_returns_422(client, db):
    body = {k: v for k, v in VALID_CLAIM_BODY.items() if k != "billed_amount"}
    assert client.post("/claims", json=body).status_code == 422


def test_create_claim_commits_to_db(client, db):
    db.refresh.side_effect = _stamp
    client.post("/claims", json=VALID_CLAIM_BODY)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# GET /claims
# ---------------------------------------------------------------------------

def test_list_claims_returns_all(client, db):
    db.scalars.return_value.all.return_value = [make_claim(), make_claim()]
    assert len(client.get("/claims").json()) == 2


def test_list_claims_empty(client, db):
    db.scalars.return_value.all.return_value = []
    assert client.get("/claims").json() == []


# ---------------------------------------------------------------------------
# GET /claims/{id}
# ---------------------------------------------------------------------------

def test_get_claim_success(client, db):
    claim = make_claim()
    db.scalar.return_value = claim
    assert client.get(f"/claims/{claim.id}").json()["id"] == str(claim.id)


def test_get_claim_not_found(client, db):
    db.scalar.return_value = None
    assert client.get(f"/claims/{uuid.uuid4()}").status_code == 404


# ---------------------------------------------------------------------------
# POST /claims/{id}/validate
# ---------------------------------------------------------------------------

def test_validate_requires_idempotency_key(client, db):
    assert client.post(f"/claims/{uuid.uuid4()}/validate").status_code == 422


@patch("app.api.claims.transition")
def test_validate_success(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.CREATED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    response = client.post(f"/claims/{claim.id}/validate", headers=IK)
    assert response.status_code == 200
    assert response.json()["status"] == "VALIDATED"


def test_validate_claim_not_found(client, db):
    db.scalar.return_value = None
    assert client.post(f"/claims/{uuid.uuid4()}/validate", headers=IK).status_code == 404


@patch("app.api.claims.transition")
def test_validate_rules_failure_returns_422(mock_t, client, db):
    from app.claims.exceptions import ValidationFailedError
    claim = make_claim(status=ClaimStatus.CREATED)
    db.scalar.return_value = claim
    mock_t.side_effect = ValidationFailedError(["CPT not covered"])
    response = client.post(f"/claims/{claim.id}/validate", headers=IK)
    assert response.status_code == 422
    assert "CPT not covered" in response.json()["detail"]["errors"]


# ---------------------------------------------------------------------------
# POST /claims/{id}/submit
# ---------------------------------------------------------------------------

@patch("app.tasks.submission.process_submission.delay")
@patch("app.api.claims.transition")
def test_submit_success(mock_t, mock_delay, client, db):
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    response = client.post(f"/claims/{claim.id}/submit", json={}, headers=IK)
    assert response.status_code == 202
    assert response.json()["status"] == "SUBMITTING"


@patch("app.tasks.submission.process_submission.delay")
@patch("app.api.claims.transition")
def test_submit_passes_clearinghouse_ref_as_reason(mock_t, mock_delay, client, db):
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db.scalar.return_value = claim
    calls = []
    mock_t.side_effect = lambda c, s, db, **kw: calls.append(kw.get("reason")) or setattr(c, "status", s)
    client.post(f"/claims/{claim.id}/submit", json={"clearinghouse_ref": "CH-12345"}, headers=IK)
    assert calls[0] == "CH-12345"


# ---------------------------------------------------------------------------
# POST /claims/{id}/adjudicate
# ---------------------------------------------------------------------------

@patch("app.api.claims.transition")
def test_adjudicate_success(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.SUBMITTED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    body = {"allowed_amount": 150.00, "patient_responsibility": 20.00}
    response = client.post(f"/claims/{claim.id}/adjudicate", json=body, headers=IK)
    assert response.status_code == 200
    assert response.json()["status"] == "ADJUDICATED"


@patch("app.api.claims.transition")
def test_adjudicate_sets_financial_fields(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.SUBMITTED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    body = {"allowed_amount": 150.00, "patient_responsibility": 20.00, "adjustment_reason": "CO-45"}
    client.post(f"/claims/{claim.id}/adjudicate", json=body, headers=IK)
    assert claim.allowed_amount == Decimal("150.00")
    assert claim.patient_responsibility == Decimal("20.00")
    assert claim.adjustment_reason == "CO-45"


def test_adjudicate_missing_allowed_amount_returns_422(client, db):
    body = {"patient_responsibility": 20.00}
    assert client.post(f"/claims/{uuid.uuid4()}/adjudicate", json=body, headers=IK).status_code == 422


# ---------------------------------------------------------------------------
# POST /claims/{id}/pay
# ---------------------------------------------------------------------------

@patch("app.api.claims.transition")
def test_pay_success(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED, allowed_amount=Decimal("150"))
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    response = client.post(f"/claims/{claim.id}/pay", json={"paid_amount": 130.00}, headers=IK)
    assert response.status_code == 200
    assert response.json()["status"] == "PAID"


@patch("app.api.claims.transition")
def test_pay_sets_paid_amount(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    client.post(f"/claims/{claim.id}/pay", json={"paid_amount": 130.00}, headers=IK)
    assert claim.paid_amount == Decimal("130.00")


def test_pay_missing_paid_amount_returns_422(client, db):
    assert client.post(f"/claims/{uuid.uuid4()}/pay", json={}, headers=IK).status_code == 422


# ---------------------------------------------------------------------------
# POST /claims/{id}/deny
# ---------------------------------------------------------------------------

@patch("app.api.claims.transition")
def test_deny_success(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    response = client.post(f"/claims/{claim.id}/deny", json={"denial_reason": "CO-97"}, headers=IK)
    assert response.status_code == 200
    assert response.json()["status"] == "DENIED"


@patch("app.api.claims.transition")
def test_deny_passes_reason_to_transition(mock_t, client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    db.scalar.return_value = claim
    calls = []
    mock_t.side_effect = lambda c, s, db, **kw: calls.append(kw.get("reason")) or setattr(c, "status", s)
    client.post(f"/claims/{claim.id}/deny", json={"denial_reason": "CO-97: bundled"}, headers=IK)
    assert calls[0] == "CO-97: bundled"


def test_deny_missing_reason_returns_422(client, db):
    assert client.post(f"/claims/{uuid.uuid4()}/deny", json={}, headers=IK).status_code == 422


# ---------------------------------------------------------------------------
# POST /claims/{id}/resubmit
# ---------------------------------------------------------------------------

@patch("app.tasks.submission.process_submission.delay")
@patch("app.api.claims.transition")
def test_resubmit_success(mock_t, mock_delay, client, db):
    claim = make_claim(status=ClaimStatus.DENIED)
    db.scalar.return_value = claim
    mock_t.side_effect = lambda c, s, db, **kw: setattr(c, "status", s)
    body = {"correction_notes": "Added modifier HO"}
    response = client.post(f"/claims/{claim.id}/resubmit", json=body, headers=IK)
    assert response.status_code == 202
    assert response.json()["status"] == "SUBMITTING"


@patch("app.tasks.submission.process_submission.delay")
@patch("app.api.claims.transition")
def test_resubmit_passes_correction_notes_as_reason(mock_t, mock_delay, client, db):
    claim = make_claim(status=ClaimStatus.DENIED)
    db.scalar.return_value = claim
    calls = []
    mock_t.side_effect = lambda c, s, db, **kw: calls.append(kw.get("reason")) or setattr(c, "status", s)
    client.post(f"/claims/{claim.id}/resubmit", json={"correction_notes": "Fixed modifier"}, headers=IK)
    assert calls[0] == "Fixed modifier"


def test_resubmit_missing_correction_notes_returns_422(client, db):
    assert client.post(f"/claims/{uuid.uuid4()}/resubmit", json={}, headers=IK).status_code == 422


# ---------------------------------------------------------------------------
# Idempotency replay (shared across endpoints)
# ---------------------------------------------------------------------------

@patch("app.api.claims.transition")
def test_duplicate_idempotency_key_returns_200_replay(mock_t, client, db):
    from app.claims.exceptions import DuplicateTransitionError
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db.scalar.return_value = claim
    mock_t.side_effect = DuplicateTransitionError("already done")
    response = client.post(f"/claims/{claim.id}/validate", headers=IK)
    assert response.status_code == 200
