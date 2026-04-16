from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


@lru_cache
def get_firebase_app():
    settings = get_settings()

    if not settings.firebase_database_url or not settings.firebase_credentials_path:
        return None

    cred_path = Path(settings.firebase_credentials_path)
    if not cred_path.exists():
        raise FileNotFoundError(f"Firebase credentials file not found: {cred_path}")

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as exc:
        raise RuntimeError("firebase-admin is not installed. Install dependencies first.") from exc

    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred = credentials.Certificate(str(cred_path))
    app_options = {"databaseURL": settings.firebase_database_url}
    if settings.firebase_storage_bucket:
        app_options["storageBucket"] = settings.firebase_storage_bucket

    try:
        return firebase_admin.initialize_app(cred, app_options)
    except ValueError:
        # Concurrent requests may race during first init on multithreaded workers.
        # If another request already initialized the default app, reuse it.
        return firebase_admin.get_app()


def get_rtdb_reference(path: str):
    app = get_firebase_app()
    if app is None:
        raise RuntimeError("Firebase is not configured. Set FIREBASE_DATABASE_URL and FIREBASE_CREDENTIALS_PATH.")

    from firebase_admin import db

    return db.reference(path, app=app)


def get_storage_bucket():
    app = get_firebase_app()
    if app is None:
        raise RuntimeError("Firebase is not configured. Set FIREBASE_DATABASE_URL and FIREBASE_CREDENTIALS_PATH.")

    try:
        from firebase_admin import storage
    except ImportError as exc:
        raise RuntimeError("firebase-admin storage support is unavailable. Install dependencies first.") from exc

    return storage.bucket(app=app)
