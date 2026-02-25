from datetime import date, datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference


class FirebaseNotificationStateService:
    def __init__(self):
        self.settings = get_settings()
        self.root = "notificationState"
        if self.settings.firebase_database_url:
            self.root = "notificationState"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _next_id(self, key: str) -> int:
        ref = get_rtdb_reference(f"{self.root}/_meta/{key}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")

        def _inc(value):
            value = int(value or 0)
            return value + 1

        next_value = ref.transaction(_inc)
        return int(next_value)

    def _iter_keyed_items(self, data: Any):
        if isinstance(data, dict):
            for key, value in data.items():
                yield str(key), value
            return
        if isinstance(data, list):
            for idx, value in enumerate(data):
                if value is None:
                    continue
                yield str(idx), value

    def get_reminder(self, caregiver_id: int) -> dict[str, Any] | None:
        ref = get_rtdb_reference(f"{self.root}/reminderSettings/{caregiver_id}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        return ref.get()

    def upsert_reminder(self, caregiver_id: int, timezone_name: str, reminder_times: list[str], enabled: bool) -> dict[str, Any]:
        existing = self.get_reminder(caregiver_id)
        now = self._now_iso()
        payload = {
            "caregiverId": caregiver_id,
            "timezone": timezone_name,
            "reminderTimes": reminder_times,
            "enabled": bool(enabled),
            "updatedAt": now,
        }
        if not existing:
            payload["createdAt"] = now
        else:
            payload["createdAt"] = existing.get("createdAt", now)

        ref = get_rtdb_reference(f"{self.root}/reminderSettings/{caregiver_id}")
        ref.set(payload)
        return payload

    def list_enabled_reminders(self) -> list[dict[str, Any]]:
        ref = get_rtdb_reference(f"{self.root}/reminderSettings")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        data = ref.get() or {}
        result: list[dict[str, Any]] = []
        for _, value in self._iter_keyed_items(data):
            if isinstance(value, dict) and value.get("enabled") is True:
                result.append(value)
        return result

    def list_subscriptions(self, caregiver_id: int) -> list[dict[str, Any]]:
        ref = get_rtdb_reference(f"{self.root}/subscriptions")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        data = ref.get() or {}
        result: list[dict[str, Any]] = []
        for key, value in self._iter_keyed_items(data):
            if not isinstance(value, dict):
                continue
            if int(value.get("caregiverId", -1)) == caregiver_id:
                value.setdefault("id", int(key) if str(key).isdigit() else value.get("id"))
                value.setdefault("createdAt", value.get("updatedAt", self._now_iso()))
                value.setdefault("updatedAt", value.get("createdAt", self._now_iso()))
                result.append(value)
        result.sort(key=lambda x: int(x.get("id", 0)))
        return result

    def list_active_subscriptions(self, caregiver_id: int) -> list[dict[str, Any]]:
        return [item for item in self.list_subscriptions(caregiver_id) if bool(item.get("active", True))]

    def find_subscription_by_identity(self, caregiver_id: int, platform: str, endpoint_or_token: str) -> dict[str, Any] | None:
        for item in self.list_subscriptions(caregiver_id):
            if item.get("platform") == platform and item.get("endpointOrToken") == endpoint_or_token:
                return item
        return None

    def upsert_subscription(self, caregiver_id: int, platform: str, endpoint_or_token: str, keys: dict[str, Any] | None) -> dict[str, Any]:
        now = self._now_iso()
        existing = self.find_subscription_by_identity(caregiver_id, platform, endpoint_or_token)
        if existing:
            subscription_id = int(existing["id"])
            payload = {
                "id": subscription_id,
                "caregiverId": caregiver_id,
                "platform": platform,
                "endpointOrToken": endpoint_or_token,
                "keys": keys,
                "active": True,
                "createdAt": existing.get("createdAt", now),
                "updatedAt": now,
            }
            get_rtdb_reference(f"{self.root}/subscriptions/{subscription_id}").set(payload)
            return payload

        subscription_id = self._next_id("nextSubscriptionId")
        payload = {
            "id": subscription_id,
            "caregiverId": caregiver_id,
            "platform": platform,
            "endpointOrToken": endpoint_or_token,
            "keys": keys,
            "active": True,
            "createdAt": now,
            "updatedAt": now,
        }
        get_rtdb_reference(f"{self.root}/subscriptions/{subscription_id}").set(payload)
        return payload

    def get_subscription(self, subscription_id: int) -> dict[str, Any] | None:
        ref = get_rtdb_reference(f"{self.root}/subscriptions/{subscription_id}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        data = ref.get()
        if isinstance(data, dict):
            data.setdefault("id", subscription_id)
            data.setdefault("createdAt", data.get("updatedAt", self._now_iso()))
            data.setdefault("updatedAt", data.get("createdAt", self._now_iso()))
        return data

    def update_subscription(self, subscription_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_subscription(subscription_id)
        if not existing:
            return None
        updated = {**existing, **patch, "id": subscription_id, "updatedAt": self._now_iso()}
        get_rtdb_reference(f"{self.root}/subscriptions/{subscription_id}").set(updated)
        return updated

    def deactivate_subscription(self, subscription_id: int) -> bool:
        existing = self.get_subscription(subscription_id)
        if not existing:
            return False
        existing["active"] = False
        existing["updatedAt"] = self._now_iso()
        get_rtdb_reference(f"{self.root}/subscriptions/{subscription_id}").set(existing)
        return True

    def check_dispatch_duplicate(self, caregiver_id: int, child_id: int, local_date: date, slot_time: str) -> int | None:
        unique_key = f"{caregiver_id}_{child_id}_{local_date.isoformat()}_{slot_time}"
        ref = get_rtdb_reference(f"{self.root}/dispatchIndex/{unique_key}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        value = ref.get()
        return int(value) if value is not None else None

    def _dispatch_log_exists(self, log_id: int) -> bool:
        ref = get_rtdb_reference(f"{self.root}/dispatchLogs/{log_id}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        return isinstance(ref.get(), dict)

    def create_dispatch_log(self, caregiver_id: int, child_id: int, local_date: date, slot_time: str, timezone_name: str, message: str) -> dict[str, Any]:
        unique_key = f"{caregiver_id}_{child_id}_{local_date.isoformat()}_{slot_time}"
        existing = self.check_dispatch_duplicate(caregiver_id, child_id, local_date, slot_time)
        if existing is not None:
            # Guard against orphaned dedupe index values (index exists but log node was removed).
            if self._dispatch_log_exists(existing):
                return {"duplicate": True, "id": existing}

        log_id = self._next_id("nextDispatchLogId")
        now = self._now_iso()
        payload = {
            "id": log_id,
            "caregiverId": caregiver_id,
            "childId": child_id,
            "localDate": local_date.isoformat(),
            "slotTime": slot_time,
            "timezone": timezone_name,
            "status": "pending",
            "deliveredCount": 0,
            "failedCount": 0,
            "message": message,
            "createdAt": now,
        }
        get_rtdb_reference(f"{self.root}/dispatchLogs/{log_id}").set(payload)
        get_rtdb_reference(f"{self.root}/dispatchIndex/{unique_key}").set(log_id)
        return payload

    def update_dispatch_log(self, log_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        ref = get_rtdb_reference(f"{self.root}/dispatchLogs/{log_id}")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        existing = ref.get()
        if not isinstance(existing, dict):
            return None
        updated = {**existing, **patch, "id": log_id}
        ref.set(updated)
        return updated

    def list_dispatch_logs(self, caregiver_id: int | None = None, local_date: date | None = None) -> list[dict[str, Any]]:
        ref = get_rtdb_reference(f"{self.root}/dispatchLogs")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        data = ref.get() or {}
        result: list[dict[str, Any]] = []
        for key, value in self._iter_keyed_items(data):
            if not isinstance(value, dict):
                continue
            value.setdefault("id", int(key) if str(key).isdigit() else value.get("id"))
            if caregiver_id is not None and int(value.get("caregiverId", -1)) != caregiver_id:
                continue
            if local_date is not None and value.get("localDate") != local_date.isoformat():
                continue
            result.append(value)
        result.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
        return result

    def create_delivery(self, log_id: int, subscription_id: int, platform: str, attempt_no: int, status: str, provider_message: str | None):
        delivery_id = self._next_id("nextDeliveryId")
        payload = {
            "id": delivery_id,
            "notificationLogId": log_id,
            "subscriptionId": subscription_id,
            "platform": platform,
            "attemptNo": attempt_no,
            "status": status,
            "providerMessage": provider_message,
            "createdAt": self._now_iso(),
        }
        get_rtdb_reference(f"{self.root}/deliveries/{delivery_id}").set(payload)
        return payload

    def list_deliveries(self, notification_log_id: int | None = None) -> list[dict[str, Any]]:
        ref = get_rtdb_reference(f"{self.root}/deliveries")
        if ref is None:
            raise RuntimeError("Firebase is not configured")
        data = ref.get() or {}
        result: list[dict[str, Any]] = []
        for key, value in self._iter_keyed_items(data):
            if not isinstance(value, dict):
                continue
            value.setdefault("id", int(key) if str(key).isdigit() else value.get("id"))
            if notification_log_id is not None and int(value.get("notificationLogId", -1)) != notification_log_id:
                continue
            result.append(value)
        result.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
        return result

    def metrics(self) -> dict[str, int]:
        logs = self.list_dispatch_logs()
        sent = sum(1 for x in logs if x.get("status") == "sent")
        partial = sum(1 for x in logs if x.get("status") == "partial")
        failed = sum(1 for x in logs if x.get("status") == "failed")
        no_subscription = sum(1 for x in logs if x.get("status") == "no_subscription")
        return {
            "total_logs": len(logs),
            "sent": sent,
            "partial": partial,
            "failed": failed,
            "no_subscription": no_subscription,
        }
