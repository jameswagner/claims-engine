import time
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


def _fetch(claim_id: uuid.UUID, db: Session, lock: bool = False) -> Claim:
    q = select(Claim).where(Claim.id == claim_id).options(selectinload(Claim.events))
    if lock:
        q = q.with_for_update()
    claim = db.scalar(q)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _transition(claim: Claim, to_status: ClaimStatus, db: Session, key: str, reason: str | None = None) -> bool:
    """Run transition and map exceptions to HTTP. Returns True if this was an idempotent replay."""
    try:
        transition(claim, to_status, db, reason=reason, idempotency_key=key)
        log.info("claim_transitioned", claim_id=str(claim.id), to_status=to_status.value)
        return False
    except DuplicateTransitionError:
        log.info("claim_transition_replay", claim_id=str(claim.id), to_status=to_status.value)
        return True
    except ValidationFailedError as e:
        log.warning("claim_validation_failed", claim_id=str(claim.id), errors=e.errors)
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    except InvalidTransitionError as e:
        log.warning("claim_invalid_transition", claim_id=str(claim.id), to_status=to_status.value, error=str(e))
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
    claim = _fetch(claim_id, db, lock=True)
    _transition(claim, ClaimStatus.VALIDATED, db, idempotency_key)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/submit", response_model=ClaimDetail)
def submit_claim(
    claim_id: uuid.UUID,
    body: SubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db, lock=True)
    time.sleep(0.2)  # simulate clearinghouse round-trip
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
    claim = _fetch(claim_id, db, lock=True)
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
    claim = _fetch(claim_id, db, lock=True)
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
    claim = _fetch(claim_id, db, lock=True)
    _transition(claim, ClaimStatus.DENIED, db, idempotency_key, reason=body.denial_reason)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{claim_id}/resubmit", response_model=ClaimDetail)
def resubmit_claim(
    claim_id: uuid.UUID,
    body: ResubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db, lock=True)
    time.sleep(0.2)  # simulate clearinghouse round-trip
    _transition(claim, ClaimStatus.SUBMITTED, db, idempotency_key, reason=body.correction_notes)
    db.commit()
    db.refresh(claim)
    return claim
