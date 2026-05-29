import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Remit(Base):
    __tablename__ = "remits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_billed: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_allowed: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_paid: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    codes = relationship("RemitCode", back_populates="remit", cascade="all, delete-orphan")
