from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.caregiver import Caregiver
from app.models.notification_subscription import NotificationSubscription
from app.schemas.subscription import (
    NotificationSubscriptionRead,
    NotificationSubscriptionUpdate,
    NotificationSubscriptionUpsert,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("", response_model=NotificationSubscriptionRead, status_code=status.HTTP_201_CREATED)
def upsert_subscription(payload: NotificationSubscriptionUpsert, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, payload.caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    existing = db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.caregiver_id == payload.caregiver_id,
            NotificationSubscription.platform == payload.platform,
            NotificationSubscription.endpoint_or_token == payload.endpoint_or_token,
        )
    )
    if existing:
        existing.keys = payload.keys
        existing.active = True
        existing.endpoint_or_token = payload.endpoint_or_token
        existing.endpoint = payload.endpoint_or_token
        db.commit()
        db.refresh(existing)
        return existing

    sub = NotificationSubscription(
        caregiver_id=payload.caregiver_id,
        platform=payload.platform,
        endpoint_or_token=payload.endpoint_or_token,
        endpoint=payload.endpoint_or_token,
        keys=payload.keys,
        active=True,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/{caregiver_id}", response_model=list[NotificationSubscriptionRead])
def list_subscriptions(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="Caregiver not found")

    subs = db.scalars(
        select(NotificationSubscription).where(NotificationSubscription.caregiver_id == caregiver_id)
    ).all()
    return list(subs)


@router.put("/{subscription_id}", response_model=NotificationSubscriptionRead)
def update_subscription(subscription_id: int, payload: NotificationSubscriptionUpdate, db: Session = Depends(get_db)):
    sub = db.get(NotificationSubscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if payload.endpoint_or_token is not None:
        sub.endpoint_or_token = payload.endpoint_or_token
        sub.endpoint = payload.endpoint_or_token
    if payload.keys is not None:
        sub.keys = payload.keys
    if payload.active is not None:
        sub.active = payload.active

    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)):
    sub = db.get(NotificationSubscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.active = False
    db.commit()
    return None
