import pytest

from app.db.seed_remit_codes import REMIT_CODE_LIBRARY, resolve_code
from app.models.remit_code import RemitCodeCategory


def test_all_library_codes_have_required_keys():
    for code, entry in REMIT_CODE_LIBRARY.items():
        assert "category" in entry, f"{code} missing category"
        assert "description" in entry, f"{code} missing description"
        assert "action_required" in entry, f"{code} missing action_required"


def test_co_codes_are_contractual_obligation():
    assert resolve_code("CO-4")["category"] == RemitCodeCategory.CONTRACTUAL_OBLIGATION
    assert resolve_code("CO-45")["category"] == RemitCodeCategory.CONTRACTUAL_OBLIGATION
    assert resolve_code("CO-97")["category"] == RemitCodeCategory.CONTRACTUAL_OBLIGATION


def test_pr_codes_are_patient_responsibility():
    assert resolve_code("PR-1")["category"] == RemitCodeCategory.PATIENT_RESPONSIBILITY
    assert resolve_code("PR-2")["category"] == RemitCodeCategory.PATIENT_RESPONSIBILITY


def test_oa_codes_are_other_adjustment():
    assert resolve_code("OA-23")["category"] == RemitCodeCategory.OTHER_ADJUSTMENT


def test_known_code_returns_correct_description():
    result = resolve_code("CO-97")
    assert "bundled" in result["description"].lower()


def test_known_code_returns_action_required():
    result = resolve_code("PR-1")
    assert result["action_required"] == "Bill patient"


def test_unknown_code_returns_fallback():
    result = resolve_code("XX-999")
    assert result["category"] == RemitCodeCategory.OTHER_ADJUSTMENT
    assert "XX-999" in result["description"]
    assert result["action_required"] == "Review manually"


def test_unknown_code_does_not_raise():
    result = resolve_code("TOTALLY-MADE-UP")
    assert result is not None


@pytest.mark.parametrize("code", ["CO-4", "CO-45", "CO-97", "PR-1", "PR-2", "OA-23"])
def test_all_seeded_codes_resolve(code):
    result = resolve_code(code)
    assert result["category"] in RemitCodeCategory.__members__.values()
    assert result["description"]
    assert result["action_required"]
