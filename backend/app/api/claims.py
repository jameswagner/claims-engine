import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.claims.exceptions import (
    DuplicateTransitionError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.claims.state_machine import ALLOWED_TRANSITIONS, transition
from app.db.session import get_db
from app.models.claim import Claim
from app.models.enums import ClaimStatus
from app.schemas.claim import AdvanceRequest, ClaimCreate, ClaimDetail, ClaimRead

router = APIRouter(prefix="/claims", tags=["claims"])


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
    claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim_id)
        .options(selectinload(Claim.events))
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.post("/{claim_id}/advance", response_model=ClaimDetail)
def advance_claim(
    claim_id: uuid.UUID,
    body: AdvanceRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim_id)
        .options(selectinload(Claim.events))
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    allowed = ALLOWED_TRANSITIONS.get(claim.status, frozenset())
    if not allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Claim is in a terminal state ({claim.status.value}) and cannot be advanced",
        )

    if ClaimStatus.PAID in allowed and ClaimStatus.DENIED in allowed:
        to_status = ClaimStatus.DENIED if body.reason else ClaimStatus.PAID
    else:
        (to_status,) = allowed

    try:
        transition(claim, to_status, db, reason=body.reason, idempotency_key=idempotency_key)

        if to_status == ClaimStatus.ADJUDICATED:
            if body.allowed_amount is not None:
                claim.allowed_amount = body.allowed_amount
            if body.patient_responsibility is not None:
                claim.patient_responsibility = body.patient_responsibility
            if body.adjustment_reason is not None:
                claim.adjustment_reason = body.adjustment_reason

        if to_status == ClaimStatus.PAID and claim.allowed_amount is not None:
            claim.paid_amount = claim.allowed_amount - (claim.patient_responsibility or Decimal("0"))

        db.commit()
        db.refresh(claim)
        return claim
    except DuplicateTransitionError:
        return claim
    except ValidationFailedError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))
