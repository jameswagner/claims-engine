import json
import os
import uuid
from decimal import Decimal
from typing import Annotated

import boto3
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.claims.exceptions import (
    DuplicateTransitionError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.claims.state_machine import TransitionResult, transition
from app.db.session import get_db
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
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

_SQS_QUEUE_URL = os.environ.get("SUBMISSION_QUEUE_URL")
_sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-west-1")) if _SQS_QUEUE_URL else None


def _enqueue_submission(claim_id: str, idempotency_key: str) -> None:
    if _sqs and _SQS_QUEUE_URL:
        _sqs.send_message(
            QueueUrl=_SQS_QUEUE_URL,
            MessageBody=json.dumps({"claim_id": claim_id, "idempotency_key": idempotency_key}),
        )
    else:
        # Local dev fallback — call synchronously via Celery
        from app.tasks.submission import process_submission
        process_submission.delay(claim_id, idempotency_key)


def _fetch(claim_id: uuid.UUID, db: Session, lock: bool = False) -> Claim:
    q = select(Claim).where(Claim.id == claim_id).options(selectinload(Claim.events))
    if lock:
        q = q.with_for_update()
    claim = db.scalar(q)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _transition(claim: Claim, to_status: ClaimStatus, db: Session, key: str, reason: str | None = None) -> TransitionResult:
    """Run transition and map exceptions to HTTP. Returns TransitionResult with replay metadata."""
    try:
        result = transition(claim, to_status, db, reason=reason, idempotency_key=key)
        if result.is_replay:
            log.info("claim_transition_replay", claim_id=str(claim.id), to_status=to_status.value)
        else:
            log.info("claim_transitioned", claim_id=str(claim.id), to_status=to_status.value)
        return result
    except DuplicateTransitionError as e:
        log.warning("claim_idempotency_conflict", claim_id=str(claim.id), to_status=to_status.value, error=str(e))
        raise HTTPException(status_code=409, detail=str(e))
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
def create_claim(
    body: ClaimCreate,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    existing_event = db.scalar(select(ClaimEvent).where(ClaimEvent.idempotency_key == idempotency_key))
    if existing_event:
        return existing_event.claim

    claim = Claim(**body.model_dump(), status=ClaimStatus.CREATED)
    db.add(claim)
    db.flush()
    event = ClaimEvent(
        claim_id=claim.id,
        from_status=ClaimStatus.CREATED,
        to_status=ClaimStatus.CREATED,
        reason="created",
        idempotency_key=idempotency_key,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_event = db.scalar(select(ClaimEvent).where(ClaimEvent.idempotency_key == idempotency_key))
        if existing_event:
            return existing_event.claim
        raise

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


@router.post("/{claim_id}/submit", response_model=ClaimDetail, status_code=202)
def submit_claim(
    claim_id: uuid.UUID,
    body: SubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db, lock=True)
    _transition(claim, ClaimStatus.SUBMITTING, db, idempotency_key, reason=body.clearinghouse_ref)
    db.commit()
    db.refresh(claim)
    _enqueue_submission(str(claim_id), str(uuid.uuid4()))
    return claim


@router.post("/{claim_id}/adjudicate", response_model=ClaimDetail)
def adjudicate_claim(
    claim_id: uuid.UUID,
    body: AdjudicateRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db, lock=True)
    result = _transition(claim, ClaimStatus.ADJUDICATED, db, idempotency_key)
    if not result.is_replay:
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
    result = _transition(claim, ClaimStatus.PAID, db, idempotency_key)
    if not result.is_replay:
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


@router.post("/{claim_id}/resubmit", response_model=ClaimDetail, status_code=202)
def resubmit_claim(
    claim_id: uuid.UUID,
    body: ResubmitRequest,
    idempotency_key: Annotated[str, Header()],
    db: Session = Depends(get_db),
):
    claim = _fetch(claim_id, db, lock=True)
    _transition(claim, ClaimStatus.SUBMITTING, db, idempotency_key, reason=body.correction_notes)
    db.commit()
    db.refresh(claim)
    _enqueue_submission(str(claim_id), str(uuid.uuid4()))
    return claim
