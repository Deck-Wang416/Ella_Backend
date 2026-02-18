from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_log_id: int
    subscription_id: int
    platform: str
    attempt_no: int
    status: str
    provider_message: str | None
    created_at: datetime
