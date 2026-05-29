import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.seed_remit_codes import resolve_code
from app.db.session import get_db
from app.models.claim import Claim
from app.models.enums import ClaimStatus
from app.models.remit import Remit
from app.models.remit_code import RemitCode
from app.schemas.remit import RemitCreate, RemitRead

router = APIRouter(prefix="/claims", tags=["remits"])

log = structlog.get_logger()


@router.post("/{claim_id}/remit", response_model=RemitRead, status_code=201)
def create_remit(
    claim_id: uuid.UUID,
    body: RemitCreate,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = db.scalar(select(Claim).where(Claim.id == claim_id))
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != ClaimStatus.ADJUDICATED:
        raise HTTPException(
            status_code=422,
            detail=f"Claim must be ADJUDICATED to receive a remit (current: {claim.status.value})",
        )

    existing = db.scalar(select(Remit).where(Remit.claim_id == claim_id))
    if existing:
        if existing.idempotency_key == idempotency_key:
            return db.scalar(
                select(Remit).where(Remit.id == existing.id).options(selectinload(Remit.codes))
            )
        raise HTTPException(status_code=409, detail="Remit already exists for this claim")

    remit = Remit(
        claim_id=claim_id,
        idempotency_key=idempotency_key,
        raw_response=body.raw_response,
        total_billed=body.total_billed,
        total_allowed=body.total_allowed,
        total_paid=body.total_paid,
    )
    db.add(remit)
    db.flush()

    for code_input in body.codes:
        ref = resolve_code(code_input.code)
        db.add(RemitCode(
            remit_id=remit.id,
            code=code_input.code,
            category=ref["category"],
            amount=code_input.amount,
            description=ref["description"],
            action_required=ref["action_required"],
        ))

    claim.allowed_amount = body.total_allowed
    claim.paid_amount = body.total_paid

    db.commit()

    log.info(
        "remit_processed",
        claim_id=str(claim_id),
        total_billed=float(body.total_billed),
        total_allowed=float(body.total_allowed),
        total_paid=float(body.total_paid),
        code_count=len(body.codes),
    )

    return db.scalar(
        select(Remit)
        .where(Remit.id == remit.id)
        .options(selectinload(Remit.codes))
    )


@router.get("/{claim_id}/remit", response_model=RemitRead)
def get_remit(claim_id: uuid.UUID, db: Session = Depends(get_db)):
    remit = db.scalar(
        select(Remit)
        .where(Remit.claim_id == claim_id)
        .options(selectinload(Remit.codes))
    )
    if not remit:
        raise HTTPException(status_code=404, detail="No remit found for this claim")
    return remit
