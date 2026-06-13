from fastapi import APIRouter, HTTPException

from app.schemas.profile import UserProfileContent, UserProfileUpdateRequest
from app.services.daily_content_service import DailyContentService
from app.services.user_profile_service import UserProfileService

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/{caregiver_id}", response_model=UserProfileContent)
def get_profile(caregiver_id: int):
    profile = UserProfileService().get_profile(caregiver_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile


@router.put("/{caregiver_id}", response_model=UserProfileContent)
def upsert_profile(caregiver_id: int, payload: UserProfileUpdateRequest):
    service = UserProfileService()
    try:
        profile = service.upsert_profile(
            caregiver_id=caregiver_id,
            username=payload.username,
            themes=payload.themes,
            robot_condition_range=payload.robot_condition_range,
            parent_condition_range=payload.parent_condition_range,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Materialize all scheduled daily files immediately after profile update.
    daily_service = DailyContentService()
    for scheduled_date in service.list_scheduled_dates(caregiver_id):
        daily_service.get_daily(caregiver_id, scheduled_date)

    return profile
