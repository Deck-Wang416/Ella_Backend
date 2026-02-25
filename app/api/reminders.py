from fastapi import APIRouter

from app.schemas.reminder import ReminderSettingRead, ReminderSettingUpdate
from app.services.firebase_notification_state_service import FirebaseNotificationStateService

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/{caregiver_id}", response_model=ReminderSettingRead)
def get_reminder_settings(caregiver_id: int):
    state = FirebaseNotificationStateService()
    settings = state.get_reminder(caregiver_id)
    if not settings:
        settings = state.upsert_reminder(caregiver_id=caregiver_id, timezone_name="UTC", reminder_times=["18:00", "21:00"], enabled=True)
    if "createdAt" not in settings:
        settings = state.upsert_reminder(
            caregiver_id=caregiver_id,
            timezone_name=settings.get("timezone", "UTC"),
            reminder_times=settings.get("reminderTimes", ["18:00", "21:00"]),
            enabled=bool(settings.get("enabled", True)),
        )

    return {
        "id": caregiver_id,
        "caregiver_id": settings["caregiverId"],
        "timezone": settings["timezone"],
        "reminder_times": settings["reminderTimes"],
        "enabled": settings["enabled"],
        "created_at": settings.get("createdAt"),
        "updated_at": settings.get("updatedAt"),
    }


@router.put("/{caregiver_id}", response_model=ReminderSettingRead)
def update_reminder_settings(caregiver_id: int, payload: ReminderSettingUpdate):
    state = FirebaseNotificationStateService()
    settings = state.upsert_reminder(
        caregiver_id=caregiver_id,
        timezone_name=payload.timezone,
        reminder_times=payload.reminder_times,
        enabled=payload.enabled,
    )
    return {
        "id": caregiver_id,
        "caregiver_id": settings["caregiverId"],
        "timezone": settings["timezone"],
        "reminder_times": settings["reminderTimes"],
        "enabled": settings["enabled"],
        "created_at": settings.get("createdAt"),
        "updated_at": settings.get("updatedAt"),
    }
