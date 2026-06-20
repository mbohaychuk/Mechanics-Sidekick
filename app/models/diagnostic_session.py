from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiagnosticSession(Base):
    __tablename__ = "diagnostic_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    live_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("live_sessions.id"), default=None
    )
    protocol_name: Mapped[str] = mapped_column(String(40), default="default")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_utc: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    ended_utc: Mapped[datetime | None] = mapped_column(default=None)
    overall_status: Mapped[str | None] = mapped_column(String(10), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    report_json: Mapped[str | None] = mapped_column(Text, default=None)
    commentary_json: Mapped[str | None] = mapped_column(Text, default=None)
