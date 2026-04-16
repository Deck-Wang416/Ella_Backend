from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.recording import (
    RecordingChunkUploadResponse,
    RecordingSessionCompleteRequest,
    RecordingSessionCreateRequest,
    RecordingSessionRead,
)
from app.services.firebase_recording_service import FirebaseRecordingService

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.post("/sessions", response_model=RecordingSessionRead, status_code=status.HTTP_201_CREATED)
def create_recording_session(payload: RecordingSessionCreateRequest):
    try:
        return FirebaseRecordingService().create_session(
            entry_date=payload.date,
            caregiver_id=payload.caregiverId,
            child_id=payload.childId,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=RecordingSessionRead)
def get_recording_session(session_id: str):
    session = FirebaseRecordingService().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Recording session not found")
    return session


@router.post("/sessions/{session_id}/chunks", response_model=RecordingChunkUploadResponse)
async def upload_recording_chunk(
    session_id: str,
    request: Request,
    chunkIndex: int = Query(..., ge=0),
    mimeType: str = Query(...),
):
    service = FirebaseRecordingService()
    try:
        blob = await request.body()
        if not blob:
            raise HTTPException(status_code=400, detail="Chunk body is required")
        return service.upload_chunk(
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
def complete_recording_session(session_id: str, payload: RecordingSessionCompleteRequest):
    service = FirebaseRecordingService()
    try:
        return service.complete_session(
            session_id=session_id,
            final_chunk_index=payload.finalChunkIndex,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Recording session not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
