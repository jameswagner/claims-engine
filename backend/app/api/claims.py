import asyncio
import uuid
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.claims.exceptions import (
    DuplicateTransitionError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.claims.state_machine import transition
from app.db.session import get_db
from app.models.claim import Claim
from app.models.enums import ClaimStatus
from app.schemas.claim import (
    AdjudicateRequest,
    ClaimCreate,
    ClaimDetail,
    ClaimRead,
    DenyRequest,
    PayRequest,
    ResubmitRequest,
    SubmitRequest,
)

router = APIRouter(prefix="/claims", tags=["claims"])
log = structlog.get_logger()


def _fetch(claim_id: uuid.UUID, db: Session) -> Claim:
    claim = db.scalar(
        select(Claim).where(Claim.id == claim_id).options(selectinload(Claim.events))
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _transition(claim: Claim, to_status: ClaimStatus, db: Session, key: str, reason: str | None = None) -> bool:
    """Run transition and map exceptions to HTTP. Returns True if this was an idempotent replay."""
    try:
        transition(claim, to_status, db, reason=reason, idempotency_key=key)
        return False
    except DuplicateTransitionError:
        return True
    except ValidationFailedError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=ClaimRead, status_code=201)
def create_claim(body: ClaimCreate, db: Session = Depends(get_db)):
    claim = Claim(**body.model_dump(), status=ClaimStatus.CREATED)
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("", response_model=list[ClaimRead])
def list_claims(db: Session = Depends(get_db)):
    return db.scalars(select(Claim).order_by(Claim.created_at.desc())).all()


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: uuid.UUID, db: Session = Depends(get_db)):
    return _fetch(claim_id, db)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

@router.post("/{claim_id}/validate", response_model=ClaimDetail)
def validate_claim_route(
    claim_id: uuid.UUID,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    _transition(claim, ClaimStatus.VALIDATED, db, idempotency_key)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/submit", response_model=ClaimDetail)
async def submit_claim(
    claim_id: uuid.UUID,
    body: SubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    await asyncio.sleep(0.2)  # simulate clearinghouse round-trip
    _transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key, reason=body.clearinghouse_ref)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/adjudicate", response_model=ClaimDetail)
def adjudicate_claim(
    claim_id: uuid.UUID,
    body: AdjudicateRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    is_replay = _transition(claim, ClaimStatus.ADJUDICATED, db, idempotency_key)
    if not is_replay:
        claim.allowed_amount = body.allowed_amount
        claim.patient_responsibility = body.patient_responsibility
        if body.adjustment_reason:
            claim.adjustment_reason = body.adjustment_reason
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/pay", response_model=ClaimDetail)
def pay_claim(
    claim_id: uuid.UUID,
    body: PayRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    is_replay = _transition(claim, ClaimStatus.PAID, db, idempotency_key)
    if not is_replay:
        claim.paid_amount = body.paid_amount
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/deny", response_model=ClaimDetail)
def deny_claim(
    claim_id: uuid.UUID,
    body: DenyRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    _transition(claim, ClaimStatus.DENIED, db, idempotency_key, reason=body.denial_reason)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/resubmit", response_model=ClaimDetail)
async def resubmit_claim(
    claim_id: uuid.UUID,
    body: ResubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db)
    await asyncio.sleep(0.2)  # simulate clearinghouse round-trip
    _transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key, reason=body.correction_notes)
    db.commit()
    db.refresh(claim)
    return claim
