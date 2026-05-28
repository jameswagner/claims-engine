#!/usr/bin/env python3
"""
Seed the database with sample claims in various lifecycle states.
Run once after docker compose up:

    docker exec -w /app claimsprocessing-backend-1 python seed.py
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.claims.state_machine import transition
from app.db.seed_rules import seed as seed_rules
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.enums import ClaimStatus


def seed(db) -> None:
    if db.query(Claim).count() > 0:
        print("Claims already seeded, skipping.")
        return

    seed_rules(db)

    # Maria Santos — stays at CREATED
    c = Claim(
        patient_name="Maria Santos", provider_name="Dr. James Wright",
        cpt_code="90837", diagnosis_code="F32.1", insurance_payer="Aetna",
        billed_amount=Decimal("200.00"), status=ClaimStatus.CREATED,
    )
    db.add(c)
    db.flush()
    print("  Maria Santos              → CREATED")

    # David Kim — VALIDATED
    c = Claim(
        patient_name="David Kim", provider_name="Dr. Lisa Park",
        cpt_code="90834", diagnosis_code="F41.1", insurance_payer="United",
        billed_amount=Decimal("150.00"), status=ClaimStatus.CREATED,
    )
    db.add(c)
    db.flush()
    transition(c, ClaimStatus.VALIDATED, db)
    print("  David Kim                 → VALIDATED")

    # Rebecca Johnson — PAID (with full financial trail)
    c = Claim(
        patient_name="Rebecca Johnson", provider_name="Dr. Carlos Mendez",
        cpt_code="90847", diagnosis_code="F43.1", insurance_payer="BlueCross",
        billed_amount=Decimal("175.00"), status=ClaimStatus.CREATED,
    )
    db.add(c)
    db.flush()
    transition(c, ClaimStatus.VALIDATED, db)
    transition(c, ClaimStatus.SUBMITTED, db)
    transition(c, ClaimStatus.ADJUDICATED, db)
    c.allowed_amount = Decimal("150.00")
    c.patient_responsibility = Decimal("25.00")
    db.flush()
    transition(c, ClaimStatus.PAID, db)
    c.paid_amount = c.allowed_amount - c.patient_responsibility
    db.flush()
    print("  Rebecca Johnson           → PAID")

    # Thomas Chen — DENIED (with adjustment reason)
    c = Claim(
        patient_name="Thomas Chen", provider_name="Dr. Amy Nguyen",
        cpt_code="90832", diagnosis_code="F33.0", insurance_payer="Cigna",
        billed_amount=Decimal("125.00"), status=ClaimStatus.CREATED,
    )
    db.add(c)
    db.flush()
    transition(c, ClaimStatus.VALIDATED, db)
    transition(c, ClaimStatus.SUBMITTED, db)
    transition(c, ClaimStatus.ADJUDICATED, db)
    c.allowed_amount = Decimal("0.00")
    c.adjustment_reason = "CO-97: procedure bundled"
    db.flush()
    transition(c, ClaimStatus.DENIED, db, reason="CO-97: procedure bundled")
    print("  Thomas Chen               → DENIED")

    db.commit()
    print("Done — 4 claims seeded.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
