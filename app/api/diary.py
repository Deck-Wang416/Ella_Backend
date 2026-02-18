from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.caregiver import Caregiver
from app.models.child import Child
from app.models.diary_entry import DiaryEntry
from app.schemas.diary import DiaryEntryRead, DiaryEntryUpdate

router = APIRouter(prefix="/diary", tags=["diary"])


@router.get("/{child_id}/{entry_date}", response_model=DiaryEntryRead)
def get_diary_entry(child_id: int, entry_date: date, db: Session = Depends(get_db)):
    child = db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    diary = db.scalar(
        select(DiaryEntry).where(
            DiaryEntry.child_id == child_id,
            DiaryEntry.entry_date == entry_date,
        )
    )
    if not diary:
        return DiaryEntryRead(
            id=None,
            child_id=child_id,
            entry_date=entry_date,
            submitted=False,
            submitted_at=None,
            updated_at=None,
            responses=None,
        )
    return diary


@router.put("/{child_id}/{entry_date}", response_model=DiaryEntryRead)
def upsert_diary_entry(child_id: int, entry_date: date, payload: DiaryEntryUpdate, db: Session = Depends(get_db)):
    child = db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    caregiver = db.get(Caregiver, child.caregiver_id)
    caregiver_tz = caregiver.timezone if caregiver else "UTC"
    try:
        local_today = datetime.now(ZoneInfo(caregiver_tz)).date()
    except ZoneInfoNotFoundError:
        local_today = datetime.now(timezone.utc).date()

    if entry_date != local_today:
        raise HTTPException(status_code=400, detail="Only today's diary can be edited")

    diary = db.scalar(
        select(DiaryEntry).where(
            DiaryEntry.child_id == child_id,
            DiaryEntry.entry_date == entry_date,
        )
    )
    now_utc = datetime.now(timezone.utc)

    if diary:
        diary.submitted = payload.submitted
        diary.responses = payload.responses
        diary.submitted_at = now_utc if payload.submitted else None
        diary.updated_at = now_utc
    else:
        diary = DiaryEntry(
            child_id=child_id,
            entry_date=entry_date,
            submitted=payload.submitted,
            responses=payload.responses,
            submitted_at=now_utc if payload.submitted else None,
            updated_at=now_utc,
        )
        db.add(diary)

    db.commit()
    db.refresh(diary)
    return diary
