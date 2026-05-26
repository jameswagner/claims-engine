import uuid
from datetime import datetime

from sqlalchemy import Enum, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ClaimStatus


class ClaimEvent(Base):
    __tablename__ = "claim_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claimstatus", native_enum=False), nullable=False
    )
    to_status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claimstatus", native_enum=False), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="events")
