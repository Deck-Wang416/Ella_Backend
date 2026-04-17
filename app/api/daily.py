from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from app.schemas.daily import DailyDetailResponse, DailyInitializeRequest, DailySummary, DailyUpdateRequest
from app.services.daily_content_service import DailyContentService
from app.services.firebase_notification_state_service import FirebaseNotificationStateService

router = APIRouter(prefix="/daily", tags=["daily"])


def _validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Invalid timezone") from exc
    return timezone_name


def _resolve_timezone(caregiver_id: int | None, fallback_timezone: str | None) -> str:
    if fallback_timezone:
        return _validate_timezone(fallback_timezone)
    if caregiver_id is None:
        return "UTC"
    settings = FirebaseNotificationStateService().get_reminder(caregiver_id)
    if settings and settings.get("timezone"):
        return _validate_timezone(settings["timezone"])
    return "UTC"


def _to_detail_response(service: DailyContentService, daily, timezone_name: str) -> DailyDetailResponse:
    summary = service.build_summary(daily, timezone_name=timezone_name)
    return DailyDetailResponse(
        date=daily.date,
        condition=daily.condition,
        dashboard=daily.dashboard,
        diary=daily.diary,
        meta={
            "hasInteraction": summary.hasInteraction,
            "diarySubmitted": summary.diarySubmitted,
            "diarySelectable": summary.diarySelectable,
            "dashboardSelectable": summary.dashboardSelectable,
            "diaryEditable": summary.diaryEditable,
        },
    )


@router.get("/summaries", response_model=list[DailySummary])
def get_daily_summaries(
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    return service.list_summaries(timezone_name=tz_name)


@router.get("/{entry_date}", response_model=DailyDetailResponse)
def get_daily(
    entry_date: date,
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    try:
        daily = service.get_daily(entry_date)
        return _to_detail_response(service, daily, tz_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None


@router.post("/{entry_date}/initialize", response_model=DailyDetailResponse)
def initialize_daily(
    entry_date: date,
    payload: DailyInitializeRequest,
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    try:
        daily = service.initialize_daily_today(
            target_date=entry_date,
            timezone_name=tz_name,
            condition=payload.condition,
        )
        return _to_detail_response(service, daily, tz_name)
    except PermissionError:
        raise HTTPException(status_code=409, detail="Only today's daily content can be initialized") from None
    except FileExistsError:
        raise HTTPException(status_code=409, detail="Daily content already exists") from None


@router.put("/{entry_date}", response_model=DailyDetailResponse)
def update_daily(
    entry_date: date,
    payload: DailyUpdateRequest,
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    try:
        daily = service.upsert_diary_today(
            target_date=entry_date,
            timezone_name=tz_name,
            responses=payload.responses,
            submitted=payload.submitted,
        )
        return _to_detail_response(service, daily, tz_name)
    except PermissionError:
        raise HTTPException(status_code=409, detail="Edit not allowed for non-today date") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily content not found") from None
