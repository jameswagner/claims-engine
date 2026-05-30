import random
import uuid
from decimal import Decimal

import structlog
from sqlalchemy import select

from app.celery_app import celery
from app.claims.state_machine import transition
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.enums import ClaimStatus

log = structlog.get_logger()

# Live denial rates — Aetna 90837 at 35% creates the spike visible in analytics.
# Historical seed uses ~15% so the dashboard shows a flat baseline until replay runs.
_DENIAL_RATES: dict[tuple[str, str | None], float] = {
    ("Aetna",            "90837"): 0.35,
    ("Aetna",            None   ): 0.18,
    ("UnitedHealthcare", None   ): 0.20,
    ("Cigna",            None   ): 0.14,
    ("Humana",           None   ): 0.13,
    ("BCBS",             None   ): 0.10,
}

_DENIAL_REASONS = [
    "CO-97: procedure bundled, not separately payable",
    "CO-45: charge exceeds contracted fee schedule",
    "CO-50: service not deemed medically necessary",
    "PR-1: deductible amount not yet met",
    "CO-4: procedure inconsistent with modifier",
]


def _denial_rate(payer: str, cpt_code: str) -> float:
    return (
        _DENIAL_RATES.get((payer, cpt_code))
        or _DENIAL_RATES.get((payer, None))
        or 0.12
    )


@celery.task(name="app.tasks.remittance.process_remittance_batch")
def process_remittance_batch(limit: int = 10) -> dict:
    """
    Simulate 835 EOB batch processing. Finds up to `limit` SUBMITTED claims
    oldest-first and adjudicates them with payer-specific denial rates.
    Commits per claim so partial success is safe on worker restart.
    """
    db = SessionLocal()
    paid = denied = skipped = 0

    try:
        claims = db.scalars(
            select(Claim)
            .where(Claim.status == ClaimStatus.SUBMITTED)
            .order_by(Claim.updated_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()

        for claim in claims:
            try:
                is_denied = random.random() < _denial_rate(claim.insurance_payer, claim.cpt_code)

                adj_key = str(uuid.uuid4())
                transition(claim, ClaimStatus.ADJUDICATED, db, idempotency_key=adj_key)

                if is_denied:
                    reason = random.choice(_DENIAL_REASONS)
                    claim.allowed_amount = Decimal("0.00")
                    claim.adjustment_reason = reason
                    db.flush()
                    transition(
                        claim,
                        ClaimStatus.DENIED,
                        db,
                        reason=reason,
                        idempotency_key=str(uuid.uuid4()),
                    )
                    denied += 1
                else:
                    allowed = (
                        claim.billed_amount
                        * Decimal(str(round(random.uniform(0.82, 0.95), 4)))
                    ).quantize(Decimal("0.01"))
                    patient_resp = (allowed * Decimal("0.20")).quantize(Decimal("0.01"))
                    claim.allowed_amount = allowed
                    claim.patient_responsibility = patient_resp
                    db.flush()
                    transition(
                        claim,
                        ClaimStatus.PAID,
                        db,
                        idempotency_key=str(uuid.uuid4()),
                    )
                    claim.paid_amount = allowed - patient_resp
                    paid += 1

                db.commit()

            except Exception as exc:
                db.rollback()
                log.error("remittance_claim_failed", claim_id=str(claim.id), error=str(exc))
                skipped += 1

    finally:
        db.close()

    log.info("remittance_batch_processed", paid=paid, denied=denied, skipped=skipped)
    return {"paid": paid, "denied": denied, "skipped": skipped}
