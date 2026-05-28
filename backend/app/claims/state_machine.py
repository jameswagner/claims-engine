import time

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.exceptions import (
    DuplicateTransitionError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus
from app.rules.validator import ClaimInput, validate_claim

ALLOWED_TRANSITIONS: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    ClaimStatus.CREATED:     frozenset({ClaimStatus.VALIDATED}),
    ClaimStatus.VALIDATED:   frozenset({ClaimStatus.SUBMITTED}),
    ClaimStatus.SUBMITTED:   frozenset({ClaimStatus.ADJUDICATED}),
    ClaimStatus.ADJUDICATED: frozenset({ClaimStatus.PAID, ClaimStatus.DENIED}),
    ClaimStatus.PAID:        frozenset(),
    ClaimStatus.DENIED:      frozenset({ClaimStatus.SUBMITTED}),
}

log = structlog.get_logger()


def transition(
    claim: Claim,
    to_status: ClaimStatus,
    db: Session,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ClaimEvent:
    start = time.perf_counter()
    from_status = claim.status

    if to_status not in ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        log.warning(
            "transition_rejected",
            claim_id=str(claim.id),
            from_status=from_status.value,
            to_status=to_status.value,
            reason="invalid_transition",
        )
        raise InvalidTransitionError(
            f"Cannot transition from {from_status.value} to {to_status.value}"
        )

    if from_status == ClaimStatus.CREATED and to_status == ClaimStatus.VALIDATED:
        result = validate_claim(
            ClaimInput(
                patient_name=claim.patient_name,
                provider_name=claim.provider_name,
                cpt_code=claim.cpt_code,
                diagnosis_code=claim.diagnosis_code,
                insurance_payer=claim.insurance_payer,
            ),
            db,
        )
        if not result.is_valid:
            log.warning(
                "transition_rejected",
                claim_id=str(claim.id),
                from_status=from_status.value,
                to_status=to_status.value,
                reason="validation_failed",
                errors=result.errors,
            )
            raise ValidationFailedError(result.errors)

    if idempotency_key is not None:
        if db.scalar(select(ClaimEvent).where(ClaimEvent.idempotency_key == idempotency_key)):
            log.warning(
                "transition_rejected",
                claim_id=str(claim.id),
                from_status=from_status.value,
                to_status=to_status.value,
                reason="duplicate_idempotency_key",
                idempotency_key=idempotency_key,
            )
            raise DuplicateTransitionError(
                f"Transition to {to_status.value} already recorded for claim {claim.id}"
            )

    event = ClaimEvent(
        claim_id=claim.id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    claim.status = to_status
    db.flush()

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info(
        "transition_applied",
        claim_id=str(claim.id),
        payer=claim.insurance_payer,
        from_status=from_status.value,
        to_status=to_status.value,
        idempotency_key=idempotency_key,
        duration_ms=duration_ms,
    )

    return event
