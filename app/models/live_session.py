from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    vin: Mapped[str | None] = mapped_column(String(32), default=None)
    started_utc: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    ended_utc: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="recording")
    target_hz: Mapped[float] = mapped_column(default=1.0)
    achieved_hz: Mapped[float | None] = mapped_column(default=None)
    pids_json: Mapped[str] = mapped_column(default="[]")
    sample_count: Mapped[int] = mapped_column(default=0)
