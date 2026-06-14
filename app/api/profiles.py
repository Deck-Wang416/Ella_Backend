from fastapi import APIRouter, HTTPException

from app.schemas.profile import UserProfileContent, UserProfileLoginRequest, UserProfileUpdateRequest
from app.services.user_profile_service import UserProfileService

router = APIRouter(prefix="/profiles", tags=["profiles"])

@router.post("/login", response_model=UserProfileContent)
def login(payload: UserProfileLoginRequest):
    profile = UserProfileService().authenticate(
        username=payload.username,
        password=payload.password,
    )
    if profile is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return profile


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
        profile = service.update_themes(
            caregiver_id=caregiver_id,
            themes=payload.themes,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="User profile not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return profile
