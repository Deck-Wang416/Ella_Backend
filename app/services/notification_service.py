import logging
from datetime import date
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.firebase_notification_state_service import FirebaseNotificationStateService
from app.services.notification_providers import get_provider

logger = logging.getLogger(__name__)


class NotificationService:
    """Dispatches reminders through available subscription channels with retries."""

    def send_reminder(
        self,
        caregiver_id: int,
        child_id: int,
        local_date: date,
        slot_time: str,
        timezone: str,
        message: str,
    ) -> bool:
        state = FirebaseNotificationStateService()
        created = state.create_dispatch_log(
            caregiver_id=caregiver_id,
            child_id=child_id,
            local_date=local_date,
            slot_time=slot_time,
            timezone_name=timezone,
            message=message,
        )
        if created.get("duplicate"):
            return False

        log_id = int(created["id"])
        subscriptions = state.list_active_subscriptions(caregiver_id)

        if not subscriptions:
            state.update_dispatch_log(log_id, {"status": "no_subscription"})
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
        delivered_count = 0
        failed_count = 0

        for sub in subscriptions:
            platform = sub.get("platform", "")
            provider = get_provider(platform)
            if provider is None:
                state.create_delivery(
                    log_id=log_id,
                    subscription_id=int(sub["id"]),
                    platform=platform,
                    attempt_no=1,
                    status="provider_missing",
                    provider_message=f"unsupported platform: {platform}",
                )
                failed_count += 1
                continue

            delivered = False
            sub_obj = SimpleNamespace(
                endpoint_or_token=sub.get("endpointOrToken"),
                endpoint=sub.get("endpointOrToken"),
                keys=sub.get("keys"),
                platform=platform,
            )
            for attempt in range(1, max_retries + 1):
                result = provider.send(sub_obj, payload)
                state.create_delivery(
                    log_id=log_id,
                    subscription_id=int(sub["id"]),
                    platform=platform,
                    attempt_no=attempt,
                    status="success" if result.success else "failed",
                    provider_message=(result.message or "")[:255] or None,
                )
                if result.success:
                    delivered = True
                    break

            if delivered:
                delivered_count += 1
            else:
                failed_count += 1

        if delivered_count > 0 and failed_count == 0:
            status = "sent"
        elif delivered_count > 0 and failed_count > 0:
            status = "partial"
        else:
            status = "failed"
        state.update_dispatch_log(
            log_id,
            {"status": status, "deliveredCount": delivered_count, "failedCount": failed_count},
        )

        logger.info(
            "Reminder dispatch finished: caregiver=%s child=%s status=%s delivered=%s failed=%s",
            caregiver_id,
            child_id,
            status,
            delivered_count,
            failed_count,
        )
        return True
