from pydantic import BaseModel, Field


class RunDueResult(BaseModel):
    checked_caregivers: int
    triggered_notifications: int


class RobotStoryCountUpsertRequest(BaseModel):
    username: str = Field(min_length=1)
    date: str
    storyCount: int = Field(ge=0)


class RobotStoryCountUpsertResponse(BaseModel):
    username: str
    caregiverId: int
    date: str
    condition: str
    storyCount: int
