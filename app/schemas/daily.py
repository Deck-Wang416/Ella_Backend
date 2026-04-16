from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ModeType = Literal["robot", "parent"]
QuestionType = Literal["checkbox", "radio", "textarea"]
OperatorType = Literal["equals", "includesAny"]
RecordingStatusType = Literal["recording", "completed", "failed"]


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


class ParentAudioSession(BaseModel):
    sessionId: str
    status: RecordingStatusType
    uploadedChunks: int = 0
    lastChunkIndex: int = -1


class ParentAudioMeta(BaseModel):
    enabled: bool = False
    activeSession: ParentAudioSession | None = None


class RobotDashboardContent(BaseModel):
    hasInteraction: bool = False
    photos: list[str] = Field(default_factory=list)
    words: list[str] = Field(default_factory=list)
    highlight: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)


class ParentDashboardContent(BaseModel):
    hasInteraction: bool = False
    words: list[str] = Field(default_factory=list)
    highlight: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)


class DiaryContent(BaseModel):
    submitted: bool = False
    submittedAt: datetime | None = None
    updatedAt: datetime | None = None
    instructions: list[str] = Field(default_factory=list)
    questions: list[DailyQuestion] = Field(default_factory=list)
    responses: dict[str, Any] = Field(default_factory=dict)


class RobotModeContent(BaseModel):
    dashboard: RobotDashboardContent
    diary: DiaryContent


class ParentModeContent(BaseModel):
    dashboard: ParentDashboardContent
    diary: DiaryContent
    parentAudio: ParentAudioMeta | None = None


class DailyModes(BaseModel):
    robot: RobotModeContent | None = None
    parent: ParentModeContent | None = None


class DailyContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    availableModes: list[ModeType] = Field(default_factory=lambda: ["robot"])
    defaultMode: ModeType = "robot"
    modes: DailyModes


class DailySummary(BaseModel):
    date: str
    availableModes: list[ModeType]
    defaultMode: ModeType
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
    availableModes: list[ModeType]
    defaultMode: ModeType
    selectedMode: ModeType
    dashboard: RobotDashboardContent | ParentDashboardContent
    diary: DiaryContent
    meta: DailyMeta
    parentAudio: ParentAudioMeta | None = None


class DailyUpdateRequest(BaseModel):
    responses: dict[str, Any] = Field(default_factory=dict)
    submitted: bool = True


class DailyModeCreateRequest(BaseModel):
    makeDefault: bool = False
