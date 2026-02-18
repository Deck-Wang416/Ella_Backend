from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def validate_internal_api_key(x_internal_api_key: str | None = Header(default=None)):
    settings = get_settings()
    if not settings.internal_api_key:
        return
    if x_internal_api_key != settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )
