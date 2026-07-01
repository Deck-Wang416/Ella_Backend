from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.core.security import validate_internal_api_key
from app.schemas.internal import (
    RobotCurrentWeekResponse,
    RobotPhotoUploadResponse,
    RobotStoryCountIncrementRequest,
    RobotStoryCountIncrementResponse,
)
from app.services.daily_content_service import DailyContentService
from app.services.robot_identity_service import RobotIdentityService
from app.services.robot_photo_service import RobotPhotoService
from app.services.robot_story_progress_service import (
    RobotStoryProgressConflictError,
    RobotStoryProgressService,
)


router = APIRouter(prefix="/internal", tags=["internal-robot"])

def _increment_robot_story_count_impl(payload: RobotStoryCountIncrementRequest, response: Response):
    progress_service = RobotStoryProgressService()
    try:
        result = progress_service.increment_story_count(
            username=payload.username,
            event_id=payload.eventId,
            completed_at_raw=payload.completedAt,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown robot username") from None
    except RobotStoryProgressConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    caregiver_id = RobotIdentityService().resolve_caregiver_id(payload.username)
    if caregiver_id is None:
        raise HTTPException(status_code=404, detail="Unknown robot username") from None

    service = DailyContentService()
    service.upsert_robot_story_count(
        caregiver_id=caregiver_id,
        target_date=result.story_date,
        story_count=result.daily_story_count,
    )
    response.status_code = status.HTTP_201_CREATED if result.applied else status.HTTP_200_OK

    return RobotStoryCountIncrementResponse(
        ok=True,
        username=payload.username,
        eventId=payload.eventId,
        storyDate=result.story_date.isoformat(),
        dailyStoryCount=result.daily_story_count,
        weekNumber=result.week_number,
        weekStartDate=result.week_start.isoformat(),
        weekEndDate=result.week_end.isoformat(),
        weeklyStoryCount=result.weekly_story_count,
        applied=result.applied,
    )


@router.post(
    "/robot-story-count",
    response_model=RobotStoryCountIncrementResponse,
    dependencies=[Depends(validate_internal_api_key)],
)
def increment_robot_story_count_legacy(payload: RobotStoryCountIncrementRequest, response: Response):
    return _increment_robot_story_count_impl(payload, response)


@router.post(
    "/robot-story-count/increment",
    response_model=RobotStoryCountIncrementResponse,
    dependencies=[Depends(validate_internal_api_key)],
)
def increment_robot_story_count(payload: RobotStoryCountIncrementRequest, response: Response):
    return _increment_robot_story_count_impl(payload, response)


@router.get(
    "/robot-story-count/current-week",
    response_model=RobotCurrentWeekResponse,
    dependencies=[Depends(validate_internal_api_key)],
)
def get_robot_story_count_current_week(username: str):
    try:
        result = RobotStoryProgressService().get_current_week(username)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="DEPLOYMENT_NOT_FOUND") from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RobotCurrentWeekResponse(
        ok=True,
        username=result.username,
        weekNumber=result.week_number,
        weekStartDate=result.week_start.isoformat(),
        weekEndDate=result.week_end.isoformat(),
        storyCount=result.story_count,
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
