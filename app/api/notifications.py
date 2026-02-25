from datetime import date

from fastapi import APIRouter, Depends

from app.core.security import validate_internal_api_key
from app.schemas.delivery import NotificationDeliveryRead
from app.schemas.notification import NotificationLogRead
from app.schemas.notification_internal import InternalTestSendRequest, InternalTestSendResult, NotificationMetrics
from app.services.firebase_notification_state_service import FirebaseNotificationStateService
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/internal/notifications", tags=["internal-notifications"])


@router.get("/logs", response_model=list[NotificationLogRead], dependencies=[Depends(validate_internal_api_key)])
def list_notification_logs(caregiver_id: int | None = None, local_date: date | None = None):
    state = FirebaseNotificationStateService()
    logs = state.list_dispatch_logs(caregiver_id=caregiver_id, local_date=local_date)
    return [
        {
            "id": item["id"],
            "caregiver_id": item["caregiverId"],
            "child_id": item["childId"],
            "local_date": item["localDate"],
            "slot_time": item["slotTime"],
            "timezone": item.get("timezone", "UTC"),
            "status": item["status"],
            "delivered_count": int(item.get("deliveredCount", 0)),
            "failed_count": int(item.get("failedCount", 0)),
            "message": item.get("message"),
            "created_at": item["createdAt"],
        }
        for item in logs
    ]


@router.get("/deliveries", response_model=list[NotificationDeliveryRead], dependencies=[Depends(validate_internal_api_key)])
def list_notification_deliveries(notification_log_id: int | None = None):
    state = FirebaseNotificationStateService()
    deliveries = state.list_deliveries(notification_log_id=notification_log_id)
    return [
        {
            "id": item["id"],
            "notification_log_id": item["notificationLogId"],
            "subscription_id": item["subscriptionId"],
            "platform": item["platform"],
            "attempt_no": item["attemptNo"],
            "status": item["status"],
            "provider_message": item.get("providerMessage"),
            "created_at": item["createdAt"],
        }
        for item in deliveries
    ]


@router.post("/test-send", response_model=InternalTestSendResult, dependencies=[Depends(validate_internal_api_key)])
def test_send_notification(payload: InternalTestSendRequest):
    accepted = NotificationService().send_reminder(
        caregiver_id=payload.caregiver_id,
        child_id=payload.child_id,
        local_date=payload.local_date,
        slot_time=payload.slot_time,
        timezone=payload.timezone,
        message=payload.message,
    )
    return InternalTestSendResult(accepted=accepted)


@router.get("/metrics", response_model=NotificationMetrics, dependencies=[Depends(validate_internal_api_key)])
def notification_metrics():
    metrics = FirebaseNotificationStateService().metrics()
    return NotificationMetrics(
        total_logs=metrics["total_logs"],
        sent=metrics["sent"],
        partial=metrics["partial"],
        failed=metrics["failed"],
        no_subscription=metrics["no_subscription"],
    )
