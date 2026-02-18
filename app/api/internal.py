from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import validate_internal_api_key
from app.schemas.internal import RunDueResult
from app.services.reminder_service import ReminderRunner

router = APIRouter(prefix="/internal/reminders", tags=["internal-reminders"])


@router.post("/run-due", response_model=RunDueResult, dependencies=[Depends(validate_internal_api_key)])
def run_due_reminders(db: Session = Depends(get_db)):
    checked, triggered = ReminderRunner().run_due(db)
    return RunDueResult(checked_caregivers=checked, triggered_notifications=triggered)
