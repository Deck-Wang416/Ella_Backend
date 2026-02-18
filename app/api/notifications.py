from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import validate_internal_api_key
from app.models.notification_log import NotificationLog
from app.schemas.notification import NotificationLogRead

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
