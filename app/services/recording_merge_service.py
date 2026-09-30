import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.firebase_client import get_rtdb_reference, get_storage_bucket


CHUNK_NAME = re.compile(r"^chunk_(\d{6})\.([a-z0-9]+)$")
SESSION_ID = re.compile(r"^rec_\d{8}_[0-9a-f]{8}$")
SUPPORTED_MIME = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/wav": "wav"}
LEASE_DURATION = timedelta(minutes=30)


class MergeAlreadyRunning(Exception):
    pass


def _merge_mediarecorder_chunks(chunks: list[Path], output_path: Path, extension: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or not on PATH")

    # MediaRecorder chunks are slices of one stream, not standalone media files.
    with tempfile.TemporaryDirectory(prefix="ella-concat-") as directory:
        combined = Path(directory) / f"combined.{extension}"
        with combined.open("wb") as target:
            for chunk in chunks:
                with chunk.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

        remux = subprocess.run(
            [ffmpeg, "-y", "-i", str(combined), "-c", "copy", str(output_path)],
            capture_output=True, text=True,
        )
        if remux.returncode == 0:
            return

        codec = "aac" if extension == "m4a" else "libopus"
        transcode = subprocess.run(
            [ffmpeg, "-y", "-fflags", "+genpts", "-i", str(combined), "-c:a", codec, str(output_path)],
            capture_output=True, text=True,
        )
        if transcode.returncode != 0:
            raise RuntimeError(
                "ffmpeg could not merge recording chunks: "
                f"remux={remux.stderr[-1000:]} transcode={transcode.stderr[-1000:]}"
            )


def _merge_standalone_segments(chunks: list[Path], output_path: Path, extension: str) -> float:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or not on PATH")

    expected_signature = None
    total_duration = 0.0
    for chunk in chunks:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name,sample_rate,channels,time_base", "-of", "json", str(chunk)],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)
        audio = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
        if len(audio) != 1 or len(data.get("streams", [])) != 1:
            raise ValueError(f"Segment {chunk.name} must contain exactly one audio stream")
        duration = float(data.get("format", {}).get("duration") or 0)
        if duration <= 0:
            raise ValueError(f"Segment {chunk.name} has no duration")
        signature = tuple(audio[0].get(key) for key in ("codec_name", "sample_rate", "channels", "time_base"))
        if expected_signature is None:
            expected_signature = signature
        elif signature != expected_signature:
            raise ValueError("Recording segments must use the same codec, sample rate, channels, and time base")
        total_duration += duration

    # Only sealed, individually playable segments use the concat demuxer.
    manifest = chunks[0].parent / "segments.ffconcat"
    manifest.write_text("ffconcat version 1.0\n" + "".join(f"file {chunk.name}\n" for chunk in chunks))
    codec = "aac" if extension == "m4a" else "libopus"
    command = [ffmpeg, "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "1",
               "-i", str(manifest), "-map", "0:a:0", "-vn", "-c:a", codec, str(output_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg could not merge standalone segments: {result.stderr[-1500:]}")
    return total_duration


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
        chunk_format = session.get("chunkFormat", "byte_stream")
        if chunk_format not in ("byte_stream", "standalone"):
            raise ValueError(f"Unsupported recording chunk format: {chunk_format}")
        if mime == "audio/wav" and chunk_format != "standalone":
            raise ValueError("WAV chunks must be standalone")
        source_extension = SUPPORTED_MIME[mime]
        output_extension = "m4a" if mime == "audio/wav" else source_extension
        output_mime = "audio/mp4" if mime == "audio/wav" else mime
        final_path = f"{prefix}recording.{output_extension}"
        final_blob = self.bucket.blob(final_path)
        # A previous attempt may have stored the final file and crashed during cleanup.
        stored = session.get("finalAudio")
        has_verified_record = isinstance(stored, dict) and stored.get("storagePath") == final_path and final_blob.exists()
        chunks = self._ordered_chunks(prefix, session, source_extension, allow_partial=has_verified_record)
        if has_verified_record:
            final_blob.reload()
            if final_blob.size != stored.get("sizeBytes"):
                raise ValueError("Stored final audio size does not match the verified record")
            with tempfile.TemporaryDirectory(prefix="ella-verify-") as directory:
                verified = Path(directory) / f"recording.{output_extension}"
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

            merged = folder / f"recording.{output_extension}"
            expected_duration = None
            if chunk_format == "standalone":
                expected_duration = _merge_standalone_segments(local_chunks, merged, output_extension)
            else:
                _merge_mediarecorder_chunks(local_chunks, merged, source_extension)
            local_duration = _probe_audio(merged)
            if expected_duration is not None and abs(local_duration - expected_duration) > max(1.0, expected_duration * 0.02):
                raise ValueError("Merged audio duration does not match source segments")
            size = merged.stat().st_size
            checksum = _sha256(merged)
            final_blob.upload_from_filename(str(merged), content_type=output_mime)
            final_blob.reload()
            if final_blob.size != size:
                raise ValueError("Stored final audio size mismatch")
            verified = folder / f"verified.{output_extension}"
            final_blob.download_to_filename(str(verified))
            if _sha256(verified) != checksum or abs(_probe_audio(verified) - local_duration) > 1:
                raise ValueError("Stored final audio verification failed")

        record = {
            "storagePath": final_path,
            "mimeType": output_mime,
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
            if extension == "wav" and match.group(2) != "wav":
                raise ValueError("Unexpected WAV chunk extension")
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
