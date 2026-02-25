from fastapi import APIRouter

from app.api.daily import router as daily_router
from app.api.internal import router as internal_router
from app.api.notifications import router as notifications_router
from app.api.reminders import router as reminders_router
from app.api.subscriptions import router as subscriptions_router
from app.api.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(daily_router)
api_router.include_router(reminders_router)
api_router.include_router(subscriptions_router)
legacy_notifications_router = APIRouter(prefix="/notifications")
legacy_notifications_router.include_router(subscriptions_router)
api_router.include_router(legacy_notifications_router)
api_router.include_router(internal_router)
api_router.include_router(notifications_router)
