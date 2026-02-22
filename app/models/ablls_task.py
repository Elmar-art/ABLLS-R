from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ABLLSTask(Base):
    __tablename__ = "ablls_tasks"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    section_code: Mapped[str] = mapped_column(String(2), index=True)
    section_name: Mapped[str] = mapped_column(String(120))
    item_number: Mapped[int] = mapped_column(Integer, index=True)
    objective: Mapped[str] = mapped_column(Text)
    criteria: Mapped[str] = mapped_column(Text)
    max_score: Mapped[int] = mapped_column(Integer, default=1)
    source_sheet: Mapped[str] = mapped_column(String(40))
