from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import validate_internal_api_key
from app.schemas.internal import RobotStoryCountUpsertRequest, RobotStoryCountUpsertResponse
from app.services.daily_content_service import DailyContentService
from app.services.robot_identity_service import RobotIdentityService


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
        username=payload.username,
        caregiverId=caregiver_id,
        date=daily.date,
        condition=daily.condition,
        storyCount=daily.dashboard.storyCount,
    )
