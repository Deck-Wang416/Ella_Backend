from datetime import date, datetime, timezone
from uuid import uuid4

from app.core.firebase_client import get_rtdb_reference, get_storage_bucket


class FirebaseRecordingService:
    def __init__(self):
        self.sessions_root = "recordingSessions"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _build_storage_prefix(self, entry_date: date, session_id: str) -> str:
        return f"audio/{entry_date.isoformat()}/{session_id}/"

    def _daily_ref(self, entry_date: date):
        return get_rtdb_reference(f"dailyData/{entry_date.isoformat()}")

    def _session_ref(self, session_id: str):
        return get_rtdb_reference(f"{self.sessions_root}/{session_id}")

    def _read_daily_payload(self, entry_date: date) -> dict | None:
        payload = self._daily_ref(entry_date).get()
        return payload if isinstance(payload, dict) else None

    def ensure_parent_daily(self, entry_date: date) -> dict:
        payload = self._read_daily_payload(entry_date)
        if payload is None:
            payload = {
                "date": entry_date.isoformat(),
                "condition": "parent",
                "dashboard": {
                    "hasInteraction": False,
                    "photos": [],
                    "words": [],
                    "highlight": [],
                    "ask": [],
                },
                "diary": {
                    "submitted": False,
                    "submittedAt": None,
                    "updatedAt": None,
                    "instructions": [],
                    "questions": [],
                    "responses": {},
                },
                "parentAudio": {
                    "enabled": True,
                    "activeSession": None,
                },
            }
            self._daily_ref(entry_date).set(payload)
            return payload

        payload.setdefault("condition", "parent")
        payload.setdefault(
            "dashboard",
            {
                "hasInteraction": False,
                "photos": [],
                "words": [],
                "highlight": [],
                "ask": [],
            },
        )
        payload.setdefault(
            "diary",
            {
                "submitted": False,
                "submittedAt": None,
                "updatedAt": None,
                "instructions": [],
                "questions": [],
                "responses": {},
            },
        )
        payload.setdefault("parentAudio", {"enabled": True, "activeSession": None})
        payload["condition"] = "parent"
        payload["parentAudio"]["enabled"] = True
        self._daily_ref(entry_date).set(payload)
        return payload

    def create_session(self, entry_date: date, caregiver_id: int, child_id: int) -> dict:
        self.ensure_parent_daily(entry_date)

        active_session_id = self.get_active_session_id_for_date(entry_date)
        if active_session_id is not None:
            existing_session = self.get_session(active_session_id)
            if existing_session is not None:
                return existing_session

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
        self._set_daily_active_session(entry_date, payload)
        return payload

    def get_session(self, session_id: str) -> dict | None:
        data = self._session_ref(session_id).get()
        return data if isinstance(data, dict) else None

    def get_active_session_for_date(self, entry_date: date) -> dict | None:
        daily = self._read_daily_payload(entry_date)
        if not daily:
            return None
        parent_audio = daily.get("parentAudio")
        if not isinstance(parent_audio, dict):
            return None
        active_session = parent_audio.get("activeSession")
        return active_session if isinstance(active_session, dict) else None

    def get_active_session_id_for_date(self, entry_date: date) -> str | None:
        active_session = self.get_active_session_for_date(entry_date)
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

        received = session.get("receivedChunkIndexes") or {}
        received[str(chunk_index)] = True
        session["receivedChunkIndexes"] = received
        session["mimeType"] = mime_type
        session["uploadedChunks"] = len(received)
        session["lastChunkIndex"] = max(int(i) for i in received.keys())
        session["updatedAt"] = self._now_iso()
        self._session_ref(session_id).set(session)

        entry_date = date.fromisoformat(session["date"])
        self._set_daily_active_session(entry_date, session)

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
        daily = self.ensure_parent_daily(entry_date)
        parent_audio = daily.setdefault("parentAudio", {"enabled": True, "activeSession": None})
        parent_audio["enabled"] = True
        parent_audio["activeSession"] = None
        self._daily_ref(entry_date).set(daily)
        return session

    def build_parent_audio_meta(self, entry_date: date, condition: str) -> dict | None:
        if condition != "parent":
            return None
        active_session = self.get_active_session_for_date(entry_date)
        return {
            "enabled": True,
            "activeSession": active_session,
        }

    def _set_daily_active_session(self, entry_date: date, session: dict) -> None:
        daily = self.ensure_parent_daily(entry_date)
        parent_audio = daily.setdefault("parentAudio", {"enabled": True, "activeSession": None})
        parent_audio["enabled"] = True
        parent_audio["activeSession"] = {
            "sessionId": session["sessionId"],
            "status": session["status"],
            "uploadedChunks": session["uploadedChunks"],
            "lastChunkIndex": session["lastChunkIndex"],
        }
        self._daily_ref(entry_date).set(daily)

    def _guess_extension(self, mime_type: str) -> str:
        mapping = {
            "audio/webm": "webm",
            "audio/mp4": "m4a",
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
            "audio/ogg": "ogg",
        }
        return mapping.get(mime_type, "bin")
