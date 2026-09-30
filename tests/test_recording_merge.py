import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.recording import RecordingSessionCreateRequest, RecordingSessionRead
from app.services.recording_merge_service import RecordingMergeService


class FakeRef:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def get(self):
        return copy.deepcopy(self.value)

    def update(self, updates):
        self.value.update(copy.deepcopy(updates))

    def transaction(self, callback):
        self.value = copy.deepcopy(callback(copy.deepcopy(self.value)))
        return copy.deepcopy(self.value)


class FakeBlob:
    def __init__(self, bucket, name, data=b""):
        self.bucket = bucket
        self.name = name
        self.data = data
        self.content_type = "audio/webm;codecs=opus"
        self.generation = 1
        self.size = len(data)
        self.fail_delete_once = False

    def exists(self):
        return self.name in self.bucket.objects

    def reload(self):
        self.size = len(self.data)

    def download_to_filename(self, path):
        Path(path).write_bytes(self.data)

    def upload_from_filename(self, path, content_type=None):
        self.data = Path(path).read_bytes()
        self.content_type = content_type
        self.size = len(self.data)
        self.bucket.objects[self.name] = self

    def delete(self, if_generation_match):
        assert if_generation_match == self.generation
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("temporary Storage deletion failure")
        del self.bucket.objects[self.name]


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return self.objects.get(name) or FakeBlob(self, name)

    def list_blobs(self, prefix):
        return [blob for name, blob in self.objects.items() if name.startswith(prefix)]

    def add(self, name, data):
        self.objects[name] = FakeBlob(self, name, data)
        return self.objects[name]


class RecordingMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "tone.webm"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:a", "libopus", str(source),
            ], check=True)
            cls.audio = source.read_bytes()
            cls.standalone_segments = []
            cls.standalone_webm_segments = []
            cls.standalone_wav_segments = []
            for index, duration in enumerate((1.1, 1.4)):
                segment = Path(directory) / f"segment_{index}.m4a"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={440 + index * 110}:duration={duration}",
                    "-c:a", "aac", str(segment),
                ], check=True)
                cls.standalone_segments.append(segment.read_bytes())
                webm_segment = Path(directory) / f"segment_{index}.webm"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={440 + index * 110}:duration={duration}",
                    "-c:a", "libopus", str(webm_segment),
                ], check=True)
                cls.standalone_webm_segments.append(webm_segment.read_bytes())
                wav_segment = Path(directory) / f"segment_{index}.wav"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={440 + index * 110}:duration={duration}",
                    "-c:a", "pcm_s16le", str(wav_segment),
                ], check=True)
                cls.standalone_wav_segments.append(wav_segment.read_bytes())

    def setUp(self):
        self.session_id = "rec_20260929_abcdef12"
        self.prefix = f"audio/test/2026-09-29/{self.session_id}/"
        self.ref = FakeRef({
            "sessionId": self.session_id,
            "status": "completed",
            "storagePrefix": self.prefix,
            "mimeType": "audio/webm;codecs=opus",
            "lastChunkIndex": 2,
            "receivedChunkIndexes": {"0": True, "1": True, "2": True},
        })
        self.bucket = FakeBucket()
        size = len(self.audio) // 3
        self.chunks = [
            self.bucket.add(f"{self.prefix}chunk_{index:06d}.bin", self.audio[index * size:(index + 1) * size] if index < 2 else self.audio[index * size:])
            for index in range(3)
        ]
        self.service = RecordingMergeService(bucket=self.bucket)
        self.ref_patch = patch("app.services.recording_merge_service.get_rtdb_reference", return_value=self.ref)
        self.ref_patch.start()
        self.addCleanup(self.ref_patch.stop)

    def test_success_verifies_final_before_deleting_chunks(self):
        result = self.service.merge_session(self.session_id)
        self.assertEqual(result["storagePath"], f"{self.prefix}recording.webm")
        self.assertGreater(result["durationSeconds"], 1)
        self.assertEqual(self.ref.value["mergeStatus"], "completed")
        self.assertEqual(len(self.bucket.objects), 1)
        self.assertIn(result["storagePath"], self.bucket.objects)

    def test_missing_chunk_never_deletes_source(self):
        del self.bucket.objects[self.chunks[1].name]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.service.merge_session(self.session_id)
        self.assertEqual(len(self.bucket.objects), 2)
        self.assertNotIn("finalAudio", self.ref.value)

    def test_failed_cleanup_retries_from_verified_final(self):
        self.chunks[1].fail_delete_once = True
        with self.assertRaisesRegex(RuntimeError, "deletion failure"):
            self.service.merge_session(self.session_id)
        self.assertIn("finalAudio", self.ref.value)
        self.assertEqual(self.ref.value["mergeStatus"], "failed")
        self.assertEqual(len(self.bucket.objects), 3)

        self.service.merge_session(self.session_id)
        self.assertEqual(self.ref.value["mergeStatus"], "completed")
        self.assertEqual(len(self.bucket.objects), 1)

    def test_unfinished_session_is_not_merged(self):
        self.ref.value["status"] = "recording"
        with self.assertRaisesRegex(ValueError, "Only completed"):
            self.service.merge_session(self.session_id)
        self.assertEqual(len(self.bucket.objects), 3)

    def test_concurrent_merge_is_rejected(self):
        token, _ = self.service._claim(self.ref)
        with self.assertRaisesRegex(Exception, "already running"):
            self.service.merge_session(self.session_id)
        self.assertEqual(self.ref.value["mergeToken"], token)
        self.assertEqual(len(self.bucket.objects), 3)

    def test_standalone_segments_merge_and_cleanup(self):
        self.bucket.objects.clear()
        for index, data in enumerate(self.standalone_segments):
            self.bucket.add(f"{self.prefix}chunk_{index:06d}.m4a", data)
        self.ref.value.update({
            "chunkFormat": "standalone",
            "mimeType": "audio/mp4",
            "lastChunkIndex": 1,
            "receivedChunkIndexes": {"0": True, "1": True},
        })

        result = self.service.merge_session(self.session_id)
        self.assertEqual(result["storagePath"], f"{self.prefix}recording.m4a")
        self.assertAlmostEqual(result["durationSeconds"], 2.5, delta=0.25)
        self.assertEqual(self.ref.value["mergeStatus"], "completed")
        self.assertEqual(set(self.bucket.objects), {result["storagePath"]})

    def test_invalid_standalone_segment_retains_chunks(self):
        self.bucket.objects.clear()
        self.bucket.add(f"{self.prefix}chunk_000000.m4a", self.standalone_segments[0])
        self.bucket.add(f"{self.prefix}chunk_000001.m4a", b"not-audio")
        self.ref.value.update({
            "chunkFormat": "standalone",
            "mimeType": "audio/mp4",
            "lastChunkIndex": 1,
            "receivedChunkIndexes": {"0": True, "1": True},
        })

        with self.assertRaises(Exception):
            self.service.merge_session(self.session_id)
        self.assertEqual(self.ref.value["mergeStatus"], "failed")
        self.assertEqual(len(self.bucket.objects), 2)
        self.assertNotIn("finalAudio", self.ref.value)

    def test_standalone_webm_segments_merge_and_cleanup(self):
        self.bucket.objects.clear()
        for index, data in enumerate(self.standalone_webm_segments):
            self.bucket.add(f"{self.prefix}chunk_{index:06d}.webm", data)
        self.ref.value.update({
            "chunkFormat": "standalone",
            "mimeType": "audio/webm",
            "lastChunkIndex": 1,
            "receivedChunkIndexes": {"0": True, "1": True},
        })

        result = self.service.merge_session(self.session_id)
        self.assertEqual(result["storagePath"], f"{self.prefix}recording.webm")
        self.assertAlmostEqual(result["durationSeconds"], 2.5, delta=0.25)
        self.assertEqual(set(self.bucket.objects), {result["storagePath"]})

    def test_standalone_wav_segments_merge_to_m4a_and_cleanup(self):
        self.bucket.objects.clear()
        for index, data in enumerate(self.standalone_wav_segments):
            self.bucket.add(f"{self.prefix}chunk_{index:06d}.wav", data)
        self.ref.value.update({
            "chunkFormat": "standalone",
            "mimeType": "audio/wav",
            "lastChunkIndex": 1,
            "receivedChunkIndexes": {"0": True, "1": True},
        })
        result = self.service.merge_session(self.session_id)
        self.assertEqual(result["storagePath"], f"{self.prefix}recording.m4a")
        self.assertEqual(result["mimeType"], "audio/mp4")
        self.assertAlmostEqual(result["durationSeconds"], 2.5, delta=0.25)
        self.assertEqual(set(self.bucket.objects), {result["storagePath"]})

    def test_legacy_create_contract_defaults_to_byte_stream(self):
        request = RecordingSessionCreateRequest(date="2026-09-29", caregiverId=1, childId=1)
        self.assertEqual(request.chunkFormat, "byte_stream")
        read = RecordingSessionRead.model_validate({
            "sessionId": self.session_id, "date": "2026-09-29", "caregiverId": 1, "childId": 1,
            "condition": "parent", "status": "recording", "uploadedChunks": 0,
            "lastChunkIndex": -1, "storagePrefix": self.prefix,
            "createdAt": "2026-09-29T00:00:00Z", "updatedAt": "2026-09-29T00:00:00Z",
        })
        self.assertEqual(read.chunkFormat, "byte_stream")


if __name__ == "__main__":
    unittest.main()
