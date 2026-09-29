import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.firebase_client import get_rtdb_reference, get_storage_bucket
from merge_recording_chunks import run_ffmpeg_from_concatenated_bytes


CHUNK_NAME = re.compile(r"^chunk_(\d{6})\.([a-z0-9]+)$")
SESSION_ID = re.compile(r"^rec_\d{8}_[0-9a-f]{8}$")
SUPPORTED_MIME = {"audio/webm": "webm", "audio/mp4": "m4a"}
LEASE_DURATION = timedelta(minutes=30)


class MergeAlreadyRunning(Exception):
    pass


def _probe_audio(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])):
        raise ValueError("Merged file has no audio stream")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("Merged audio has no duration")
    return duration


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RecordingMergeService:
    def __init__(self, bucket=None, sessions_root="recordingSessions"):
        self.bucket = bucket or get_storage_bucket()
        self.sessions_root = sessions_root

    def _session_ref(self, session_id):
        return get_rtdb_reference(f"{self.sessions_root}/{session_id}")

    def completed_ids(self):
        sessions = get_rtdb_reference(self.sessions_root).get() or {}
        return sorted(session_id for session_id, data in sessions.items()
                      if isinstance(data, dict) and data.get("status") == "completed")

    def retryable_ids(self, limit=2):
        sessions = get_rtdb_reference(self.sessions_root).get() or {}
        now = datetime.now(timezone.utc)
        result = []
        for session_id, data in sessions.items():
            if not isinstance(data, dict) or data.get("status") != "completed":
                continue
            state = data.get("mergeStatus")
            if state not in ("pending", "failed", "processing"):
                continue
            if int(data.get("mergeAttempts") or 0) >= 3:
                continue
            lease = data.get("mergeLeaseUntil")
            if state == "processing" and lease:
                try:
                    if datetime.fromisoformat(lease) > now:
                        continue
                except ValueError:
                    pass
            result.append(session_id)
            if len(result) >= limit:
                break
        return result

    def _claim(self, ref):
        token = uuid4().hex
        now = datetime.now(timezone.utc)

        def update(data):
            if not isinstance(data, dict) or data.get("status") != "completed":
                raise ValueError("Only completed recording sessions can be merged")
            lease = data.get("mergeLeaseUntil")
            if lease:
                try:
                    if datetime.fromisoformat(lease) > now:
                        raise MergeAlreadyRunning("Recording merge is already running")
                except ValueError:
                    pass
            data["mergeStatus"] = "processing"
            data["mergeLeaseUntil"] = (now + LEASE_DURATION).isoformat()
            data["mergeToken"] = token
            data["mergeAttempts"] = int(data.get("mergeAttempts") or 0) + 1
            data["mergeError"] = None
            return data

        return token, ref.transaction(update)

    def _finish(self, ref, token, updates):
        def update(data):
            if not isinstance(data, dict) or data.get("mergeToken") != token:
                raise MergeAlreadyRunning("Recording merge lease was replaced")
            data.update(updates)
            data["mergeToken"] = None
            data["mergeLeaseUntil"] = None
            return data

        ref.transaction(update)

    def merge_session(self, session_id: str) -> dict:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("Invalid session ID")
        ref = self._session_ref(session_id)
        token, session = self._claim(ref)
        try:
            return self._merge_claimed(ref, session, session_id, token)
        except Exception as exc:
            self._finish(ref, token, {"mergeStatus": "failed", "mergeError": str(exc)[:500]})
            raise

    def _merge_claimed(self, ref, session, session_id, token):
        prefix = session.get("storagePrefix")
        if not isinstance(prefix, str) or not prefix.startswith("audio/") or not prefix.endswith(f"/{session_id}/") or ".." in prefix:
            raise ValueError("Invalid recording storage prefix")
        mime = str(session.get("mimeType") or "").split(";", 1)[0].strip().lower()
        if mime not in SUPPORTED_MIME:
            raise ValueError(f"Unsupported recording mime type: {mime}")
        extension = SUPPORTED_MIME[mime]
        final_path = f"{prefix}recording.{extension}"
        final_blob = self.bucket.blob(final_path)
        # A previous attempt may have stored the final file and crashed during cleanup.
        stored = session.get("finalAudio")
        has_verified_record = isinstance(stored, dict) and stored.get("storagePath") == final_path and final_blob.exists()
        chunks = self._ordered_chunks(prefix, session, extension, allow_partial=has_verified_record)
        if has_verified_record:
            final_blob.reload()
            if final_blob.size != stored.get("sizeBytes"):
                raise ValueError("Stored final audio size does not match the verified record")
            with tempfile.TemporaryDirectory(prefix="ella-verify-") as directory:
                verified = Path(directory) / f"recording.{extension}"
                final_blob.download_to_filename(str(verified))
                if _sha256(verified) != stored.get("sha256"):
                    raise ValueError("Stored final audio checksum does not match")
                _probe_audio(verified)
            self._delete_chunks(chunks)
            self._finish(ref, token, {"mergeStatus": "completed", "mergeError": None})
            return stored

        if not chunks:
            raise ValueError("No source chunks and no verified final audio")

        with tempfile.TemporaryDirectory(prefix="ella-merge-") as directory:
            folder = Path(directory)
            local_chunks = []
            for index, chunk in enumerate(chunks):
                local = folder / f"chunk_{index:06d}.{chunk.name.rsplit('.', 1)[-1]}"
                chunk.download_to_filename(str(local))
                if local.stat().st_size != chunk.size or local.stat().st_size <= 0:
                    raise ValueError(f"Chunk {index} was not downloaded intact")
                local_chunks.append(local)

            merged = folder / f"recording.{extension}"
            run_ffmpeg_from_concatenated_bytes(local_chunks, merged, extension)
            local_duration = _probe_audio(merged)
            size = merged.stat().st_size
            checksum = _sha256(merged)
            final_blob.upload_from_filename(str(merged), content_type=mime)
            final_blob.reload()
            if final_blob.size != size:
                raise ValueError("Stored final audio size mismatch")
            verified = folder / f"verified.{extension}"
            final_blob.download_to_filename(str(verified))
            if _sha256(verified) != checksum or abs(_probe_audio(verified) - local_duration) > 1:
                raise ValueError("Stored final audio verification failed")

        record = {
            "storagePath": final_path,
            "mimeType": mime,
            "sizeBytes": size,
            "durationSeconds": local_duration,
            "sha256": checksum,
            "sourceChunkCount": len(chunks),
            "mergedAt": datetime.now(timezone.utc).isoformat(),
        }
        ref.update({"finalAudio": record})
        self._delete_chunks(chunks)
        self._finish(ref, token, {"mergeStatus": "completed", "mergeError": None})
        return record

    def _ordered_chunks(self, prefix: str, session: dict, extension: str, allow_partial=False):
        indexed = {}
        for blob in self.bucket.list_blobs(prefix=prefix):
            suffix = blob.name[len(prefix):]
            match = CHUNK_NAME.fullmatch(suffix)
            if not match:
                continue
            index = int(match.group(1))
            if index in indexed:
                raise ValueError(f"Duplicate chunk index {index}")
            if extension == "webm" and match.group(2) not in ("bin", "webm"):
                raise ValueError("Unexpected WebM chunk extension")
            if extension == "m4a" and match.group(2) not in ("bin", "m4a", "mp4"):
                raise ValueError("Unexpected MP4 chunk extension")
            indexed[index] = blob
        if not indexed:
            return []
        if allow_partial:
            return [indexed[index] for index in sorted(indexed)]
        expected_final = int(session.get("lastChunkIndex", -1))
        if expected_final < 0 or sorted(indexed) != list(range(expected_final + 1)):
            raise ValueError("Recording chunks are incomplete or out of range")
        received = session.get("receivedChunkIndexes")
        if received is not None:
            if isinstance(received, dict):
                acknowledged = {int(key) for key, value in received.items() if value}
            elif isinstance(received, list):
                acknowledged = {index for index, value in enumerate(received) if value} if all(isinstance(value, bool) for value in received) else {int(value) for value in received}
            else:
                raise ValueError("Invalid recorded chunk acknowledgements")
            if acknowledged != set(indexed):
                raise ValueError("Storage chunks do not match the session acknowledgements")
        return [indexed[index] for index in sorted(indexed)]

    def _delete_chunks(self, chunks):
        for chunk in chunks:
            chunk.delete(if_generation_match=chunk.generation)
