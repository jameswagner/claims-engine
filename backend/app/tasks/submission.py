import random
import time
import uuid

import structlog
from sqlalchemy import select

from app.celery_app import celery
from app.claims.state_machine import transition
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.enums import ClaimStatus

log = structlog.get_logger()

_CLEARINGHOUSE_REJECTION_RATE = 0.20
_REJECTION_REASON = "EDI validation failed: invalid NPI format"


@celery.task(
    name="app.tasks.submission.process_submission",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_submission(self, claim_id_str: str, idempotency_key: str) -> dict:
    """
    Simulate clearinghouse EDI round-trip for a SUBMITTING claim.
    80% → SUBMITTED, 20% → CLEARINGHOUSE_REJECTED.
    """
    db = SessionLocal()
    try:
        claim = db.scalar(
            select(Claim)
            .where(Claim.id == uuid.UUID(claim_id_str))
            .with_for_update()
        )

        if not claim:
            log.error("submission_claim_not_found", claim_id=claim_id_str)
            return {"status": "error", "reason": "not_found"}

        if claim.status != ClaimStatus.SUBMITTING:
            log.warning(
                "submission_wrong_status",
                claim_id=claim_id_str,
                status=claim.status.value,
            )
            return {"status": "skipped", "reason": f"status_is_{claim.status.value}"}

        # Simulate EDI round-trip latency
        time.sleep(random.uniform(0.5, 2.0))

        if random.random() < _CLEARINGHOUSE_REJECTION_RATE:
            transition(
                claim,
                ClaimStatus.CLEARINGHOUSE_REJECTED,
                db,
                reason=_REJECTION_REASON,
                idempotency_key=idempotency_key,
            )
            outcome = "clearinghouse_rejected"
        else:
            transition(
                claim,
                ClaimStatus.SUBMITTED,
                db,
                idempotency_key=idempotency_key,
            )
            outcome = "submitted"

        db.commit()
        log.info("submission_processed", claim_id=claim_id_str, outcome=outcome)
        return {"status": outcome, "claim_id": claim_id_str}

    except Exception as exc:
        db.rollback()
        log.error("submission_failed", claim_id=claim_id_str, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
