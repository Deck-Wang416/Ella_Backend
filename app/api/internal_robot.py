from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import validate_internal_api_key
from app.schemas.internal import (
    RobotPhotoUploadResponse,
    RobotStoryCountUpsertRequest,
    RobotStoryCountUpsertResponse,
)
from app.services.daily_content_service import DailyContentService
from app.services.robot_identity_service import RobotIdentityService
from app.services.robot_photo_service import RobotPhotoService


router = APIRouter(prefix="/internal", tags=["internal-robot"])


@router.post(
    "/robot-story-count",
    response_model=RobotStoryCountUpsertResponse,
    dependencies=[Depends(validate_internal_api_key)],
    status_code=status.HTTP_200_OK,
)
def upsert_robot_story_count(payload: RobotStoryCountUpsertRequest):
    caregiver_id = RobotIdentityService().resolve_caregiver_id(payload.username)
    if caregiver_id is None:
        raise HTTPException(status_code=404, detail="Unknown robot username") from None

    try:
        target_date = date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date") from None

    service = DailyContentService()
    try:
        daily = service.upsert_robot_story_count(
            caregiver_id=caregiver_id,
            target_date=target_date,
            story_count=payload.storyCount,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RobotStoryCountUpsertResponse(
        ok=True,
        username=payload.username,
        date=daily.date,
        storyCount=daily.dashboard.storyCount,
    )


@router.post(
    "/robot-photo",
    response_model=RobotPhotoUploadResponse,
    dependencies=[Depends(validate_internal_api_key)],
    status_code=status.HTTP_200_OK,
)
async def upload_robot_photo(
    username: str = Form(...),
    entry_date_raw: str = Form(..., alias="date"),
    image: UploadFile = File(...),
):
    caregiver_id = RobotIdentityService().resolve_caregiver_id(username)
    if caregiver_id is None:
        raise HTTPException(status_code=404, detail="Unknown robot username") from None

    try:
        target_date = date.fromisoformat(entry_date_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date") from None

    mime_type = image.content_type or ""
    service = DailyContentService()
    try:
        service.ensure_robot_daily(
            caregiver_id=caregiver_id,
            target_date=target_date,
        )
        photo_blob = await image.read()
        if not photo_blob:
            raise HTTPException(status_code=400, detail="Image file is required") from None
        photo_url = RobotPhotoService().upload_photo(
            caregiver_id=caregiver_id,
            entry_date=target_date,
            mime_type=mime_type,
            blob=photo_blob,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        daily = service.append_robot_photo(
            caregiver_id=caregiver_id,
            target_date=target_date,
            photo_url=photo_url,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RobotPhotoUploadResponse(
        ok=True,
        username=username,
        date=daily.date,
        photoUrl=photo_url,
    )
