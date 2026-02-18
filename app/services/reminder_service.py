from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.child import Child
from app.models.diary_entry import DiaryEntry
from app.models.reminder_setting import ReminderSetting
from app.services.notification_service import NotificationService


class ReminderRunner:
    def __init__(self, notification_service: NotificationService | None = None):
        self.notification_service = notification_service or NotificationService()

    def run_due(self, db: Session) -> tuple[int, int]:
        now_utc = datetime.now(timezone.utc)
        settings = db.scalars(select(ReminderSetting).where(ReminderSetting.enabled.is_(True))).all()

        checked_caregivers = 0
        triggered_notifications = 0

        for setting in settings:
            checked_caregivers += 1

            try:
                tz = ZoneInfo(setting.timezone)
            except ZoneInfoNotFoundError:
                tz = ZoneInfo("UTC")

            local_now = now_utc.astimezone(tz)
            local_today = local_now.date()
            current_hhmm = local_now.strftime("%H:%M")

            if current_hhmm not in (setting.reminder_times or []):
                continue

            children = db.scalars(select(Child).where(Child.caregiver_id == setting.caregiver_id)).all()
            for child in children:
                diary = db.scalar(
                    select(DiaryEntry).where(
                        DiaryEntry.child_id == child.id,
                        DiaryEntry.entry_date == local_today,
                    )
                )
                if diary and diary.submitted:
                    continue

                sent = self.notification_service.send_reminder(
                    db=db,
                    caregiver_id=setting.caregiver_id,
                    child_id=child.id,
                    local_date=local_today,
                    slot_time=current_hhmm,
                    timezone=setting.timezone,
                    message=f"Diary not submitted yet for {child.name}",
                )
                if sent:
                    triggered_notifications += 1

        return checked_caregivers, triggered_notifications
