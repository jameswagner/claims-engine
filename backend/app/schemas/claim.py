import uuid
from datetime import datetime

from pydantic import BaseModel, field_serializer
from decimal import Decimal

from app.models.enums import ClaimStatus


class ClaimCreate(BaseModel):
    patient_name: str
    provider_name: str
    cpt_code: str
    diagnosis_code: str
    insurance_payer: str
    billed_amount: Decimal


class ClaimEventRead(BaseModel):
    id: uuid.UUID
    from_status: ClaimStatus
    to_status: ClaimStatus
    reason: str | None
    triggered_at: datetime

    model_config = {"from_attributes": True}


class ClaimRead(BaseModel):
    id: uuid.UUID
    patient_name: str
    provider_name: str
    cpt_code: str
    diagnosis_code: str
    insurance_payer: str
    status: ClaimStatus
    billed_amount: Decimal
    allowed_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    patient_responsibility: Decimal | None = None
    adjustment_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("billed_amount", "allowed_amount", "paid_amount", "patient_responsibility")
    def serialize_decimal(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None


class ClaimDetail(ClaimRead):
    events: list[ClaimEventRead] = []


class AdvanceRequest(BaseModel):
    reason: str | None = None
    allowed_amount: Decimal | None = None
    patient_responsibility: Decimal | None = None
    adjustment_reason: str | None = None
