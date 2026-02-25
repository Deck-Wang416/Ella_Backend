from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.daily_content_service import DailyContentService
from app.services.firebase_notification_state_service import FirebaseNotificationStateService
from app.services.notification_service import NotificationService


class ReminderRunner:
    def __init__(self, notification_service: NotificationService | None = None):
        self.notification_service = notification_service or NotificationService()
        self.daily_service = DailyContentService()
        self.notification_state = FirebaseNotificationStateService()

    def run_due(self) -> tuple[int, int]:
        now_utc = datetime.now(timezone.utc)
        settings = self.notification_state.list_enabled_reminders()

        checked_caregivers = 0
        triggered_notifications = 0

        for setting in settings:
            checked_caregivers += 1

            timezone_name = setting.get("timezone", "UTC")
            reminder_times = setting.get("reminderTimes", [])
            caregiver_id = int(setting.get("caregiverId", 0))
            if caregiver_id <= 0:
                continue

            try:
                tz = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                tz = ZoneInfo("UTC")

            local_now = now_utc.astimezone(tz)
            local_today = local_now.date()
            current_hhmm = local_now.strftime("%H:%M")

            if current_hhmm not in reminder_times:
                continue

            # Child tables are deprecated in single-user mode; keep a stable child_id for dedupe key.
            child_id = 1
            child_name = "Child"
            if self.daily_service.is_submitted(local_today):
                continue

            sent = self.notification_service.send_reminder(
                caregiver_id=caregiver_id,
                child_id=child_id,
                local_date=local_today,
                slot_time=current_hhmm,
                timezone=timezone_name,
                message=f"Diary not submitted yet for {child_name}",
            )
            if sent:
                triggered_notifications += 1

        return checked_caregivers, triggered_notifications
