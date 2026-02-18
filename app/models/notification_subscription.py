from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        UniqueConstraint("caregiver_id", "platform", "endpoint_or_token", name="uq_subscription_unique_endpoint_or_token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    caregiver_id: Mapped[int] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="web_push")
    endpoint_or_token: Mapped[str] = mapped_column(String(500), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    keys: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
