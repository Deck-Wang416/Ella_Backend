from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class NotificationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caregiver_id: int
    child_id: int
    local_date: date
    slot_time: str
    timezone: str
    status: str
    delivered_count: int
    failed_count: int
    message: str | None
    created_at: datetime
