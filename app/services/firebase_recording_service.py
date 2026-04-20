from datetime import date, datetime, timezone
from uuid import uuid4

from app.core.firebase_client import get_rtdb_reference, get_storage_bucket
from app.schemas.daily import DailyContent
from app.services.daily_content_service import DailyContentService


class FirebaseRecordingService:
    def __init__(self):
        self.sessions_root = "recordingSessions"
        self.daily_service = DailyContentService()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _build_storage_prefix(self, entry_date: date, session_id: str) -> str:
        return f"audio/{entry_date.isoformat()}/{session_id}/"

    def _session_ref(self, session_id: str):
        return get_rtdb_reference(f"{self.sessions_root}/{session_id}")

    def _get_existing_parent_daily(self, caregiver_id: int, entry_date: date) -> DailyContent:
        daily = self.daily_service.get_daily(caregiver_id, entry_date)
        if daily.condition != "parent":
            raise PermissionError("Recording session is only allowed when daily.condition is 'parent'")
        return daily

    def create_session(self, entry_date: date, caregiver_id: int, child_id: int) -> dict:
        self._get_existing_parent_daily(caregiver_id, entry_date)

        now = self._now_iso()
        session_id = f"rec_{entry_date.strftime('%Y%m%d')}_{uuid4().hex[:8]}"
        storage_prefix = self._build_storage_prefix(entry_date, session_id)
        payload = {
            "sessionId": session_id,
            "date": entry_date.isoformat(),
            "caregiverId": caregiver_id,
            "childId": child_id,
            "condition": "parent",
            "status": "recording",
            "mimeType": None,
            "uploadedChunks": 0,
            "lastChunkIndex": -1,
            "receivedChunkIndexes": {},
            "storagePrefix": storage_prefix,
            "createdAt": now,
            "updatedAt": now,
            "completedAt": None,
        }
        self._session_ref(session_id).set(payload)
        return payload

    def get_session(self, session_id: str) -> dict | None:
        data = self._session_ref(session_id).get()
        return data if isinstance(data, dict) else None

    def upload_chunk(self, session_id: str, chunk_index: int, mime_type: str, blob: bytes) -> dict:
        session = self.get_session(session_id)
        if session is None:
            raise FileNotFoundError(session_id)
        if session.get("status") != "recording":
            raise ValueError("Recording session is not active")

        extension = self._guess_extension(mime_type)
        storage_path = f"{session['storagePrefix']}chunk_{chunk_index:06d}.{extension}"
        bucket = get_storage_bucket()
        storage_blob = bucket.blob(storage_path)
        storage_blob.upload_from_string(blob, content_type=mime_type)

        received = self._normalize_received_chunk_indexes(session.get("receivedChunkIndexes"))
        received[str(chunk_index)] = True
        session["receivedChunkIndexes"] = received
        session["mimeType"] = mime_type
        session["uploadedChunks"] = len(received)
        session["lastChunkIndex"] = max(int(i) for i in received.keys())
        session["updatedAt"] = self._now_iso()
        self._session_ref(session_id).set(session)

        return {
            "sessionId": session_id,
            "chunkIndex": chunk_index,
            "status": "uploaded",
            "storagePath": storage_path,
            "uploadedChunks": session["uploadedChunks"],
            "lastChunkIndex": session["lastChunkIndex"],
        }

    def complete_session(self, session_id: str, final_chunk_index: int) -> dict:
        session = self.get_session(session_id)
        if session is None:
            raise FileNotFoundError(session_id)

        now = self._now_iso()
        session["status"] = "completed"
        session["lastChunkIndex"] = max(int(session.get("lastChunkIndex", -1)), final_chunk_index)
        session["updatedAt"] = now
        session["completedAt"] = now
        self._session_ref(session_id).set(session)
        return session

    def _normalize_received_chunk_indexes(self, received: object) -> dict[str, bool]:
        if isinstance(received, dict):
            normalized: dict[str, bool] = {}
            for key, value in received.items():
                try:
                    normalized[str(int(key))] = bool(value)
                except (TypeError, ValueError):
                    continue
            return normalized
        if isinstance(received, list):
            normalized: dict[str, bool] = {}
            # Some older payloads were stored as dense boolean arrays like [true, false, true].
            if all(isinstance(item, bool) for item in received):
                for index, present in enumerate(received):
                    if present:
                        normalized[str(index)] = True
                return normalized
            # Some payloads may contain explicit chunk indexes like [0, 1, 2].
            for item in received:
                try:
                    normalized[str(int(item))] = True
                except (TypeError, ValueError):
                    continue
            return normalized
        return {}

    def _guess_extension(self, mime_type: str) -> str:
        mapping = {
            "audio/webm": "webm",
            "audio/mp4": "m4a",
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
            "audio/ogg": "ogg",
        }
        return mapping.get(mime_type, "bin")
