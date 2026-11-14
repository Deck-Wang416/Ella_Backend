import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.recordings import RecordingPerfBatch, upload_recording_perf


class FakeRef:
    def __init__(self):
        self.events = {}

    def update(self, events):
        self.events.update(events)


class RecordingPerfTests(unittest.TestCase):
    def setUp(self):
        self.ref = FakeRef()
        self.payload = RecordingPerfBatch(events=[{
            "seq": 0,
            "name": "chunk confirmed",
            "at": datetime.now(timezone.utc),
            "recordingId": "test-recording",
            "chunkIndex": 0,
            "sizeBytes": 292096,
            "requestMs": 1450,
        }])

    def test_accepted_events_are_idempotently_keyed(self):
        with patch("app.api.recordings.get_settings", return_value=SimpleNamespace(recording_perf_enabled=True)), \
             patch("app.api.recordings.FirebaseRecordingService") as service, \
             patch("app.api.recordings.get_rtdb_reference", return_value=self.ref):
            service.return_value.get_session.return_value = {"chunkFormat": "standalone"}
            self.assertEqual(upload_recording_perf("rec_test", self.payload), {"accepted": 1})
            self.assertEqual(upload_recording_perf("rec_test", self.payload), {"accepted": 1})
        self.assertEqual(len(self.ref.events), 1)
        self.assertEqual(self.ref.events["event_00000"]["requestMs"], 1450)

    def test_disabled_by_default(self):
        with patch("app.api.recordings.get_settings", return_value=SimpleNamespace(recording_perf_enabled=False)):
            with self.assertRaises(HTTPException) as error:
                upload_recording_perf("rec_test", self.payload)
        self.assertEqual(error.exception.status_code, 404)

    def test_rejects_raw_or_unknown_fields(self):
        with self.assertRaises(ValidationError):
            RecordingPerfBatch(events=[{
                "seq": 0, "name": "chunk confirmed", "at": datetime.now(timezone.utc),
                "recordingId": "test-recording", "base64": "audio content",
            }])
