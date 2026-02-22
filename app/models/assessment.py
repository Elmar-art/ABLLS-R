from datetime import date, datetime, timezone
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id"), index=True)
    therapist_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    area: Mapped[str] = mapped_column(String(120))
    score: Mapped[int] = mapped_column(Integer)
    is_prompted: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_date: Mapped[date] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
