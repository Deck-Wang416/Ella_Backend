from pydantic import BaseModel


class RunDueResult(BaseModel):
    checked_caregivers: int
    triggered_notifications: int
