from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import DailyContent, DailySummary


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
            result.append(
                DailySummary(
                    date=today.isoformat(),
                    isToday=True,
                    hasInteraction=False,
                    diarySubmitted=False,
                    todayBlueDot=False,
                    diarySelectable=True,
                    dashboardSelectable=False,
                    diaryEditable=True,
                )
            )
        result.sort(key=lambda item: item.date)
        return result

    def get_daily(self, target_date: date) -> DailyContent:
        ref = get_rtdb_reference(f"{self.settings.firebase_daily_root}/{target_date.isoformat()}")
        payload = ref.get()
        if payload:
            return DailyContent.model_validate(payload)
        raise FileNotFoundError(target_date.isoformat())

    def build_empty_daily(self, target_date: date) -> DailyContent:
        template = self._load_latest_diary_template()
        return DailyContent(
            date=target_date.isoformat(),
            dashboard={
                "hasInteraction": False,
                "photos": [],
                "words": [],
                "highlight": [],
                "ask": [],
            },
            diary={
                "submitted": False,
                "submittedAt": None,
                "updatedAt": None,
                "instructions": template["instructions"],
                "questions": template["questions"],
                "responses": {},
            },
        )

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

        try:
            daily = self.get_daily(target_date)
        except FileNotFoundError:
            daily = self.build_empty_daily(target_date)

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
        is_today = day == today
        return DailySummary(
            date=daily.date,
            isToday=is_today,
            hasInteraction=bool(daily.dashboard.hasInteraction),
            diarySubmitted=submitted,
            todayBlueDot=is_today and submitted,
            diarySelectable=is_today or (day < today and submitted),
            dashboardSelectable=bool(daily.dashboard.hasInteraction),
            diaryEditable=is_today,
        )

    def _save_daily(self, target_date: date, daily: DailyContent) -> None:
        ref = get_rtdb_reference(f"{self.settings.firebase_daily_root}/{target_date.isoformat()}")
        ref.set(daily.model_dump(mode="json"))

    def _load_latest_diary_template(self) -> dict:
        """
        Use the latest existing daily file as the form template source.
        If no file exists, return empty arrays with correct schema shape.
        """
        records = list(self._iter_daily_records())
        if not records:
            return {"instructions": [], "questions": []}
        records.sort(key=lambda item: item.date)
        latest = records[-1]
        try:
            return {
                "instructions": latest.diary.instructions or [],
                "questions": latest.diary.questions or [],
            }
        except Exception:
            return {"instructions": [], "questions": []}

    def _iter_daily_records(self) -> list[DailyContent]:
        records: list[DailyContent] = []
        ref = get_rtdb_reference(self.settings.firebase_daily_root)
        payload = ref.get() or {}
        if isinstance(payload, dict):
            for _, value in payload.items():
                try:
                    records.append(DailyContent.model_validate(value))
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
