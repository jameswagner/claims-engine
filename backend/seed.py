#!/usr/bin/env python3
"""
Seed the database with 8 days of flat, unremarkable claim history (t-10 through t-3).

All denial rates are normal baseline — no Aetna spike. The spike emerges in real
time via the fast-forward demo, which adds t-2, t-1, and today one click at a time.

    docker exec -w /app claimsprocessing-backend-1 python seed.py
"""
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db.seed_rules import seed as seed_rules
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus
from app.models.payor_rule import PayorRule
from app.models.remit import Remit
from app.models.remit_code import RemitCode

random.seed(42)

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
    "Barbara Anderson", "Steven Jackson", "Susan White", "Joseph Harris",
    "Dorothy Taylor", "Richard Moore", "Lisa Jones", "Charles Davis",
    "Nancy Miller", "Mark Wilson", "Betty Anderson", "Paul Thompson",
    "Helen Martinez", "Donald Garcia",
]

# Flat baseline — no spike, no anomaly
_NORMAL_RATES: dict[tuple[str | None, str | None], float] = {
    ("Aetna",            "90837"): 0.15,
    ("Aetna",            None   ): 0.12,
    ("BCBS",             None   ): 0.08,
    ("UnitedHealthcare", None   ): 0.12,
    ("Cigna",            None   ): 0.11,
    ("Humana",           None   ): 0.12,
    (None,               None   ): 0.12,
}

DENIAL_REASONS = [
    "CO-97: procedure bundled, not separately payable",
    "CO-45: charge exceeds contracted fee schedule",
    "CO-50: service not deemed medically necessary",
    "PR-1: deductible amount not yet met",
    "CO-4: procedure inconsistent with modifier",
]

BILLED_RANGE: dict[str, tuple[int, int]] = {
    "90837": (200, 280),
    "90834": (160, 220),
    "90832": (130, 175),
}


PLACE_OF_SERVICE_CHOICES = ["telehealth", "in-office"]

def _denial_rate(payer: str, cpt_code: str, place_of_service: str) -> float:
    base = (
        _NORMAL_RATES.get((payer, cpt_code))
        or _NORMAL_RATES.get((payer, None))
        or _NORMAL_RATES[(None, None)]
    )
    return base + 0.05 if place_of_service == "telehealth" else base


def _adj_days(payer: str) -> int:
    if payer == "UnitedHealthcare":
        return random.randint(35, 55)
    return random.randint(15, 25)


def _event(
    claim_id: uuid.UUID,
    from_status: ClaimStatus,
    to_status: ClaimStatus,
    triggered_at: datetime,
    reason: str | None = None,
) -> ClaimEvent:
    return ClaimEvent(
        id=uuid.uuid4(),
        claim_id=claim_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        idempotency_key=str(uuid.uuid4()),
        triggered_at=triggered_at,
    )


def _seed_day(db, day_date: date, count: int) -> None:
    """
    Write `count` fully adjudicated claims whose ADJUDICATED→{PAID,DENIED} event
    falls on `day_date`. Timestamps work backwards from that resolution point.
    """
    for i in range(count):
        payer = random.choice(PAYERS)
        cpt_code = random.choice(CPT_CODES)

        resolved_at = datetime(
            day_date.year, day_date.month, day_date.day,
            random.randint(6, 22), random.randint(0, 59), random.randint(0, 59),
            tzinfo=timezone.utc,
        )
        adjudicated_at = resolved_at - timedelta(hours=random.randint(1, 4))
        submitted_at = adjudicated_at - timedelta(days=_adj_days(payer), hours=random.randint(0, 12))
        validated_at = submitted_at - timedelta(days=random.randint(1, 2), hours=random.randint(1, 6))
        created_at = validated_at - timedelta(days=random.randint(1, 2), hours=random.randint(1, 6))

        pos = random.choices(PLACE_OF_SERVICE_CHOICES, weights=[60, 40])[0]
        lo, hi = BILLED_RANGE[cpt_code]
        billed = Decimal(str(round(random.uniform(lo, hi), 2))).quantize(Decimal("0.01"))
        is_denied = random.random() < _denial_rate(payer, cpt_code, pos)
        denial_reason = random.choice(DENIAL_REASONS) if is_denied else None

        if is_denied:
            allowed = Decimal("0.00")
            patient_resp = None
            paid_amt = None
            final_status = ClaimStatus.DENIED
        else:
            allowed = (billed * Decimal(str(round(random.uniform(0.82, 0.95), 4)))).quantize(Decimal("0.01"))
            patient_resp = (allowed * Decimal("0.20")).quantize(Decimal("0.01"))
            paid_amt = allowed - patient_resp
            final_status = ClaimStatus.PAID

        claim = Claim(
            id=uuid.uuid4(),
            patient_name=random.choice(PATIENT_NAMES),
            provider_name=random.choice(PROVIDERS),
            cpt_code=cpt_code,
            diagnosis_code=random.choice(DIAGNOSES),
            insurance_payer=payer,
            billed_amount=billed,
            status=final_status,
            allowed_amount=allowed,
            patient_responsibility=patient_resp,
            paid_amount=paid_amt,
            adjustment_reason=denial_reason if is_denied else None,
            place_of_service=pos,
            created_at=created_at,
            updated_at=resolved_at,
        )
        db.add(claim)
        db.flush()

        events: list[ClaimEvent] = [
            _event(claim.id, ClaimStatus.CREATED,    ClaimStatus.VALIDATED,   validated_at),
            _event(claim.id, ClaimStatus.VALIDATED,  ClaimStatus.SUBMITTED,   submitted_at),
            _event(claim.id, ClaimStatus.SUBMITTED,  ClaimStatus.ADJUDICATED, adjudicated_at),
        ]
        if is_denied:
            events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.DENIED, resolved_at, reason=denial_reason))
        else:
            events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.PAID, resolved_at))
        db.add_all(events)

        if (i + 1) % 100 == 0:
            db.commit()

    db.commit()


def seed(db, force: bool = False) -> None:
    if db.query(Claim).count() > 0:
        if not force:
            print("Claims already seeded, skipping.")
            return
        print("--force set: clearing existing data...")
        db.query(RemitCode).delete()
        db.query(Remit).delete()
        db.query(ClaimEvent).delete()
        db.query(Claim).delete()
        db.query(PayorRule).delete()
        db.commit()
        print("Cleared.")

    seed_rules(db)

    now = datetime.now(timezone.utc)
    claims_per_day = 800

    # Seed t-10 through t-3: 8 days of flat baseline, all normal denial rates.
    # t-2, t-1, and today are left empty — the fast-forward fills them one click at a time.
    for day_offset in range(10, 2, -1):  # 10, 9, 8, 7, 6, 5, 4, 3
        day_date = (now - timedelta(days=day_offset)).date()
        print(f"Seeding {day_date} ({claims_per_day} claims)...")
        _seed_day(db, day_date, count=claims_per_day)

    total = 8 * claims_per_day
    print(f"\nDone — {total} claims seeded across 8 days (t-10 through t-3).")
    print("Dashboard will show a flat baseline. Use fast-forward to reveal the Aetna anomaly.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    db = SessionLocal()
    try:
        seed(db, force=force)
    finally:
        db.close()
