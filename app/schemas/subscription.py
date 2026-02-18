from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PlatformType = Literal["web_push", "fcm", "apns"]


class NotificationSubscriptionUpsert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    caregiver_id: int
    platform: PlatformType
    endpoint_or_token: str = Field(min_length=3, max_length=500, alias="endpointOrToken")
    keys: dict[str, Any] | None = None


class NotificationSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    caregiver_id: int
    platform: PlatformType
    endpoint_or_token: str = Field(serialization_alias="endpointOrToken")
    keys: dict[str, Any] | None
    active: bool
    created_at: datetime
    updated_at: datetime


class NotificationSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    endpoint_or_token: str | None = Field(default=None, min_length=3, max_length=500, alias="endpointOrToken")
    keys: dict[str, Any] | None = None
    active: bool | None = None
