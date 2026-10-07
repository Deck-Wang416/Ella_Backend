import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.notification_providers import ApnsProvider, FcmProvider
from app.services.firebase_notification_state_service import FirebaseNotificationStateService


class MobileNotificationProviderTests(unittest.TestCase):
    def test_same_device_token_deactivates_other_caregiver(self):
        with patch("app.services.firebase_notification_state_service.get_settings",
                   return_value=SimpleNamespace(firebase_database_url="")):
            state = FirebaseNotificationStateService()
        root = MagicMock()
        root.get.return_value = {
            "4": {"caregiverId": 1, "platform": "apns", "endpointOrToken": "shared", "active": True},
            "5": {"caregiverId": 2, "platform": "apns", "endpointOrToken": "shared", "active": True},
        }
        with patch("app.services.firebase_notification_state_service.get_rtdb_reference", return_value=root), \
             patch.object(state, "deactivate_subscription") as deactivate:
            state._deactivate_other_bindings(2, "apns", "shared", 5)
        deactivate.assert_called_once_with(4)

    def test_fcm_sends_a_visible_diary_reminder(self):
        settings = SimpleNamespace(mobile_push_dry_run=False)
        with patch("app.services.notification_providers.get_settings", return_value=settings), \
             patch("app.services.notification_providers.get_firebase_app", return_value=object()), \
             patch("firebase_admin.messaging.send") as send:
            result = FcmProvider().send(
                SimpleNamespace(endpoint_or_token="device-token"), {"message": "Complete today's diary"}
            )
        self.assertTrue(result.success)
        message = send.call_args.args[0]
        self.assertEqual(message.token, "device-token")
        self.assertEqual(message.notification.title, "Diary Reminder")
        self.assertEqual(message.notification.body, "Complete today's diary")

    def test_apns_uses_http2_sandbox_and_alert_payload(self):
        settings = SimpleNamespace(
            mobile_push_dry_run=False, apns_team_id="TEAM", apns_key_id="KEY",
            apns_private_key="private", apns_bundle_id="com.ella.parentportal", apns_use_sandbox=True,
        )
        client = MagicMock()
        client.post.return_value.status_code = 200
        client_context = MagicMock()
        client_context.__enter__.return_value = client
        token = "a" * 64
        with patch("app.services.notification_providers.get_settings", return_value=settings), \
             patch("jwt.encode", return_value="signed"), \
             patch("httpx.Client", return_value=client_context) as client_class:
            result = ApnsProvider().send(
                SimpleNamespace(endpoint_or_token=token), {"message": "Complete today's diary"}
            )
        self.assertTrue(result.success)
        self.assertTrue(client_class.call_args.kwargs["http2"])
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], f"https://api.sandbox.push.apple.com/3/device/{token}")
        self.assertEqual(kwargs["headers"]["apns-topic"], "com.ella.parentportal")
        self.assertEqual(kwargs["json"]["aps"]["alert"]["body"], "Complete today's diary")

    def test_apns_requires_configuration(self):
        settings = SimpleNamespace(
            mobile_push_dry_run=False, apns_team_id="", apns_key_id="",
            apns_private_key="", apns_bundle_id="com.ella.parentportal",
        )
        with patch("app.services.notification_providers.get_settings", return_value=settings):
            result = ApnsProvider().send(SimpleNamespace(endpoint_or_token="a" * 64), {})
        self.assertFalse(result.success)
        self.assertEqual(result.message, "missing APNs config")


if __name__ == "__main__":
    unittest.main()
