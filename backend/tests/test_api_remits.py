import uuid

import pytest

from app.models.enums import ClaimStatus
from tests.conftest import make_claim, make_remit, make_remit_code

IK = {"Idempotency-Key": str(uuid.uuid4())}

VALID_REMIT_BODY = {
    "raw_response": '{"payer": "Aetna", "claim_id": "abc123"}',
    "total_billed": 200.00,
    "total_allowed": 150.00,
    "total_paid": 130.00,
    "codes": [
        {"code": "CO-45", "amount": 50.00},
        {"code": "PR-1", "amount": 20.00},
    ],
}


# ---------------------------------------------------------------------------
# POST /claims/{id}/remit
# ---------------------------------------------------------------------------

def test_create_remit_returns_201(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    remit = make_remit(claim_id=claim.id, codes=[make_remit_code()])
    db.scalar.side_effect = [claim, None, remit]

    response = client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)
    assert response.status_code == 201


def test_create_remit_returns_remit_fields(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    remit = make_remit(claim_id=claim.id, codes=[make_remit_code()])
    db.scalar.side_effect = [claim, None, remit]

    response = client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)
    data = response.json()
    assert data["total_billed"] == 200.0
    assert data["total_allowed"] == 150.0
    assert data["total_paid"] == 130.0
    assert "codes" in data


def test_create_remit_claim_not_found_returns_404(client, db):
    db.scalar.return_value = None
    response = client.post(f"/claims/{uuid.uuid4()}/remit", json=VALID_REMIT_BODY, headers=IK)
    assert response.status_code == 404


def test_create_remit_claim_not_adjudicated_returns_422(client, db):
    claim = make_claim(status=ClaimStatus.SUBMITTED)
    db.scalar.return_value = claim
    response = client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)
    assert response.status_code == 422
    assert "ADJUDICATED" in response.json()["detail"]


def test_create_remit_wrong_status_message_includes_current_status(client, db):
    claim = make_claim(status=ClaimStatus.VALIDATED)
    db.scalar.return_value = claim
    response = client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)
    assert "VALIDATED" in response.json()["detail"]


def test_create_remit_duplicate_returns_409(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    existing_remit = make_remit(claim_id=claim.id)
    db.scalar.side_effect = [claim, existing_remit]

    response = client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)
    assert response.status_code == 409


def test_create_remit_unknown_code_accepted(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    remit = make_remit(claim_id=claim.id)
    db.scalar.side_effect = [claim, None, remit]

    body = {**VALID_REMIT_BODY, "codes": [{"code": "XX-999", "amount": 10.00}]}
    response = client.post(f"/claims/{claim.id}/remit", json=body, headers=IK)
    assert response.status_code == 201


def test_create_remit_updates_claim_financials(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    remit = make_remit(claim_id=claim.id)
    db.scalar.side_effect = [claim, None, remit]

    client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)

    assert claim.allowed_amount == 150.00
    assert claim.paid_amount == 130.00


def test_create_remit_writes_one_remit_code_per_input(client, db):
    claim = make_claim(status=ClaimStatus.ADJUDICATED)
    remit = make_remit(claim_id=claim.id)
    db.scalar.side_effect = [claim, None, remit]

    client.post(f"/claims/{claim.id}/remit", json=VALID_REMIT_BODY, headers=IK)

    # Two codes in VALID_REMIT_BODY → two db.add calls for RemitCode + one for Remit
    assert db.add.call_count == 3


def test_create_remit_missing_codes_returns_422(client, db):
    body = {k: v for k, v in VALID_REMIT_BODY.items() if k != "codes"}
    response = client.post(f"/claims/{uuid.uuid4()}/remit", json=body, headers=IK)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /claims/{id}/remit
# ---------------------------------------------------------------------------

def test_get_remit_returns_200(client, db):
    remit = make_remit(codes=[make_remit_code()])
    db.scalar.return_value = remit
    response = client.get(f"/claims/{uuid.uuid4()}/remit")
    assert response.status_code == 200


def test_get_remit_not_found_returns_404(client, db):
    db.scalar.return_value = None
    response = client.get(f"/claims/{uuid.uuid4()}/remit")
    assert response.status_code == 404


def test_get_remit_returns_codes(client, db):
    code = make_remit_code(code="CO-45")
    remit = make_remit(codes=[code])
    db.scalar.return_value = remit
    response = client.get(f"/claims/{uuid.uuid4()}/remit")
    data = response.json()
    assert len(data["codes"]) == 1
    assert data["codes"][0]["code"] == "CO-45"


def test_get_remit_code_includes_action_required(client, db):
    code = make_remit_code(action_required="Bill patient")
    remit = make_remit(codes=[code])
    db.scalar.return_value = remit
    response = client.get(f"/claims/{uuid.uuid4()}/remit")
    assert response.json()["codes"][0]["action_required"] == "Bill patient"
