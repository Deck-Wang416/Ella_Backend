from dataclasses import dataclass
import json
import re
import time
from typing import Any

from app.core.config import get_settings
from app.core.firebase_client import get_firebase_app


@dataclass
class ProviderResult:
    success: bool
    message: str | None = None


class BaseNotificationProvider:
    platform = "base"

    def send(self, subscription: Any, payload: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError


class WebPushProvider(BaseNotificationProvider):
    platform = "web_push"

    def send(self, subscription: Any, payload: dict[str, Any]) -> ProviderResult:
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

    def send(self, subscription: Any, payload: dict[str, Any]) -> ProviderResult:
        settings = get_settings()
        if settings.mobile_push_dry_run:
            return ProviderResult(success=True, message="fcm dry-run success")
        try:
            from firebase_admin import messaging

            app = get_firebase_app()
            if app is None:
                return ProviderResult(success=False, message="Firebase is not configured")
            message = messaging.Message(
                token=subscription.endpoint_or_token,
                notification=messaging.Notification(
                    title="Diary Reminder",
                    body=payload.get("message") or "Please complete today's Parent Diary.",
                ),
                data={"type": "diary_reminder", "url": "/parent-diary"},
            )
            messaging.send(message, app=app)
            return ProviderResult(success=True, message="fcm accepted")
        except Exception as exc:
            return ProviderResult(success=False, message=f"fcm failed: {str(exc)[:200]}")


class ApnsProvider(BaseNotificationProvider):
    platform = "apns"

    def send(self, subscription: Any, payload: dict[str, Any]) -> ProviderResult:
        settings = get_settings()
        if settings.mobile_push_dry_run:
            return ProviderResult(success=True, message="apns dry-run success")
        if not all((settings.apns_team_id, settings.apns_key_id, settings.apns_private_key, settings.apns_bundle_id)):
            return ProviderResult(success=False, message="missing APNs config")
        token = subscription.endpoint_or_token or ""
        if not re.fullmatch(r"[0-9a-fA-F]{64,}", token):
            return ProviderResult(success=False, message="invalid APNs device token")
        try:
            import httpx
            import jwt

            provider_token = jwt.encode(
                {"iss": settings.apns_team_id, "iat": int(time.time())},
                settings.apns_private_key.replace("\\n", "\n"),
                algorithm="ES256",
                headers={"kid": settings.apns_key_id},
            )
            host = "api.sandbox.push.apple.com" if settings.apns_use_sandbox else "api.push.apple.com"
            headers = {
                "authorization": f"bearer {provider_token}",
                "apns-topic": settings.apns_bundle_id,
                "apns-push-type": "alert",
                "apns-priority": "10",
            }
            body = {"aps": {"alert": {
                "title": "Diary Reminder",
                "body": payload.get("message") or "Please complete today's Parent Diary.",
            }, "sound": "default"}, "type": "diary_reminder", "url": "/parent-diary"}
            with httpx.Client(http2=True, timeout=10.0) as client:
                response = client.post(f"https://{host}/3/device/{token}", headers=headers, json=body)
            if response.status_code == 200:
                return ProviderResult(success=True, message="apns accepted")
            reason = response.json().get("reason", "unknown") if response.content else "unknown"
            return ProviderResult(success=False, message=f"apns {response.status_code}: {str(reason)[:160]}")
        except Exception as exc:
            return ProviderResult(success=False, message=f"apns failed: {str(exc)[:200]}")


def get_provider(platform: str) -> BaseNotificationProvider | None:
    provider_map: dict[str, BaseNotificationProvider] = {
        "web_push": WebPushProvider(),
        "fcm": FcmProvider(),
        "apns": ApnsProvider(),
    }
    return provider_map.get(platform)
