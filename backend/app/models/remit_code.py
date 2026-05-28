import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RemitCodeCategory(str, enum.Enum):
    CONTRACTUAL_OBLIGATION = "CONTRACTUAL_OBLIGATION"
    PATIENT_RESPONSIBILITY = "PATIENT_RESPONSIBILITY"
    OTHER_ADJUSTMENT = "OTHER_ADJUSTMENT"
    PAYOR_INITIATED = "PAYOR_INITIATED"


class RemitCode(Base):
    __tablename__ = "remit_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    remit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("remits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[RemitCodeCategory] = mapped_column(
        Enum(RemitCodeCategory, name="remitcodecategory", native_enum=False), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    action_required: Mapped[str] = mapped_column(String, nullable=False)

    remit = relationship("Remit", back_populates="codes")
