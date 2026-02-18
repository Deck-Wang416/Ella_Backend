from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.caregiver import Caregiver
from app.models.reminder_setting import ReminderSetting
from app.schemas.reminder import ReminderSettingRead, ReminderSettingUpdate

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/{caregiver_id}", response_model=ReminderSettingRead)
def get_reminder_settings(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    settings = db.query(ReminderSetting).filter(ReminderSetting.caregiver_id == caregiver_id).first()
    if not settings:
        settings = ReminderSetting(caregiver_id=caregiver_id, timezone=caregiver.timezone, reminder_times=["18:00", "21:00"], enabled=True)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


@router.put("/{caregiver_id}", response_model=ReminderSettingRead)
def update_reminder_settings(caregiver_id: int, payload: ReminderSettingUpdate, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    settings = db.query(ReminderSetting).filter(ReminderSetting.caregiver_id == caregiver_id).first()
    if not settings:
        settings = ReminderSetting(caregiver_id=caregiver_id)
        db.add(settings)

    settings.timezone = payload.timezone
    settings.reminder_times = payload.reminder_times
    settings.enabled = payload.enabled
    caregiver.timezone = payload.timezone

    db.commit()
    db.refresh(settings)
    return settings
