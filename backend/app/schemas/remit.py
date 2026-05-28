import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer

from app.models.remit_code import RemitCodeCategory


class RemitCodeInput(BaseModel):
    code: str
    amount: Decimal


class RemitCreate(BaseModel):
    raw_response: str
    total_billed: Decimal
    total_allowed: Decimal
    total_paid: Decimal
    codes: list[RemitCodeInput]


class RemitCodeRead(BaseModel):
    id: uuid.UUID
    code: str
    category: RemitCodeCategory
    amount: Decimal
    description: str
    action_required: str

    model_config = {"from_attributes": True}

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> float:
        return float(v)


class RemitRead(BaseModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    raw_response: str
    processed_at: datetime
    total_billed: Decimal
    total_allowed: Decimal
    total_paid: Decimal
    codes: list[RemitCodeRead] = []

    model_config = {"from_attributes": True}

    @field_serializer("total_billed", "total_allowed", "total_paid")
    def serialize_decimal(self, v: Decimal) -> float:
        return float(v)
