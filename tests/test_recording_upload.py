import copy
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from google.api_core.exceptions import PreconditionFailed
from starlette.requests import Request

from app.api.recordings import upload_recording_chunk
from app.services.firebase_recording_service import FirebaseRecordingService


class FakeRef:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def get(self):
        return copy.deepcopy(self.value)

    def transaction(self, callback):
        self.value = callback(copy.deepcopy(self.value))
        return copy.deepcopy(self.value)


class FakeBlob:
    def __init__(self, bucket=None, path=None):
        self.bucket = bucket
        self.path = path
        self.data = None
        self.generation = 1
        self.fail_delete_once = False

    def upload_from_string(self, data, content_type, if_generation_match):
        assert if_generation_match == 0
        if self.data is not None:
            raise PreconditionFailed("already exists")
        self.data = data

    def reload(self):
        return None

    def download_as_bytes(self):
        return self.data

    def delete(self, if_generation_match):
        assert if_generation_match == self.generation
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("Storage unavailable")
        del self.bucket.blobs[self.path]


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, path):
        return self.blobs.setdefault(path, FakeBlob(self, path))

    def list_blobs(self, prefix):
        return [blob for path, blob in list(self.blobs.items()) if path.startswith(prefix)]


class RecordingUploadTests(unittest.TestCase):
    def setUp(self):
        self.session_id = "rec_20260929_abcdef12"
        self.ref = FakeRef({
            "status": "recording",
            "storagePrefix": f"audio/test/2026-09-29/{self.session_id}/",
            "receivedChunkIndexes": {},
        })
        self.bucket = FakeBucket()
        self.service = FirebaseRecordingService.__new__(FirebaseRecordingService)
        self.service.sessions_root = "recordingSessions"
        self.patches = [
            patch("app.services.firebase_recording_service.get_rtdb_reference", return_value=self.ref),
            patch("app.services.firebase_recording_service.get_storage_bucket", return_value=self.bucket),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_same_chunk_retry_is_idempotent(self):
        first = self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"audio")
        second = self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"audio")
        self.assertEqual(first, second)
        self.assertEqual(self.ref.value["uploadedChunks"], 1)
        self.assertEqual(len(self.bucket.blobs), 1)

    def test_conflicting_retry_cannot_overwrite_audio(self):
        self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"first")
        with self.assertRaisesRegex(ValueError, "different audio"):
            self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"second")
        self.assertEqual(next(iter(self.bucket.blobs.values())).data, b"first")
        self.assertEqual(self.ref.value["uploadedChunks"], 1)

    def test_rtdb_numeric_key_arrays_allow_next_chunk_and_lost_ack_retry(self):
        self.ref.value["chunkFormat"] = "standalone"
        self.service.upload_chunk(self.session_id, 0, "audio/wav", b"first")
        # Firebase converts maps containing only numeric keys to JSON arrays.
        self.ref.value["receivedChunkIndexes"] = [True]
        self.ref.value["chunkSha256"] = [self.ref.value["chunkSha256"]["0"]]
        path = f"{self.ref.value['storagePrefix']}chunk_000001.wav"
        self.bucket.blob(path).data = b"second"  # Storage write succeeded before acknowledgement.

        result = self.service.upload_chunk(self.session_id, 1, "audio/wav", b"second")
        self.assertEqual(result["chunkIndex"], 1)
        self.assertEqual(self.ref.value["uploadedChunks"], 2)
        self.assertEqual(self.ref.value["lastChunkIndex"], 1)
        with self.assertRaisesRegex(ValueError, "different audio"):
            self.service.upload_chunk(self.session_id, 1, "audio/wav", b"changed")

    def test_acknowledgements_accumulate_and_legacy_suffix_is_preserved(self):
        self.service.upload_chunk(self.session_id, 0, "audio/webm;codecs=opus", b"first")
        self.service.upload_chunk(self.session_id, 1, "audio/webm;codecs=opus", b"second")
        self.assertEqual(self.ref.value["uploadedChunks"], 2)
        self.assertEqual(self.ref.value["lastChunkIndex"], 1)
        self.assertTrue(all(name.endswith(".bin") for name in self.bucket.blobs))

    def test_mixed_container_rejected(self):
        self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"first")
        with self.assertRaisesRegex(ValueError, "same audio MIME"):
            self.service.upload_chunk(self.session_id, 1, "audio/webm", b"second")
        self.assertEqual(len(self.bucket.blobs), 1)

    def test_standalone_wav_is_accepted_but_byte_stream_wav_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be standalone"):
            self.service.upload_chunk(self.session_id, 0, "audio/wav", b"wav")
        self.ref.value["chunkFormat"] = "standalone"
        self.service.upload_chunk(self.session_id, 0, "audio/wav", b"wav")
        self.assertTrue(next(iter(self.bucket.blobs)).endswith("chunk_000000.wav"))

    def test_oversized_request_is_rejected_before_storage(self):
        async def receive():
            return {"type": "http.request", "body": b"12345", "more_body": False}

        request = Request({"type": "http", "method": "POST", "headers": []}, receive)
        with patch("app.api.recordings.MAX_CHUNK_BYTES", 4), \
             patch("app.api.recordings.FirebaseRecordingService", return_value=self.service), \
             self.assertRaises(HTTPException) as error:
            asyncio.run(upload_recording_chunk(self.session_id, request, chunkIndex=0, mimeType="audio/mp4"))
        self.assertEqual(error.exception.status_code, 413)
        self.assertEqual(self.bucket.blobs, {})

    def test_explicit_cancel_removes_only_its_chunks_and_can_be_retried(self):
        self.ref.value["caregiverId"] = 1
        own_path = f"{self.ref.value['storagePrefix']}chunk_000000.m4a"
        other_path = "audio/other/2026-09-29/rec_other/chunk_000000.m4a"
        self.bucket.blob(own_path).data = b"audio"
        self.bucket.blob(other_path).data = b"keep"

        result = self.service.cancel_session(self.session_id, 1)
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn(own_path, self.bucket.blobs)
        self.assertIn(other_path, self.bucket.blobs)
        self.service.cancel_session(self.session_id, 1)

    def test_cancel_rejects_wrong_caregiver_and_completed_session(self):
        self.ref.value["caregiverId"] = 1
        with self.assertRaises(PermissionError):
            self.service.cancel_session(self.session_id, 2)
        self.ref.value["status"] = "completed"
        with self.assertRaises(PermissionError):
            self.service.cancel_session(self.session_id, 1)

    def test_failed_storage_cleanup_keeps_cancel_retryable(self):
        self.ref.value["caregiverId"] = 1
        path = f"{self.ref.value['storagePrefix']}chunk_000000.m4a"
        blob = self.bucket.blob(path)
        blob.data = b"audio"
        blob.fail_delete_once = True
        with self.assertRaisesRegex(RuntimeError, "Storage unavailable"):
            self.service.cancel_session(self.session_id, 1)
        self.assertEqual(self.ref.value["status"], "cancelled")
        self.service.cancel_session(self.session_id, 1)
        self.assertNotIn(path, self.bucket.blobs)

    def test_chunk_finishing_after_cancel_does_not_leave_a_blob(self):
        self.ref.value["caregiverId"] = 1
        def cancel_before_acknowledgement(callback):
            self.ref.value["status"] = "cancelled"
            return callback(copy.deepcopy(self.ref.value))
        self.ref.transaction = cancel_before_acknowledgement
        with self.assertRaisesRegex(ValueError, "not active"):
            self.service.upload_chunk(self.session_id, 0, "audio/mp4", b"audio")
        self.assertEqual(self.bucket.blobs, {})

    def test_cancelled_session_cannot_be_completed(self):
        self.ref.value.update({"caregiverId": 1, "uploadedChunks": 1,
                               "receivedChunkIndexes": {"0": True}})
        self.service.cancel_session(self.session_id, 1)
        with self.assertRaisesRegex(ValueError, "not active"):
            self.service.complete_session(self.session_id, 0, 3)


if __name__ == "__main__":
    unittest.main()
