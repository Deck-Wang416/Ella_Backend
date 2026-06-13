from datetime import datetime

from pydantic import BaseModel, Field


class ConditionRange(BaseModel):
    startDate: str
    endDate: str


class UserProfileContent(BaseModel):
    caregiverId: int
    username: str | None = None
    themes: list[str] = Field(default_factory=list)
    dayCount: int | None = None
    robot_condition_range: ConditionRange | None = None
    parent_condition_range: ConditionRange | None = None
    updatedAt: datetime | None = None


class UserProfileUpdateRequest(BaseModel):
    themes: list[str]
