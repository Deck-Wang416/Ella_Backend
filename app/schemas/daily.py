from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ConditionType = Literal["robot", "parent"]
QuestionType = Literal["checkbox", "radio", "textarea"]
OperatorType = Literal["equals", "includesAny"]
class FollowupShowWhen(BaseModel):
    operator: OperatorType
    value: str | list[str]


class FollowupConfig(BaseModel):
    label: str
    showWhen: FollowupShowWhen


class DailyQuestion(BaseModel):
    id: str
    type: QuestionType
    label: str
    options: list[str] | None = None
    followup: FollowupConfig | None = None


class DashboardContent(BaseModel):
    hasInteraction: bool = False
    photos: list[str] = Field(default_factory=list)
    words: list[str] = Field(default_factory=list)
    highlight: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)


class ParentDashboardContent(BaseModel):
    hasInteraction: bool = False
    words: list[str] = Field(default_factory=list)


class DiaryContent(BaseModel):
    submitted: bool = False
    submittedAt: datetime | None = None
    updatedAt: datetime | None = None
    instructions: list[str] = Field(default_factory=list)
    questions: list[DailyQuestion] = Field(default_factory=list)
    responses: dict[str, Any] = Field(default_factory=dict)


class DailyContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    condition: ConditionType = "robot"
    dashboard: DashboardContent | ParentDashboardContent
    diary: DiaryContent


class DailySummary(BaseModel):
    date: str
    condition: ConditionType
    isToday: bool
    hasInteraction: bool
    diarySubmitted: bool
    todayBlueDot: bool
    diarySelectable: bool
    dashboardSelectable: bool
    diaryEditable: bool


class DailyMeta(BaseModel):
    hasInteraction: bool
    diarySubmitted: bool
    diarySelectable: bool
    dashboardSelectable: bool
    diaryEditable: bool


class DailyDetailResponse(BaseModel):
    date: str
    condition: ConditionType
    dashboard: DashboardContent | ParentDashboardContent
    diary: DiaryContent
    meta: DailyMeta


class DailyUpdateRequest(BaseModel):
    responses: dict[str, Any] = Field(default_factory=dict)
    submitted: bool = True


class DailyInitializeRequest(BaseModel):
    condition: ConditionType
