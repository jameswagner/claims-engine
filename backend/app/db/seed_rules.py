from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.payor_rule import PayorRule, RuleType

BASELINE_RULES = [
    # --- CPT allowlist (applies to all payers) ---
    PayorRule(
        payer="*", rule_type=RuleType.ALLOWED_CPT, cpt_code="90837",
        description="Individual psychotherapy, 60 min",
    ),
    PayorRule(
        payer="*", rule_type=RuleType.ALLOWED_CPT, cpt_code="90834",
        description="Individual psychotherapy, 45 min",
    ),
    PayorRule(
        payer="*", rule_type=RuleType.ALLOWED_CPT, cpt_code="90832",
        description="Individual psychotherapy, 30 min",
    ),
    PayorRule(
        payer="*", rule_type=RuleType.ALLOWED_CPT, cpt_code="90847",
        description="Family psychotherapy with patient present",
    ),
    PayorRule(
        payer="*", rule_type=RuleType.ALLOWED_CPT, cpt_code="90853",
        description="Group psychotherapy",
    ),
    # --- Diagnosis prefix requirement (applies to all payers) ---
    PayorRule(
        payer="*", rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F",
        description="Diagnosis must be a mental health ICD-10 code (F00–F99)",
    ),
    # --- Medicare-specific exclusions ---
    PayorRule(
        payer="Medicare", rule_type=RuleType.EXCLUDED_CPT, cpt_code="90853",
        description="CPT 90853 (group therapy) is not covered by Medicare",
    ),
]


def seed(db: Session) -> None:
    if db.query(PayorRule).count() == 0:
        db.add_all(BASELINE_RULES)
        db.commit()
        print(f"Seeded {len(BASELINE_RULES)} payor rules.")
    else:
        print("Payor rules already seeded, skipping.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
