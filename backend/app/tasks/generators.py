import random
import uuid
from decimal import Decimal

import structlog

from app.celery_app import celery
from app.claims.state_machine import transition
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.enums import ClaimStatus
from app.rules.validator import ClaimInput, validate_claim

log = structlog.get_logger()

PROVIDERS = [
    "Dr. Sarah Chen",
    "Dr. Marcus Williams",
    "Dr. Aisha Patel",
    "Dr. James Rodriguez",
    "Dr. Emily Nakamura",
    "Dr. David Okonkwo",
]

PAYERS = ["Aetna", "Cigna", "BCBS", "UnitedHealthcare", "Humana"]

CPT_CODES = ["90837", "90834", "90832"]

DIAGNOSES = [
    "F32.1", "F41.1", "F43.1", "F33.0",
    "F40.10", "F31.81", "F32.0", "F33.1",
]

PATIENT_NAMES = [
    "Maria Santos", "David Kim", "Rebecca Johnson", "Thomas Chen",
    "Jennifer Walsh", "Michael Torres", "Angela Davis", "Robert Nguyen",
    "Christine Park", "James Mitchell", "Sandra Lee", "William Brown",
    "Patricia Garcia", "Christopher Martinez", "Linda Wilson", "Kevin Thompson",
]

BILLED_RANGE = {
    "90837": (200, 280),
    "90834": (160, 220),
    "90832": (130, 175),
}


def _create_one_claim(db) -> str | None:
    """Creates one random claim and transitions it to VALIDATED. Returns claim_id or None."""
    payer = random.choice(PAYERS)
    cpt_code = random.choice(CPT_CODES)
    provider = random.choice(PROVIDERS)
    diagnosis = random.choice(DIAGNOSES)
    patient = random.choice(PATIENT_NAMES)

    lo, hi = BILLED_RANGE[cpt_code]
    billed = Decimal(str(round(random.uniform(lo, hi), 2))).quantize(Decimal("0.01"))

    result = validate_claim(
        ClaimInput(
            patient_name=patient,
            provider_name=provider,
            cpt_code=cpt_code,
            diagnosis_code=diagnosis,
            insurance_payer=payer,
        ),
        db,
    )
    if not result.is_valid:
        log.warning("generator_validation_failed", payer=payer, cpt_code=cpt_code, errors=result.errors)
        return None

    claim = Claim(
        id=uuid.uuid4(),
        patient_name=patient,
        provider_name=provider,
        cpt_code=cpt_code,
        diagnosis_code=diagnosis,
        insurance_payer=payer,
        billed_amount=billed,
        status=ClaimStatus.CREATED,
    )
    db.add(claim)
    db.flush()

    transition(claim, ClaimStatus.VALIDATED, db, idempotency_key=str(uuid.uuid4()))
    return str(claim.id)


@celery.task(name="app.tasks.generators.generate_session_completions")
def generate_session_completions(count: int = 2) -> list[str]:
    """Create `count` VALIDATED claims. Returns list of claim_id strings."""
    db = SessionLocal()
    try:
        claim_ids = []
        for _ in range(count):
            cid = _create_one_claim(db)
            if cid:
                claim_ids.append(cid)
        db.commit()
        log.info("session_completions_generated", count=len(claim_ids))
        return claim_ids
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.generators.run_background_generators")
def run_background_generators() -> None:
    """Beat task: create 1-2 claims, queue submission, run small remittance batch."""
    from app.tasks.remittance import process_remittance_batch
    from app.tasks.submission import process_submission

    db = SessionLocal()
    try:
        count = random.randint(1, 2)
        claim_ids = []
        for _ in range(count):
            cid = _create_one_claim(db)
            if cid:
                claim_ids.append(cid)

        # Transition each to SUBMITTING before queuing the worker
        from app.models.claim import Claim as ClaimModel
        from sqlalchemy import select

        submission_pairs = []
        for claim_id_str in claim_ids:
            claim = db.scalar(
                select(ClaimModel)
                .where(ClaimModel.id == uuid.UUID(claim_id_str))
                .with_for_update()
            )
            if claim and claim.status == ClaimStatus.VALIDATED:
                key = str(uuid.uuid4())
                transition(claim, ClaimStatus.SUBMITTING, db, idempotency_key=key)
                submission_pairs.append((claim_id_str, key))

        db.commit()

        for claim_id_str, key in submission_pairs:
            process_submission.delay(claim_id_str, key)

        process_remittance_batch.delay(limit=3)

        log.info("background_generators_ran", claims_created=len(claim_ids))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
