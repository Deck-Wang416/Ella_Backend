import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification_log import NotificationLog

logger = logging.getLogger(__name__)


class NotificationService:
    """Placeholder notification sender; currently logs and stores dispatch records."""

    def send_reminder(
        self,
        db: Session,
        caregiver_id: int,
        child_id: int,
        local_date: date,
        slot_time: str,
        timezone: str,
        message: str,
    ) -> bool:
        existing = db.scalar(
            select(NotificationLog).where(
                NotificationLog.caregiver_id == caregiver_id,
                NotificationLog.child_id == child_id,
                NotificationLog.local_date == local_date,
                NotificationLog.slot_time == slot_time,
            )
        )
        if existing:
            return False

        log = NotificationLog(
            caregiver_id=caregiver_id,
            child_id=child_id,
            local_date=local_date,
            slot_time=slot_time,
            timezone=timezone,
            status="sent",
            message=message,
        )
        db.add(log)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False

        logger.info(
            "Reminder sent (placeholder): caregiver=%s child=%s date=%s slot=%s tz=%s",
            caregiver_id,
            child_id,
            local_date,
            slot_time,
            timezone,
        )
        return True
