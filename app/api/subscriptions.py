from fastapi import APIRouter, HTTPException, status

from app.schemas.subscription import (
    NotificationSubscriptionRead,
    NotificationSubscriptionUpdate,
    NotificationSubscriptionUpsert,
)
from app.services.firebase_notification_state_service import FirebaseNotificationStateService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("", response_model=NotificationSubscriptionRead, status_code=status.HTTP_201_CREATED)
def upsert_subscription(payload: NotificationSubscriptionUpsert):
    state = FirebaseNotificationStateService()
    sub = state.upsert_subscription(
        caregiver_id=payload.caregiver_id,
        platform=payload.platform,
        endpoint_or_token=payload.endpoint_or_token,
        keys=payload.keys,
    )
    return {
        "id": sub["id"],
        "caregiver_id": sub["caregiverId"],
        "platform": sub["platform"],
        "endpoint_or_token": sub["endpointOrToken"],
        "keys": sub.get("keys"),
        "active": bool(sub.get("active", True)),
        "created_at": sub.get("createdAt"),
        "updated_at": sub.get("updatedAt"),
    }


@router.get("/{caregiver_id}", response_model=list[NotificationSubscriptionRead])
def list_subscriptions(caregiver_id: int):
    state = FirebaseNotificationStateService()
    subs = state.list_subscriptions(caregiver_id)
    return [
        {
            "id": item["id"],
            "caregiver_id": item["caregiverId"],
            "platform": item["platform"],
            "endpoint_or_token": item["endpointOrToken"],
            "keys": item.get("keys"),
            "active": bool(item.get("active", True)),
            "created_at": item.get("createdAt"),
            "updated_at": item.get("updatedAt"),
        }
        for item in subs
    ]


@router.put("/{subscription_id}", response_model=NotificationSubscriptionRead)
def update_subscription(subscription_id: int, payload: NotificationSubscriptionUpdate):
    state = FirebaseNotificationStateService()
    patch: dict = {}
    if payload.endpoint_or_token is not None:
        patch["endpointOrToken"] = payload.endpoint_or_token
    if payload.keys is not None:
        patch["keys"] = payload.keys
    if payload.active is not None:
        patch["active"] = payload.active

    sub = state.update_subscription(subscription_id, patch)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {
        "id": sub["id"],
        "caregiver_id": sub["caregiverId"],
        "platform": sub["platform"],
        "endpoint_or_token": sub["endpointOrToken"],
        "keys": sub.get("keys"),
        "active": bool(sub.get("active", True)),
        "created_at": sub.get("createdAt"),
        "updated_at": sub.get("updatedAt"),
    }


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(subscription_id: int):
    state = FirebaseNotificationStateService()
    ok = state.deactivate_subscription(subscription_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return None
