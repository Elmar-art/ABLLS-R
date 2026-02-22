from datetime import date, datetime, timezone
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EditRequest(Base):
    __tablename__ = "edit_requests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id"), index=True)
    therapist_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    area: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    requested_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_is_prompted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requested_assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_assessment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
