import enum


class ClaimStatus(str, enum.Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    DENIED = "DENIED"
