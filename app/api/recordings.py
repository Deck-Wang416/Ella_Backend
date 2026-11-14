from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from starlette.concurrency import run_in_threadpool

from app.schemas.recording import (
    RecordingChunkUploadResponse,
    RecordingSessionCancelRequest,
    RecordingSessionCompleteRequest,
    RecordingSessionCreateRequest,
    RecordingSessionRead,
)
from app.services.firebase_recording_service import FirebaseRecordingService
from app.services.recording_merge_service import RecordingMergeService
from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference

logger = logging.getLogger(__name__)
MAX_CHUNK_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/recordings", tags=["recordings"])


class RecordingPerfEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0, le=10000)
    name: Literal[
        "stop saved locally", "interrupted", "chunk request started", "chunk request failed",
        "chunk confirmed", "complete requested", "complete confirmed",
    ]
    at: datetime
    recordingId: str = Field(min_length=1, max_length=40)
    chunkIndex: int | None = Field(default=None, ge=0, le=10000)
    attempt: int | None = Field(default=None, ge=1, le=10)
    attempts: int | None = Field(default=None, ge=1, le=10)
    status: int | Literal["network error"] | None = None
    sizeBytes: int | None = Field(default=None, ge=0, le=10000000)
    sealedChunksAtScan: int | None = Field(default=None, ge=0, le=10000)
    readMs: int | None = Field(default=None, ge=0)
    decodeMs: int | None = Field(default=None, ge=0)
    requestMs: int | None = Field(default=None, ge=0)
    confirmMs: int | None = Field(default=None, ge=0)
    totalMs: int | None = Field(default=None, ge=0)
    durationSeconds: float | None = Field(default=None, ge=0)
    totalChunks: int | None = Field(default=None, ge=0)
    uploadedChunks: int | None = Field(default=None, ge=0)
    pendingChunks: int | None = Field(default=None, ge=0)
    stopCallMs: int | None = Field(default=None, ge=0)
    stopToCompleteSeconds: int | None = Field(default=None, ge=0)
    completeMs: int | None = Field(default=None, ge=0)
    uploadedChunksThisRun: int | None = Field(default=None, ge=0)
    uploadedBytesThisRun: int | None = Field(default=None, ge=0)
    meanRequestMs: int | None = Field(default=None, ge=0)
    meanTotalMs: int | None = Field(default=None, ge=0)
    failedAttempts: int | None = Field(default=None, ge=0)


class RecordingPerfBatch(BaseModel):
    events: list[RecordingPerfEvent] = Field(min_length=1, max_length=20)


@router.post("/sessions", response_model=RecordingSessionRead, status_code=status.HTTP_201_CREATED)
def create_recording_session(payload: RecordingSessionCreateRequest):
    try:
        return FirebaseRecordingService().create_session(
            entry_date=payload.date,
            caregiver_id=payload.caregiverId,
            child_id=payload.childId,
            chunk_format=payload.chunkFormat,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=RecordingSessionRead)
def get_recording_session(session_id: str):
    session = FirebaseRecordingService().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Recording session not found")
    return session


@router.post("/sessions/{session_id}/perf")
def upload_recording_perf(session_id: str, payload: RecordingPerfBatch):
    if not get_settings().recording_perf_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    session = FirebaseRecordingService().get_session(session_id)
    if not session or session.get("chunkFormat") != "standalone":
        raise HTTPException(status_code=404, detail="Recording session not found")
    if len({event.recordingId for event in payload.events}) != 1:
        raise HTTPException(status_code=400, detail="Mixed recording IDs")
    ref = get_rtdb_reference(f"recordingDiagnostics/{session_id}")
    ref.update({f"event_{event.seq:05d}": event.model_dump(mode="json", exclude_none=True)
                for event in payload.events})
    return {"accepted": len(payload.events)}


@router.post("/sessions/{session_id}/chunks", response_model=RecordingChunkUploadResponse)
async def upload_recording_chunk(
    session_id: str,
    request: Request,
    chunkIndex: int = Query(..., ge=0),
    mimeType: str = Query(...),
):
    service = FirebaseRecordingService()
    try:
        parts = []
        size = 0
        async for part in request.stream():
            size += len(part)
            if size > MAX_CHUNK_BYTES:
                raise HTTPException(status_code=413, detail="Audio chunk is too large")
            parts.append(part)
        blob = b"".join(parts)
        if not blob:
            raise HTTPException(status_code=400, detail="Chunk body is required")
        return await run_in_threadpool(service.upload_chunk,
            session_id=session_id,
            chunk_index=chunkIndex,
            mime_type=mimeType,
            blob=blob,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Recording session not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/complete", response_model=RecordingSessionRead)
def complete_recording_session(session_id: str, payload: RecordingSessionCompleteRequest, background_tasks: BackgroundTasks):
    service = FirebaseRecordingService()
    try:
        completed = service.complete_session(
            session_id=session_id,
            final_chunk_index=payload.finalChunkIndex,
            duration_seconds=payload.durationSeconds,
        )
        background_tasks.add_task(_merge_completed_session, session_id)
        return completed
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Recording session not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/cancel", response_model=RecordingSessionRead)
def cancel_recording_session(session_id: str, payload: RecordingSessionCancelRequest):
    try:
        return FirebaseRecordingService().cancel_session(session_id, payload.caregiverId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Recording session not found") from None
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _merge_completed_session(session_id: str) -> None:
    try:
        RecordingMergeService().merge_session(session_id)
    except Exception:
        logger.exception("Recording merge failed for %s; source chunks retained", session_id)
