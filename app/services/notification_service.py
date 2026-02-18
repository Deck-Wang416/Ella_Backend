import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_log import NotificationLog
from app.models.notification_subscription import NotificationSubscription
from app.services.notification_providers import get_provider

logger = logging.getLogger(__name__)


class NotificationService:
    """Dispatches reminders through available subscription channels with retries."""

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
            status="pending",
            message=message,
            delivered_count=0,
            failed_count=0,
        )
        db.add(log)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False

        subscriptions = db.scalars(
            select(NotificationSubscription).where(
                NotificationSubscription.caregiver_id == caregiver_id,
                NotificationSubscription.active.is_(True),
            )
        ).all()

        if not subscriptions:
            log.status = "no_subscription"
            db.commit()
            return True

        settings = get_settings()
        max_retries = max(1, settings.notification_max_retries)

        payload = {
            "type": "diary_reminder",
            "caregiver_id": caregiver_id,
            "child_id": child_id,
            "local_date": str(local_date),
            "slot_time": slot_time,
            "message": message,
        }

        for sub in subscriptions:
            provider = get_provider(sub.platform)
            if provider is None:
                db.add(
                    NotificationDelivery(
                        notification_log_id=log.id,
                        subscription_id=sub.id,
                        platform=sub.platform,
                        attempt_no=1,
                        status="provider_missing",
                        provider_message=f"unsupported platform: {sub.platform}",
                    )
                )
                log.failed_count += 1
                continue

            delivered = False
            for attempt in range(1, max_retries + 1):
                result = provider.send(sub, payload)
                db.add(
                    NotificationDelivery(
                        notification_log_id=log.id,
                        subscription_id=sub.id,
                        platform=sub.platform,
                        attempt_no=attempt,
                        status="success" if result.success else "failed",
                        provider_message=(result.message or "")[:255] or None,
                    )
                )
                if result.success:
                    delivered = True
                    break

            if delivered:
                log.delivered_count += 1
            else:
                log.failed_count += 1

        if log.delivered_count > 0 and log.failed_count == 0:
            log.status = "sent"
        elif log.delivered_count > 0 and log.failed_count > 0:
            log.status = "partial"
        else:
            log.status = "failed"

        db.commit()

        logger.info(
            "Reminder dispatch finished: caregiver=%s child=%s status=%s delivered=%s failed=%s",
            caregiver_id,
            child_id,
            log.status,
            log.delivered_count,
            log.failed_count,
        )
        return True
