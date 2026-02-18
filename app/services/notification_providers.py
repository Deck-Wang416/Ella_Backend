from dataclasses import dataclass
import json
from typing import Any

from app.core.config import get_settings
from app.models.notification_subscription import NotificationSubscription


@dataclass
class ProviderResult:
    success: bool
    message: str | None = None


class BaseNotificationProvider:
    platform = "base"

    def send(self, subscription: NotificationSubscription, payload: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError


class WebPushProvider(BaseNotificationProvider):
    platform = "web_push"

    def send(self, subscription: NotificationSubscription, payload: dict[str, Any]) -> ProviderResult:
        settings = get_settings()
        if settings.web_push_dry_run:
            return ProviderResult(success=True, message="web_push dry-run success")

        try:
            from pywebpush import WebPushException, webpush
        except Exception:
            return ProviderResult(success=False, message="pywebpush is not installed")

        vapid_private_key = settings.web_push_vapid_private_key
        vapid_claims_sub = settings.web_push_vapid_claims_sub
        if not vapid_private_key or not vapid_claims_sub:
            return ProviderResult(success=False, message="missing VAPID config")

        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint_or_token or subscription.endpoint,
                    "keys": subscription.keys or {},
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_claims_sub},
            )
            return ProviderResult(success=True, message="web_push delivered")
        except WebPushException as exc:
            return ProviderResult(success=False, message=f"web_push failed: {str(exc)[:200]}")


class FcmProvider(BaseNotificationProvider):
    platform = "fcm"

    def send(self, subscription: NotificationSubscription, payload: dict[str, Any]) -> ProviderResult:
        settings = get_settings()
        if settings.mobile_push_dry_run:
            return ProviderResult(success=True, message="fcm dry-run success")
        return ProviderResult(success=False, message="fcm provider not integrated yet")


class ApnsProvider(BaseNotificationProvider):
    platform = "apns"

    def send(self, subscription: NotificationSubscription, payload: dict[str, Any]) -> ProviderResult:
        settings = get_settings()
        if settings.mobile_push_dry_run:
            return ProviderResult(success=True, message="apns dry-run success")
        return ProviderResult(success=False, message="apns provider not integrated yet")


def get_provider(platform: str) -> BaseNotificationProvider | None:
    provider_map: dict[str, BaseNotificationProvider] = {
        "web_push": WebPushProvider(),
        "fcm": FcmProvider(),
        "apns": ApnsProvider(),
    }
    return provider_map.get(platform)
