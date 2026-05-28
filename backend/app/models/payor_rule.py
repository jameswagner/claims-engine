import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RuleType(str, enum.Enum):
    ALLOWED_CPT = "ALLOWED_CPT"
    EXCLUDED_CPT = "EXCLUDED_CPT"
    REQUIRE_DIAGNOSIS_PREFIX = "REQUIRE_DIAGNOSIS_PREFIX"


class PayorRule(Base):
    __tablename__ = "payor_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer: Mapped[str] = mapped_column(String, nullable=False, index=True)
    rule_type: Mapped[RuleType] = mapped_column(
        Enum(RuleType, name="ruletype", native_enum=False), nullable=False
    )
    cpt_code: Mapped[str | None] = mapped_column(String, nullable=True)
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
