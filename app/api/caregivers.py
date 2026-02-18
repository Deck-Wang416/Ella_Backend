from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.caregiver import Caregiver
from app.models.child import Child
from app.models.reminder_setting import ReminderSetting
from app.schemas.caregiver import CaregiverCreate, CaregiverRead, ChildCreate, ChildRead

router = APIRouter(prefix="/caregivers", tags=["caregivers"])


@router.post("", response_model=CaregiverRead, status_code=status.HTTP_201_CREATED)
def create_caregiver(payload: CaregiverCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Caregiver).where(Caregiver.email == payload.email))
    if exists:
        raise HTTPException(status_code=400, detail="Email already exists")

    caregiver = Caregiver(name=payload.name, email=payload.email, timezone=payload.timezone)
    db.add(caregiver)
    db.flush()

    default_settings = ReminderSetting(
        caregiver_id=caregiver.id,
        timezone=payload.timezone,
        reminder_times=["18:00", "21:00"],
        enabled=True,
    )
    db.add(default_settings)
    db.commit()
    db.refresh(caregiver)
    return caregiver


@router.get("/{caregiver_id}", response_model=CaregiverRead)
def get_caregiver(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")
    return caregiver


@router.post("/children", response_model=ChildRead, status_code=status.HTTP_201_CREATED)
def create_child(payload: ChildCreate, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, payload.caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    child = Child(caregiver_id=payload.caregiver_id, name=payload.name)
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@router.get("/{caregiver_id}/children", response_model=list[ChildRead])
def list_children(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    children = db.scalars(select(Child).where(Child.caregiver_id == caregiver_id)).all()
    return list(children)
