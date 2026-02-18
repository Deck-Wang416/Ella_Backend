from datetime import date

from pydantic import BaseModel, Field


class InternalTestSendRequest(BaseModel):
    caregiver_id: int
    child_id: int
    local_date: date
    slot_time: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "UTC"
    message: str = "Diary not submitted yet"


class InternalTestSendResult(BaseModel):
    accepted: bool


class NotificationMetrics(BaseModel):
    total_logs: int
    sent: int
    partial: int
    failed: int
    no_subscription: int
