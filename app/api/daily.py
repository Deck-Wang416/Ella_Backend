from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from app.schemas.daily import DailyDetailResponse, DailyModeCreateRequest, DailySummary, DailyUpdateRequest, ModeType
from app.services.daily_content_service import DailyContentService
from app.services.firebase_notification_state_service import FirebaseNotificationStateService
from app.services.firebase_recording_service import FirebaseRecordingService

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


def _resolve_mode(daily, requested_mode: ModeType | None) -> ModeType:
    selected_mode = requested_mode or daily.defaultMode
    if selected_mode not in daily.availableModes:
        raise HTTPException(status_code=404, detail=f"Mode '{selected_mode}' is not available for this date")
    return selected_mode


def _to_detail_response(service: DailyContentService, daily, timezone_name: str, requested_mode: ModeType | None) -> DailyDetailResponse:
    selected_mode = _resolve_mode(daily, requested_mode)
    mode_content = service.get_mode_content(daily, selected_mode)
    if mode_content is None:
        raise HTTPException(status_code=404, detail=f"Mode '{selected_mode}' is not available for this date")
    summary = service.build_mode_summary(daily, selected_mode, timezone_name=timezone_name)
    parent_audio = FirebaseRecordingService().build_parent_audio_meta(daily, selected_mode)
    return DailyDetailResponse(
        date=daily.date,
        availableModes=daily.availableModes,
        defaultMode=daily.defaultMode,
        selectedMode=selected_mode,
        dashboard=mode_content.dashboard,
        diary=mode_content.diary,
        meta={
            "hasInteraction": summary.hasInteraction,
            "diarySubmitted": summary.diarySubmitted,
            "diarySelectable": summary.diarySelectable,
            "dashboardSelectable": summary.dashboardSelectable,
            "diaryEditable": summary.diaryEditable,
        },
        parentAudio=parent_audio,
    )


def _local_today(timezone_name: str) -> date:
    return DailyContentService().local_today(timezone_name)


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
    mode: ModeType | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    try:
        daily = service.get_daily(entry_date)
        return _to_detail_response(service, daily, tz_name, mode)
    except FileNotFoundError:
        if entry_date == _local_today(tz_name):
            daily = service.build_empty_daily(entry_date)
            return _to_detail_response(service, daily, tz_name, mode)
        raise HTTPException(status_code=404, detail="Daily content not found") from None


@router.post("/{entry_date}/modes/{mode}", response_model=DailyDetailResponse)
def create_daily_mode(
    entry_date: date,
    mode: ModeType,
    payload: DailyModeCreateRequest | None = None,
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    daily = service.add_mode(entry_date, mode, make_default=bool(payload and payload.makeDefault))
    return _to_detail_response(service, daily, tz_name, mode)


@router.put("/{entry_date}", response_model=DailyDetailResponse)
def update_daily(
    entry_date: date,
    payload: DailyUpdateRequest,
    caregiver_id: int | None = Query(default=None),
    timezone: str | None = Query(default=None),
    mode: ModeType | None = Query(default=None),
):
    tz_name = _resolve_timezone(caregiver_id, timezone)
    service = DailyContentService()
    try:
        daily = service.upsert_diary_today(
            target_date=entry_date,
            timezone_name=tz_name,
            responses=payload.responses,
            submitted=payload.submitted,
            mode=mode,
        )
        return _to_detail_response(service, daily, tz_name, mode)
    except PermissionError:
        raise HTTPException(status_code=409, detail="Edit not allowed for non-today date") from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
