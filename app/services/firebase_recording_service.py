from datetime import date, datetime, timezone
from uuid import uuid4

from app.core.firebase_client import get_rtdb_reference, get_storage_bucket
from app.schemas.daily import DailyContent, ParentAudioMeta, ParentAudioSession
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

    def _get_existing_parent_daily(self, entry_date: date) -> DailyContent:
        daily = self.daily_service.get_daily(entry_date)
        if daily.condition != "parent":
            raise PermissionError("Recording session is only allowed when daily.condition is 'parent'")
        return daily

    def create_session(self, entry_date: date, caregiver_id: int, child_id: int) -> dict:
        daily = self._get_existing_parent_daily(entry_date)

        active_session_id = self.get_active_session_id_for_date(daily)
        if active_session_id is not None:
            existing_session = self.get_session(active_session_id)
            if existing_session is not None and existing_session.get("status") == "recording":
                return existing_session
            self._clear_daily_active_session(daily)
            self.daily_service._save_daily(entry_date, daily)

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
        self._set_daily_active_session(daily, payload)
        self.daily_service._save_daily(entry_date, daily)
        return payload

    def get_session(self, session_id: str) -> dict | None:
        data = self._session_ref(session_id).get()
        return data if isinstance(data, dict) else None

    def get_active_session_for_date(self, daily: DailyContent) -> dict | None:
        parent_audio = daily.parentAudio
        if parent_audio is None or parent_audio.activeSession is None:
            return None
        return parent_audio.activeSession.model_dump(mode="json")

    def get_active_session_id_for_date(self, daily: DailyContent) -> str | None:
        active_session = self.get_active_session_for_date(daily)
        if not active_session:
            return None
        session_id = active_session.get("sessionId")
        return session_id if isinstance(session_id, str) and session_id else None

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

        entry_date = date.fromisoformat(session["date"])
        daily = self._get_existing_parent_daily(entry_date)
        self._set_daily_active_session(daily, session)
        self.daily_service._save_daily(entry_date, daily)

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

        entry_date = date.fromisoformat(session["date"])
        daily = self._get_existing_parent_daily(entry_date)
        daily.parentAudio = ParentAudioMeta(enabled=True, activeSession=None)
        self.daily_service._save_daily(entry_date, daily)
        return session

    def build_parent_audio_meta(self, daily: DailyContent) -> ParentAudioMeta | None:
        if daily.condition != "parent":
            return None
        if daily.parentAudio is None:
            return ParentAudioMeta(enabled=True, activeSession=None)
        active_session_id = self.get_active_session_id_for_date(daily)
        if active_session_id is not None:
            session = self.get_session(active_session_id)
            if session is None or session.get("status") != "recording":
                self._clear_daily_active_session(daily)
                self.daily_service._save_daily(date.fromisoformat(daily.date), daily)
                return daily.parentAudio
        return daily.parentAudio

    def _set_daily_active_session(self, daily: DailyContent, session: dict) -> None:
        daily.parentAudio = ParentAudioMeta(
            enabled=True,
            activeSession=ParentAudioSession(
                sessionId=session["sessionId"],
                status=session["status"],
                uploadedChunks=session["uploadedChunks"],
                lastChunkIndex=session["lastChunkIndex"],
            ),
        )

    def _clear_daily_active_session(self, daily: DailyContent) -> None:
        daily.parentAudio = ParentAudioMeta(enabled=True, activeSession=None)

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
