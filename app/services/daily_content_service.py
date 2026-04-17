from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import (
    ConditionType,
    DailyContent,
    DailySummary,
    DiaryContent,
    DashboardContent,
    ParentAudioMeta,
    ParentDashboardContent,
)


class DailyContentService:
    def __init__(self):
        self.settings = get_settings()
        if not self.settings.firebase_database_url or not self.settings.firebase_credentials_path:
            raise RuntimeError("Firebase is required. Set FIREBASE_DATABASE_URL and FIREBASE_CREDENTIALS_PATH.")

    def list_summaries(self, timezone_name: str = "UTC") -> list[DailySummary]:
        today = self._local_today(timezone_name)
        result: list[DailySummary] = []
        seen_dates: set[date] = set()
        for daily in self._iter_daily_records():
            day = date.fromisoformat(daily.date)
            seen_dates.add(day)
            result.append(self.build_summary(daily, timezone_name))
        if today not in seen_dates:
            empty_daily = self.build_empty_daily(today)
            result.append(self.build_summary(empty_daily, timezone_name))
        result.sort(key=lambda item: item.date)
        return result

    def get_daily(self, target_date: date) -> DailyContent:
        ref = get_rtdb_reference(f"{self.settings.firebase_daily_root}/{target_date.isoformat()}")
        payload = ref.get()
        if payload:
            return self.normalize_daily_payload(payload, target_date)
        raise FileNotFoundError(target_date.isoformat())

    def build_empty_daily(self, target_date: date, condition: ConditionType = "robot") -> DailyContent:
        template = self._load_latest_diary_template()
        dashboard = (
            ParentDashboardContent(hasInteraction=False, words=[])
            if condition == "parent"
            else DashboardContent(hasInteraction=False, photos=[], words=[], highlight=[], ask=[])
        )
        return DailyContent(
            date=target_date.isoformat(),
            condition=condition,
            dashboard=dashboard,
            diary=DiaryContent(
                submitted=False,
                submittedAt=None,
                updatedAt=None,
                instructions=template["instructions"],
                questions=template["questions"],
                responses={},
            ),
            parentAudio=ParentAudioMeta(enabled=True, activeSession=None) if condition == "parent" else None,
        )

    def initialize_daily_today(self, target_date: date, timezone_name: str, condition: ConditionType) -> DailyContent:
        today = self._local_today(timezone_name)
        if target_date != today:
            raise PermissionError("Only today's daily content can be initialized")
        try:
            self.get_daily(target_date)
        except FileNotFoundError:
            daily = self.build_empty_daily(target_date, condition=condition)
            self._save_daily(target_date, daily)
            return daily
        raise FileExistsError(target_date.isoformat())

    def upsert_diary_today(
        self,
        target_date: date,
        timezone_name: str,
        responses: dict,
        submitted: bool,
    ) -> DailyContent:
        today = self._local_today(timezone_name)
        if target_date != today:
            raise PermissionError("Only today's daily diary is editable")

        daily = self.get_daily(target_date)

        now = datetime.now(timezone.utc)
        first_submit = daily.diary.submittedAt
        daily.diary.responses = responses
        daily.diary.submitted = bool(submitted)
        if submitted and first_submit is None:
            daily.diary.submittedAt = now
        if not submitted:
            daily.diary.submittedAt = None
        daily.diary.updatedAt = now

        self._save_daily(target_date, daily)
        return daily

    def is_submitted(self, target_date: date) -> bool:
        try:
            daily = self.get_daily(target_date)
            return bool(daily.diary.submitted)
        except FileNotFoundError:
            return False

    def build_summary(self, daily: DailyContent, timezone_name: str = "UTC") -> DailySummary:
        day = date.fromisoformat(daily.date)
        today = self._local_today(timezone_name)
        submitted = bool(daily.diary.submitted)
        has_interaction = bool(daily.dashboard.hasInteraction)
        is_today = day == today
        return DailySummary(
            date=daily.date,
            condition=daily.condition,
            isToday=is_today,
            hasInteraction=has_interaction,
            diarySubmitted=submitted,
            todayBlueDot=is_today and submitted,
            diarySelectable=is_today or (day < today and submitted),
            dashboardSelectable=has_interaction,
            diaryEditable=is_today,
        )

    def normalize_daily_payload(self, payload: dict, target_date: date | None = None) -> DailyContent:
        condition: ConditionType = payload.get("condition", "robot")
        if condition not in ("robot", "parent"):
            condition = "robot"

        dashboard_payload = payload.get("dashboard") or {}
        dashboard = (
            ParentDashboardContent.model_validate(dashboard_payload)
            if condition == "parent"
            else DashboardContent.model_validate(dashboard_payload)
        )
        diary = DiaryContent.model_validate(payload.get("diary") or {})
        parent_audio_payload = payload.get("parentAudio")
        parent_audio = ParentAudioMeta.model_validate(parent_audio_payload) if isinstance(parent_audio_payload, dict) else None
        resolved_date = payload.get("date") or (target_date.isoformat() if target_date else "")

        return DailyContent(
            date=resolved_date,
            condition=condition,
            dashboard=dashboard,
            diary=diary,
            parentAudio=parent_audio if condition == "parent" else None,
        )

    def _save_daily(self, target_date: date, daily: DailyContent) -> None:
        ref = get_rtdb_reference(f"{self.settings.firebase_daily_root}/{target_date.isoformat()}")
        ref.set(daily.model_dump(mode="json", exclude_none=True))

    def _load_latest_diary_template(self) -> dict:
        records = list(self._iter_daily_records())
        if not records:
            return {"instructions": [], "questions": []}
        records.sort(key=lambda item: item.date)
        for item in reversed(records):
            try:
                return {
                    "instructions": item.diary.instructions or [],
                    "questions": item.diary.questions or [],
                }
            except Exception:
                continue
        return {"instructions": [], "questions": []}

    def _iter_daily_records(self) -> list[DailyContent]:
        records: list[DailyContent] = []
        ref = get_rtdb_reference(self.settings.firebase_daily_root)
        payload = ref.get() or {}
        if isinstance(payload, dict):
            for key, value in payload.items():
                try:
                    fallback_date = date.fromisoformat(str(key))
                    records.append(self.normalize_daily_payload(value, fallback_date))
                except Exception:
                    continue
        return records

    def _local_today(self, timezone_name: str) -> date:
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    def local_today(self, timezone_name: str) -> date:
        return self._local_today(timezone_name)
