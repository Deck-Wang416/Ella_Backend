from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PlatformType = Literal["web_push", "fcm", "apns"]


class NotificationSubscriptionUpsert(BaseModel):
    caregiver_id: int
    platform: PlatformType
    endpoint: str = Field(min_length=3, max_length=500)
    keys: dict[str, Any] | None = None


class NotificationSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caregiver_id: int
    platform: PlatformType
    endpoint: str
    keys: dict[str, Any] | None
    active: bool
    created_at: datetime
    updated_at: datetime
