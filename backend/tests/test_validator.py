import pytest
from unittest.mock import Mock

from app.models.payor_rule import PayorRule, RuleType
from app.rules.validator import ClaimInput, ValidationResult, validate_claim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_rule(
    payer: str = "*",
    rule_type: RuleType = RuleType.ALLOWED_CPT,
    cpt_code: str | None = None,
    value: str | None = None,
    description: str = "",
) -> PayorRule:
    rule = PayorRule()
    rule.payer = payer
    rule.rule_type = rule_type
    rule.cpt_code = cpt_code
    rule.value = value
    rule.description = description
    return rule


def make_db(*rules: PayorRule) -> Mock:
    """Mock Session whose .scalars(...).all() returns the given rules."""
    db = Mock()
    db.scalars.return_value.all.return_value = list(rules)
    return db


def standard_rules() -> list[PayorRule]:
    """Baseline ruleset matching seed data."""
    return [
        make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90837", description="Individual 60 min"),
        make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90834", description="Individual 45 min"),
        make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90832", description="Individual 30 min"),
        make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90847", description="Family therapy"),
        make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90853", description="Group therapy"),
        make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="Mental health ICD-10"),
    ]


def valid_claim(**overrides) -> ClaimInput:
    defaults = dict(
        patient_name="Jane Doe",
        provider_name="Dr. Smith",
        cpt_code="90837",
        diagnosis_code="F32.1",
        insurance_payer="Aetna",
    )
    return ClaimInput(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_claim_passes():
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(), db)
    assert result.is_valid
    assert result.errors == []


def test_result_type():
    result = validate_claim(valid_claim(), make_db(*standard_rules()))
    assert isinstance(result, ValidationResult)
    assert isinstance(result.errors, list)


# ---------------------------------------------------------------------------
# ALLOWED_CPT rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cpt", ["90837", "90834", "90832", "90847", "90853"])
def test_each_allowed_cpt_passes(cpt):
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(cpt_code=cpt), db)
    cpt_errors = [e for e in result.errors if "CPT code" in e and "not covered" in e]
    assert cpt_errors == []


def test_cpt_not_in_allowed_list_fails():
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(cpt_code="99213"), db)
    assert not result.is_valid
    assert any("99213" in e for e in result.errors)


def test_cpt_error_lists_accepted_codes():
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(cpt_code="99999"), db)
    error_text = " ".join(result.errors)
    assert "90837" in error_text


def test_no_allowed_cpt_rules_means_no_cpt_restriction():
    # If no ALLOWED_CPT rules exist at all, any CPT is accepted
    rules = [make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(cpt_code="99999"), db)
    cpt_errors = [e for e in result.errors if "not covered" in e]
    assert cpt_errors == []


def test_empty_cpt_code_fails_against_allowlist():
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(cpt_code=""), db)
    assert not result.is_valid


# ---------------------------------------------------------------------------
# EXCLUDED_CPT rule
# ---------------------------------------------------------------------------

def test_excluded_cpt_for_specific_payer_fails():
    rules = standard_rules() + [
        make_rule(payer="Medicare", rule_type=RuleType.EXCLUDED_CPT, cpt_code="90853",
                  description="CPT 90853 not covered by Medicare")
    ]
    db = make_db(*rules)
    result = validate_claim(valid_claim(cpt_code="90853", insurance_payer="Medicare"), db)
    assert not result.is_valid
    assert any("90853" in e and "Medicare" in e for e in result.errors)


def test_excluded_cpt_uses_rule_description_as_error():
    exclusion_msg = "Group therapy not a covered Medicare benefit"
    rules = [make_rule(payer="Medicare", rule_type=RuleType.EXCLUDED_CPT,
                       cpt_code="90853", description=exclusion_msg)]
    db = make_db(*rules)
    result = validate_claim(valid_claim(cpt_code="90853", insurance_payer="Medicare"), db)
    assert exclusion_msg in result.errors


def test_excluded_cpt_for_other_payer_not_triggered():
    # 90853 is excluded for Medicare — Aetna should not be affected
    # The DB mock only returns rules applicable to the payer being validated,
    # so Aetna's query wouldn't include Medicare-specific rules.
    rules = standard_rules()  # no Medicare exclusion in this ruleset
    db = make_db(*rules)
    result = validate_claim(valid_claim(cpt_code="90853", insurance_payer="Aetna"), db)
    assert result.is_valid


def test_excluded_cpt_non_matching_code_not_triggered():
    rules = [make_rule(payer="Medicare", rule_type=RuleType.EXCLUDED_CPT,
                       cpt_code="90853", description="Not covered")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(cpt_code="90837", insurance_payer="Medicare"), db)
    excluded_errors = [e for e in result.errors if "Not covered" in e]
    assert excluded_errors == []


# ---------------------------------------------------------------------------
# REQUIRE_DIAGNOSIS_PREFIX rule
# ---------------------------------------------------------------------------

def test_diagnosis_matching_prefix_passes():
    rules = [make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code="F41.1"), db)
    diag_errors = [e for e in result.errors if "prefix" in e]
    assert diag_errors == []


def test_diagnosis_not_matching_prefix_fails():
    rules = [make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="Mental health only")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code="G30.0"), db)
    assert not result.is_valid
    assert any("G30.0" in e for e in result.errors)


def test_diagnosis_prefix_check_is_case_insensitive():
    rules = [make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code="f32.1"), db)
    diag_errors = [e for e in result.errors if "prefix" in e]
    assert diag_errors == []


@pytest.mark.parametrize("code", ["G30.0", "M54.5", "Z00.00", "J06.9"])
def test_non_f_codes_fail(code):
    rules = [make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="Mental health ICD-10")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code=code), db)
    assert not result.is_valid


def test_multiple_prefix_rules_all_checked():
    # hypothetical payer requiring both F and Z codes accepted
    rules = [
        make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="Mental health"),
        make_rule(rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX, value="F", description="Also mental health"),
    ]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code="G30.0"), db)
    # both prefix rules fire
    assert len([e for e in result.errors if "prefix" in e]) == 2


def test_no_prefix_rules_means_no_diagnosis_restriction():
    rules = [make_rule(rule_type=RuleType.ALLOWED_CPT, cpt_code="90837", description="")]
    db = make_db(*rules)
    result = validate_claim(valid_claim(diagnosis_code="G30.0"), db)
    diag_errors = [e for e in result.errors if "prefix" in e]
    assert diag_errors == []


# ---------------------------------------------------------------------------
# Name validation (no DB dependency)
# ---------------------------------------------------------------------------

def test_empty_patient_name_fails():
    result = validate_claim(valid_claim(patient_name=""), make_db())
    assert not result.is_valid
    assert any("patient" in e.lower() for e in result.errors)


def test_whitespace_only_patient_name_fails():
    result = validate_claim(valid_claim(patient_name="   "), make_db())
    assert not result.is_valid


def test_empty_provider_name_fails():
    result = validate_claim(valid_claim(provider_name=""), make_db())
    assert not result.is_valid
    assert any("provider" in e.lower() for e in result.errors)


def test_whitespace_only_provider_name_fails():
    result = validate_claim(valid_claim(provider_name="\t\n"), make_db())
    assert not result.is_valid


def test_single_char_names_pass():
    db = make_db(*standard_rules())
    result = validate_claim(valid_claim(patient_name="X", provider_name="Y"), db)
    assert result.is_valid


# ---------------------------------------------------------------------------
# Multiple errors
# ---------------------------------------------------------------------------

def test_all_rules_checked_independently():
    db = make_db(*standard_rules())
    result = validate_claim(ClaimInput(
        patient_name="",
        provider_name="",
        cpt_code="99999",
        diagnosis_code="G30.0",
        insurance_payer="Aetna",
    ), db)
    assert not result.is_valid
    assert len(result.errors) == 4  # 2 names + CPT + diagnosis


def test_excluded_and_name_errors_accumulate():
    exclusion = make_rule(payer="Medicare", rule_type=RuleType.EXCLUDED_CPT,
                          cpt_code="90853", description="Not covered by Medicare")
    db = make_db(*standard_rules(), exclusion)
    result = validate_claim(ClaimInput(
        patient_name="",
        provider_name="Dr. Smith",
        cpt_code="90853",
        diagnosis_code="F32.1",
        insurance_payer="Medicare",
    ), db)
    assert not result.is_valid
    assert len(result.errors) == 2  # empty name + Medicare exclusion


# ---------------------------------------------------------------------------
# DB query behaviour
# ---------------------------------------------------------------------------

def test_db_query_is_called_once():
    db = make_db(*standard_rules())
    validate_claim(valid_claim(), db)
    assert db.scalars.call_count == 1


def test_wildcard_rules_apply_regardless_of_payer():
    # The wildcard behaviour is enforced by the DB query (payer == claim.payer OR payer == "*").
    # Here we verify the validator correctly uses whatever the DB returns — if the DB
    # returns wildcard rules, they are applied.
    wildcard_rule = make_rule(payer="*", rule_type=RuleType.REQUIRE_DIAGNOSIS_PREFIX,
                              value="F", description="All payers: mental health only")
    db = make_db(wildcard_rule)
    result = validate_claim(valid_claim(diagnosis_code="G30.0"), db)
    assert not result.is_valid
