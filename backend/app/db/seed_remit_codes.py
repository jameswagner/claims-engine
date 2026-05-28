from app.models.remit_code import RemitCodeCategory

REMIT_CODE_LIBRARY: dict[str, dict] = {
    "CO-4": {
        "category": RemitCodeCategory.CONTRACTUAL_OBLIGATION,
        "description": "Procedure code inconsistent with modifier",
        "action_required": "Resubmit with correct modifier",
    },
    "CO-45": {
        "category": RemitCodeCategory.CONTRACTUAL_OBLIGATION,
        "description": "Charge exceeds fee schedule/maximum allowable",
        "action_required": "Write off difference, bill patient responsibility",
    },
    "CO-97": {
        "category": RemitCodeCategory.CONTRACTUAL_OBLIGATION,
        "description": "Procedure bundled with another service — payment included elsewhere",
        "action_required": "Resubmit unbundled or write off",
    },
    "PR-1": {
        "category": RemitCodeCategory.PATIENT_RESPONSIBILITY,
        "description": "Deductible amount",
        "action_required": "Bill patient",
    },
    "PR-2": {
        "category": RemitCodeCategory.PATIENT_RESPONSIBILITY,
        "description": "Coinsurance amount",
        "action_required": "Bill patient",
    },
    "OA-23": {
        "category": RemitCodeCategory.OTHER_ADJUSTMENT,
        "description": "Payment adjusted due to involvement of a prior payer",
        "action_required": "Coordinate with primary insurer",
    },
}


def resolve_code(code: str) -> dict:
    """Return library entry for a code, or a generic fallback for unknown codes."""
    if code in REMIT_CODE_LIBRARY:
        return REMIT_CODE_LIBRARY[code]
    return {
        "category": RemitCodeCategory.OTHER_ADJUSTMENT,
        "description": f"Adjustment code {code}",
        "action_required": "Review manually",
    }
