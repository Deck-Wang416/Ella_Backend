from datetime import datetime, date
from typing import Literal

from pydantic import BaseModel, Field


class RecordingSessionCreateRequest(BaseModel):
    date: date
    caregiverId: int = Field(gt=0)
    childId: int = Field(gt=0)
    chunkFormat: Literal["byte_stream", "standalone"] = "byte_stream"


class FinalAudioRead(BaseModel):
    storagePath: str
    mimeType: str
    sizeBytes: int
    durationSeconds: float
    sha256: str
    sourceChunkCount: int
    mergedAt: datetime


class RecordingSessionRead(BaseModel):
    sessionId: str
    date: str
    caregiverId: int
    childId: int
    condition: Literal["parent"]
    status: Literal["recording", "completed", "failed"]
    mimeType: str | None = None
    chunkFormat: Literal["byte_stream", "standalone"] = "byte_stream"
    uploadedChunks: int
    lastChunkIndex: int
    storagePrefix: str
    durationSeconds: int | None = None
    createdAt: datetime
    updatedAt: datetime
    completedAt: datetime | None = None
    mergeStatus: Literal["pending", "processing", "failed", "completed"] | None = None
    finalAudio: FinalAudioRead | None = None


class RecordingChunkUploadResponse(BaseModel):
    sessionId: str
    chunkIndex: int
    status: str
    storagePath: str
    uploadedChunks: int
    lastChunkIndex: int


class RecordingSessionCompleteRequest(BaseModel):
    finalChunkIndex: int = Field(ge=-1)
    durationSeconds: int | None = Field(default=None, ge=0)
