import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.payor_rule import PayorRule, RuleType

WILDCARD = "*"

log = structlog.get_logger()


@dataclass
class ClaimInput:
    patient_name: str
    provider_name: str
    cpt_code: str
    diagnosis_code: str
    insurance_payer: str


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)


def validate_claim(claim: ClaimInput, db: Session) -> ValidationResult:
    start = time.perf_counter()
    errors: list[str] = []

    claim.patient_name = claim.patient_name.strip()
    claim.provider_name = claim.provider_name.strip()
    claim.cpt_code = claim.cpt_code.strip()
    claim.diagnosis_code = claim.diagnosis_code.strip()
    claim.insurance_payer = claim.insurance_payer.strip()

    if not claim.patient_name:
        errors.append("Patient name cannot be empty")

    if not claim.provider_name:
        errors.append("Provider name cannot be empty")

    rules = db.scalars(
        select(PayorRule).where(
            or_(PayorRule.payer == claim.insurance_payer, PayorRule.payer == WILDCARD)
        )
    ).all()

    allowed_cpts = {r.cpt_code for r in rules if r.rule_type == RuleType.ALLOWED_CPT}
    if allowed_cpts and claim.cpt_code not in allowed_cpts:
        errors.append(
            f"CPT code '{claim.cpt_code}' is not covered "
            f"(accepted: {', '.join(sorted(allowed_cpts))})"
        )

    for rule in rules:
        if rule.rule_type == RuleType.EXCLUDED_CPT and rule.cpt_code == claim.cpt_code:
            errors.append(rule.description)

    for rule in rules:
        if rule.rule_type == RuleType.REQUIRE_DIAGNOSIS_PREFIX and rule.value:
            if not claim.diagnosis_code.upper().startswith(rule.value.upper()):
                errors.append(
                    f"Diagnosis code '{claim.diagnosis_code}' does not match "
                    f"required prefix '{rule.value}' — {rule.description}"
                )

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info(
        "claim_validated",
        payer=claim.insurance_payer,
        cpt_code=claim.cpt_code,
        is_valid=len(errors) == 0,
        errors=errors,
        duration_ms=duration_ms,
    )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)
