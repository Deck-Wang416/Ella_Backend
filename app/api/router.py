from fastapi import APIRouter

from app.api.caregivers import router as caregivers_router
from app.api.diary import router as diary_router
from app.api.internal import router as internal_router
from app.api.notifications import router as notifications_router
from app.api.reminders import router as reminders_router
from app.api.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(caregivers_router)
api_router.include_router(diary_router)
api_router.include_router(reminders_router)
api_router.include_router(internal_router)
api_router.include_router(notifications_router)
