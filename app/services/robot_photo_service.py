from datetime import date
from uuid import uuid4

from app.core.firebase_client import get_storage_bucket


class RobotPhotoService:
    SUPPORTED_MIME_TYPES = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }

    def validate_mime_type(self, mime_type: str) -> str:
        normalized = (mime_type or "").strip().lower()
        if normalized not in self.SUPPORTED_MIME_TYPES:
            raise ValueError("Unsupported image type")
        return normalized

    def upload_photo(
        self,
        caregiver_id: int,
        entry_date: date,
        mime_type: str,
        blob: bytes,
    ) -> str:
        normalized_mime_type = self.validate_mime_type(mime_type)
        extension = self.SUPPORTED_MIME_TYPES[normalized_mime_type]
        object_id = uuid4().hex
        storage_path = f"robot_photos/{caregiver_id}/{entry_date.isoformat()}/{object_id}.{extension}"
        token = str(uuid4())

        bucket = get_storage_bucket()
        storage_blob = bucket.blob(storage_path)
        storage_blob.metadata = {"firebaseStorageDownloadTokens": token}
        storage_blob.upload_from_string(blob, content_type=normalized_mime_type)

        return (
            f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/"
            f"{storage_path.replace('/', '%2F')}?alt=media&token={token}"
        )
