from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChildTherapistAssignment(Base):
    __tablename__ = "child_therapist_assignments"
    __table_args__ = (UniqueConstraint("child_id", "therapist_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id"), index=True)
    therapist_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )


class ChildParentAssignment(Base):
    __tablename__ = "child_parent_assignments"
    __table_args__ = (UniqueConstraint("child_id", "parent_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id"), index=True)
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
