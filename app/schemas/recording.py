from datetime import datetime, date
from typing import Literal

from pydantic import BaseModel, Field


class RecordingSessionCreateRequest(BaseModel):
    date: date
    caregiverId: int = Field(gt=0)
    childId: int = Field(gt=0)


class RecordingSessionRead(BaseModel):
    sessionId: str
    date: str
    caregiverId: int
    childId: int
    condition: Literal["parent"]
    status: Literal["recording", "completed", "failed"]
    mimeType: str | None = None
    uploadedChunks: int
    lastChunkIndex: int
    storagePrefix: str
    createdAt: datetime
    updatedAt: datetime
    completedAt: datetime | None = None


class RecordingChunkUploadResponse(BaseModel):
    sessionId: str
    chunkIndex: int
    status: str
    storagePath: str
    uploadedChunks: int
    lastChunkIndex: int


class RecordingSessionCompleteRequest(BaseModel):
    finalChunkIndex: int = Field(ge=-1)
