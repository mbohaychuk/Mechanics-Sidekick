from datetime import datetime, timezone

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LiveSample(Base):
    __tablename__ = "live_samples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_sessions.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column()
    recorded_utc: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    t_offset_ms: Mapped[int] = mapped_column(default=0)
    values_json: Mapped[str] = mapped_column(default="{}")
