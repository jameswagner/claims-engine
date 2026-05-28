import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Enum, String, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ClaimStatus


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    cpt_code: Mapped[str] = mapped_column(String, nullable=False)
    diagnosis_code: Mapped[str] = mapped_column(String, nullable=False)
    insurance_payer: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claimstatus", native_enum=False),
        nullable=False,
        default=ClaimStatus.CREATED,
    )
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    allowed_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    patient_responsibility: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    adjustment_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events = relationship("ClaimEvent", back_populates="claim", cascade="all, delete-orphan")
