import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.schemas.daily import DailyContent, DailySummary


class DailyContentService:
    def __init__(self):
        self.settings = get_settings()
        self.base_dir = Path(self.settings.daily_data_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, target_date: date) -> Path:
        return self.base_dir / f"{target_date.isoformat()}.json"

    def list_summaries(self, timezone_name: str = "UTC") -> list[DailySummary]:
        today = self._local_today(timezone_name)
        result: list[DailySummary] = []
        seen_dates: set[date] = set()
        for file_path in sorted(self.base_dir.glob("*.json")):
            daily = self._read_file(file_path)
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
        file_path = self._file_path(target_date)
        if not file_path.exists():
            raise FileNotFoundError(target_date.isoformat())
        return self._read_file(file_path)

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

        file_path = self._file_path(target_date)
        if file_path.exists():
            daily = self._read_file(file_path)
        else:
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

        self._write_file(file_path, daily)
        return daily

    def is_submitted(self, target_date: date) -> bool:
        file_path = self._file_path(target_date)
        if not file_path.exists():
            return False
        daily = self._read_file(file_path)
        return bool(daily.diary.submitted)

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

    def _read_file(self, file_path: Path) -> DailyContent:
        with file_path.open("r", encoding="utf-8") as f:
            return DailyContent.model_validate(json.load(f))

    def _write_file(self, file_path: Path, daily: DailyContent) -> None:
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(daily.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    def _load_latest_diary_template(self) -> dict:
        """
        Use the latest existing daily file as the form template source.
        If no file exists, return empty arrays with correct schema shape.
        """
        files = sorted(self.base_dir.glob("*.json"))
        if not files:
            return {"instructions": [], "questions": []}

        latest_file = files[-1]
        try:
            latest = self._read_file(latest_file)
            return {
                "instructions": latest.diary.instructions or [],
                "questions": latest.diary.questions or [],
            }
        except Exception:
            return {"instructions": [], "questions": []}

    def _local_today(self, timezone_name: str) -> date:
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    def local_today(self, timezone_name: str) -> date:
        return self._local_today(timezone_name)
