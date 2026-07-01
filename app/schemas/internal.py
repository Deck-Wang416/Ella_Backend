from pydantic import BaseModel, Field


class RunDueResult(BaseModel):
    checked_caregivers: int
    triggered_notifications: int


class RobotStoryCountIncrementRequest(BaseModel):
    username: str = Field(min_length=1)
    eventId: str = Field(min_length=1)
    completedAt: str = Field(min_length=1)


class RobotStoryCountIncrementResponse(BaseModel):
    ok: bool
    username: str
    eventId: str
    storyDate: str
    dailyStoryCount: int
    weekNumber: int
    weekStartDate: str
    weekEndDate: str
    weeklyStoryCount: int
    applied: bool


class RobotCurrentWeekResponse(BaseModel):
    ok: bool
    username: str
    weekNumber: int
    weekStartDate: str
    weekEndDate: str
    storyCount: int


class RobotPhotoUploadResponse(BaseModel):
    ok: bool
    username: str
    date: str
    photoUrl: str
