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
    def __init__(self):
        self.data = None

    def upload_from_string(self, data, content_type, if_generation_match):
        assert if_generation_match == 0
        if self.data is not None:
            raise PreconditionFailed("already exists")
        self.data = data

    def reload(self):
        return None

    def download_as_bytes(self):
        return self.data


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, path):
        return self.blobs.setdefault(path, FakeBlob())


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


if __name__ == "__main__":
    unittest.main()
