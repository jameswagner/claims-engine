#!/usr/bin/env python3
"""
Seed the database with 300 historically resolved claims (6 months of backstory).

Historical Aetna denial rate on 90837 is intentionally unremarkable (~15%).
The live remittance workers crank it to 35% during demo replay — the spike
emerges in real time rather than being pre-baked into the dashboard.

    docker exec -w /app claimsprocessing-backend-1 python seed.py
"""
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db.seed_rules import seed as seed_rules
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus

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

# Historical denial rates — intentionally unremarkable baseline.
# Live workers use 35% for Aetna+90837 to create the spike.
_DENIAL_RATES: dict[tuple[str | None, str | None], float] = {
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

# Billed amount range (dollars) by CPT code
BILLED_RANGE: dict[str, tuple[int, int]] = {
    "90837": (200, 280),
    "90834": (160, 220),
    "90832": (130, 175),
}


def denial_rate(payer: str, cpt_code: str) -> float:
    return (
        _DENIAL_RATES.get((payer, cpt_code))
        or _DENIAL_RATES.get((payer, None))
        or _DENIAL_RATES[(None, None)]
    )


def adj_days(payer: str) -> int:
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


def seed(db) -> None:
    if db.query(Claim).count() > 0:
        print("Claims already seeded, skipping.")
        return

    seed_rules(db)

    now = datetime.now(timezone.utc)
    target = 300
    resubmit_budget = 40
    resubmit_count = 0

    print(f"Generating {target} historical claims...")

    for i in range(target):
        payer = random.choice(PAYERS)
        cpt_code = random.choice(CPT_CODES)
        provider = random.choice(PROVIDERS)
        diagnosis = random.choice(DIAGNOSES)
        patient = random.choice(PATIENT_NAMES)

        # Spread across last 6 months; bias toward older so claims are fully resolved
        days_ago = random.randint(30, 180)
        created_at = now - timedelta(days=days_ago, hours=random.randint(0, 12))

        lo, hi = BILLED_RANGE[cpt_code]
        billed = Decimal(str(round(random.uniform(lo, hi), 2))).quantize(Decimal("0.01"))

        is_denied = random.random() < denial_rate(payer, cpt_code)
        do_resubmit = (
            is_denied
            and resubmit_count < resubmit_budget
            and random.random() < 0.65
        )

        # --- Timestamps ---
        validated_at = created_at + timedelta(days=random.randint(1, 2), hours=random.randint(1, 6))
        submitted_at = validated_at + timedelta(days=random.randint(1, 3), hours=random.randint(1, 6))
        adjudicated_at = submitted_at + timedelta(days=adj_days(payer), hours=random.randint(1, 6))
        resolved_at = adjudicated_at + timedelta(hours=random.randint(1, 8))

        denial_reason = random.choice(DENIAL_REASONS) if is_denied else None

        # Resubmission timestamps (only if claim gets resubmitted after denial)
        if do_resubmit:
            resub_submitted_at = resolved_at + timedelta(days=random.randint(3, 7))
            resub_adjudicated_at = resub_submitted_at + timedelta(days=adj_days(payer))
            resub_paid_at = resub_adjudicated_at + timedelta(hours=random.randint(1, 8))
            final_at = resub_paid_at
            resubmit_count += 1
        else:
            resub_submitted_at = resub_adjudicated_at = resub_paid_at = None
            final_at = resolved_at

        # --- Financials ---
        final_status = ClaimStatus.DENIED if (is_denied and not do_resubmit) else ClaimStatus.PAID

        if final_status == ClaimStatus.PAID:
            allowed = (billed * Decimal(str(round(random.uniform(0.82, 0.95), 4)))).quantize(Decimal("0.01"))
            patient_resp = (allowed * Decimal("0.20")).quantize(Decimal("0.01"))
            paid_amt = allowed - patient_resp
        else:
            allowed = Decimal("0.00")
            patient_resp = None
            paid_amt = None

        # --- Claim row ---
        claim = Claim(
            id=uuid.uuid4(),
            patient_name=patient,
            provider_name=provider,
            cpt_code=cpt_code,
            diagnosis_code=diagnosis,
            insurance_payer=payer,
            billed_amount=billed,
            status=final_status,
            allowed_amount=allowed,
            patient_responsibility=patient_resp,
            paid_amount=paid_amt,
            adjustment_reason=denial_reason if final_status == ClaimStatus.DENIED else None,
            created_at=created_at,
            updated_at=final_at,
        )
        db.add(claim)
        db.flush()

        # --- Events ---
        events = [
            _event(claim.id, ClaimStatus.CREATED,    ClaimStatus.VALIDATED,   validated_at),
            _event(claim.id, ClaimStatus.VALIDATED,  ClaimStatus.SUBMITTED,   submitted_at),
            _event(claim.id, ClaimStatus.SUBMITTED,  ClaimStatus.ADJUDICATED, adjudicated_at),
        ]

        if is_denied:
            events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.DENIED, resolved_at, reason=denial_reason))
            if do_resubmit:
                events += [
                    _event(claim.id, ClaimStatus.DENIED,      ClaimStatus.SUBMITTED,   resub_submitted_at),
                    _event(claim.id, ClaimStatus.SUBMITTED,   ClaimStatus.ADJUDICATED, resub_adjudicated_at),
                    _event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.PAID,        resub_paid_at),
                ]
        else:
            events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.PAID, resolved_at))

        db.add_all(events)

        if (i + 1) % 50 == 0:
            db.commit()
            print(f"  {i + 1}/{target} committed...")

    db.commit()
    print(f"Done — {target} historical claims seeded ({resubmit_count} deny→resubmit→paid).")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
