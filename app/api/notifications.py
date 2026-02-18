from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import validate_internal_api_key
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_log import NotificationLog
from app.schemas.delivery import NotificationDeliveryRead
from app.schemas.notification import NotificationLogRead
from app.schemas.notification_internal import InternalTestSendRequest, InternalTestSendResult, NotificationMetrics
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/internal/notifications", tags=["internal-notifications"])


@router.get("/logs", response_model=list[NotificationLogRead], dependencies=[Depends(validate_internal_api_key)])
def list_notification_logs(caregiver_id: int | None = None, local_date: date | None = None, db: Session = Depends(get_db)):
    stmt = select(NotificationLog).order_by(NotificationLog.created_at.desc())
    if caregiver_id is not None:
        stmt = stmt.where(NotificationLog.caregiver_id == caregiver_id)
    if local_date is not None:
        stmt = stmt.where(NotificationLog.local_date == local_date)
    logs = db.scalars(stmt).all()
    return list(logs)


@router.get("/deliveries", response_model=list[NotificationDeliveryRead], dependencies=[Depends(validate_internal_api_key)])
def list_notification_deliveries(notification_log_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc())
    if notification_log_id is not None:
        stmt = stmt.where(NotificationDelivery.notification_log_id == notification_log_id)
    deliveries = db.scalars(stmt).all()
    return list(deliveries)


@router.post("/test-send", response_model=InternalTestSendResult, dependencies=[Depends(validate_internal_api_key)])
def test_send_notification(payload: InternalTestSendRequest, db: Session = Depends(get_db)):
    accepted = NotificationService().send_reminder(
        db=db,
        caregiver_id=payload.caregiver_id,
        child_id=payload.child_id,
        local_date=payload.local_date,
        slot_time=payload.slot_time,
        timezone=payload.timezone,
        message=payload.message,
    )
    return InternalTestSendResult(accepted=accepted)


@router.get("/metrics", response_model=NotificationMetrics, dependencies=[Depends(validate_internal_api_key)])
def notification_metrics(db: Session = Depends(get_db)):
    rows = db.execute(
        select(NotificationLog.status, func.count(NotificationLog.id)).group_by(NotificationLog.status)
    ).all()
    counts = {status: count for status, count in rows}
    total_logs = sum(counts.values())
    return NotificationMetrics(
        total_logs=total_logs,
        sent=counts.get("sent", 0),
        partial=counts.get("partial", 0),
        failed=counts.get("failed", 0),
        no_subscription=counts.get("no_subscription", 0),
    )
