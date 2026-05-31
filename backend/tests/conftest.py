import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.enums import ClaimStatus
from app.models.remit_code import RemitCodeCategory


def make_claim(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        patient_name="Jane Doe",
        provider_name="Dr. Smith",
        cpt_code="90837",
        diagnosis_code="F32.1",
        insurance_payer="Aetna",
        status=ClaimStatus.CREATED,
        billed_amount=Decimal("200.00"),
        allowed_amount=None,
        paid_amount=None,
        patient_responsibility=None,
        adjustment_reason=None,
        created_at=now,
        updated_at=now,
        events=[],
    )
    return types.SimpleNamespace(**{**defaults, **overrides})


def make_remit(claim_id=None, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        claim_id=claim_id or uuid.uuid4(),
        idempotency_key=str(uuid.uuid4()),
        raw_response='{"payer": "Aetna"}',
        processed_at=datetime.now(timezone.utc),
        total_billed=Decimal("200.00"),
        total_allowed=Decimal("150.00"),
        total_paid=Decimal("130.00"),
        codes=[],
    )
    return types.SimpleNamespace(**{**defaults, **overrides})


def make_remit_code(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        remit_id=uuid.uuid4(),
        code="CO-45",
        category=RemitCodeCategory.CONTRACTUAL_OBLIGATION,
        amount=Decimal("50.00"),
        description="Charge exceeds fee schedule/maximum allowable",
        action_required="Write off difference, bill patient responsibility",
    )
    return types.SimpleNamespace(**{**defaults, **overrides})


@pytest.fixture
def db():
    return Mock()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
