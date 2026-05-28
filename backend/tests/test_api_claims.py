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

IDEMPOTENCY_HEADERS = {"Idempotency-Key": str(uuid.uuid4())}


# ---------------------------------------------------------------------------
# POST /claims
# ---------------------------------------------------------------------------

def _stamp(obj):
    """Mock db.refresh — sets fields that server_default/flush would normally populate."""
    import uuid as _uuid
    from datetime import datetime, timezone
    obj.id = obj.id or _uuid.uuid4()
    obj.created_at = datetime.now(timezone.utc)
    obj.updated_at = datetime.now(timezone.utc)


def test_create_claim_returns_201(client, db):
    db.refresh.side_effect = _stamp
    response = client.post("/claims", json=VALID_CLAIM_BODY)
    assert response.status_code == 201
    data = response.json()
    assert data["patient_name"] == "Jane Doe"
    assert data["status"] == "CREATED"
    assert data["billed_amount"] == 200.0


def test_create_claim_missing_billed_amount_returns_422(client, db):
    body = {k: v for k, v in VALID_CLAIM_BODY.items() if k != "billed_amount"}
    response = client.post("/claims", json=body)
    assert response.status_code == 422


def test_create_claim_commits_to_db(client, db):
    db.refresh.side_effect = _stamp
    client.post("/claims", json=VALID_CLAIM_BODY)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# GET /claims
# ---------------------------------------------------------------------------

def test_list_claims_returns_200(client, db):
    claims = [make_claim(), make_claim(status=ClaimStatus.PAID)]
    db.scalars.return_value.all.return_value = claims
    response = client.get("/claims")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_claims_empty(client, db):
    db.scalars.return_value.all.return_value = []
    response = client.get("/claims")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /claims/{id}
# ---------------------------------------------------------------------------

def test_get_claim_returns_200(client, db):
    claim = make_claim()
    db.scalar.return_value = claim
    response = client.get(f"/claims/{claim.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(claim.id)


def test_get_claim_not_found_returns_404(client, db):
    db.scalar.return_value = None
    response = client.get(f"/claims/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_claim_includes_events(client, db):
    claim = make_claim(status=ClaimStatus.VALIDATED, events=[])
    db.scalar.return_value = claim
    response = client.get(f"/claims/{claim.id}")
    assert "events" in response.json()


# ---------------------------------------------------------------------------
# POST /claims/{id}/advance
# ---------------------------------------------------------------------------

def test_advance_requires_idempotency_key(client, db):
    response = client.post(f"/claims/{uuid.uuid4()}/advance", json={})
    assert response.status_code == 422


def test_advance_claim_not_found_returns_404(client, db):
    db.scalar.return_value = None
    response = client.post(
        f"/claims/{uuid.uuid4()}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 404


def test_advance_terminal_claim_returns_422(client, db):
    claim = make_claim(status=ClaimStatus.PAID)
    db.scalar.return_value = claim
    response = client.post(
        f"/claims/{claim.id}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 422
    assert "terminal" in response.json()["detail"].lower()


@patch("app.api.claims.transition")
def test_advance_success_returns_200(mock_transition, client, db):
    claim = make_claim(status=ClaimStatus.VALIDATED)

    def do_transition(c, to_status, db, **kwargs):
        c.status = to_status

    mock_transition.side_effect = do_transition
    db.scalar.return_value = claim

    response = client.post(
        f"/claims/{claim.id}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUBMITTED"


@patch("app.api.claims.transition")
def test_advance_duplicate_key_returns_200_replay(mock_transition, client, db):
    from app.claims.exceptions import DuplicateTransitionError

    claim = make_claim(status=ClaimStatus.VALIDATED)
    db.scalar.return_value = claim
    mock_transition.side_effect = DuplicateTransitionError("already done")

    response = client.post(
        f"/claims/{claim.id}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "VALIDATED"


@patch("app.api.claims.transition")
def test_advance_validation_failed_returns_422(mock_transition, client, db):
    from app.claims.exceptions import ValidationFailedError

    claim = make_claim(status=ClaimStatus.CREATED)
    db.scalar.return_value = claim
    mock_transition.side_effect = ValidationFailedError(["CPT code not covered"])

    response = client.post(
        f"/claims/{claim.id}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 422
    assert "CPT code not covered" in response.json()["detail"]["errors"]


@patch("app.api.claims.transition")
def test_advance_to_adjudicated_sets_financial_fields(mock_transition, client, db):
    claim = make_claim(status=ClaimStatus.SUBMITTED)

    def do_transition(c, to_status, db, **kwargs):
        c.status = to_status

    mock_transition.side_effect = do_transition
    db.scalar.return_value = claim

    response = client.post(
        f"/claims/{claim.id}/advance",
        json={"allowed_amount": 150.00, "patient_responsibility": 20.00},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 200
    assert claim.allowed_amount == Decimal("150.00")
    assert claim.patient_responsibility == Decimal("20.00")


@patch("app.api.claims.transition")
def test_advance_to_paid_computes_paid_amount(mock_transition, client, db):
    claim = make_claim(
        status=ClaimStatus.ADJUDICATED,
        allowed_amount=Decimal("150.00"),
        patient_responsibility=Decimal("20.00"),
    )

    def do_transition(c, to_status, db, **kwargs):
        c.status = to_status

    mock_transition.side_effect = do_transition
    db.scalar.return_value = claim

    response = client.post(
        f"/claims/{claim.id}/advance",
        json={},
        headers=IDEMPOTENCY_HEADERS,
    )
    assert response.status_code == 200
    assert claim.paid_amount == Decimal("130.00")
