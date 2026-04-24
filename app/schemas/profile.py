from datetime import datetime

from pydantic import BaseModel


class ConditionRange(BaseModel):
    startDate: str
    endDate: str


class UserProfileContent(BaseModel):
    caregiverId: int
    robot_condition_range: ConditionRange | None = None
    parent_condition_range: ConditionRange | None = None
    updatedAt: datetime | None = None


class UserProfileUpdateRequest(BaseModel):
    robot_condition_range: ConditionRange | None = None
    parent_condition_range: ConditionRange | None = None
