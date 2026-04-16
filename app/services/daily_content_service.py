from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import (
    DailyContent,
    DailyModes,
    DailySummary,
    DiaryContent,
    ModeType,
    ParentAudioMeta,
    ParentDashboardContent,
    ParentModeContent,
    RobotDashboardContent,
    RobotModeContent,
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

    def build_empty_daily(self, target_date: date) -> DailyContent:
        return DailyContent(
            date=target_date.isoformat(),
            availableModes=["robot", "parent"],
            defaultMode="robot",
            modes=DailyModes(
                robot=self.build_mode_content("robot"),
                parent=self.build_mode_content("parent"),
            ),
        )

    def add_mode(self, target_date: date, mode: ModeType, make_default: bool = False) -> DailyContent:
        try:
            daily = self.get_daily(target_date)
        except FileNotFoundError:
            daily = self.build_empty_daily(target_date)
            self._save_daily(target_date, daily)
            return daily

        existing_mode = self.get_mode_content(daily, mode)
        if existing_mode is None:
            self.set_mode_content(daily, mode, self.build_mode_content(mode))

        available_modes = self.available_modes(daily)
        if make_default and mode in available_modes:
            daily.defaultMode = mode
        elif "robot" in available_modes:
            daily.defaultMode = "robot"
        elif available_modes:
            daily.defaultMode = available_modes[0]

        self._save_daily(target_date, daily)
        return daily

    def upsert_diary_today(
        self,
        target_date: date,
        timezone_name: str,
        responses: dict,
        submitted: bool,
        mode: ModeType | None = None,
    ) -> DailyContent:
        today = self._local_today(timezone_name)
        if target_date != today:
            raise PermissionError("Only today's daily diary is editable")

        try:
            daily = self.get_daily(target_date)
        except FileNotFoundError:
            daily = self.build_empty_daily(target_date)

        selected_mode = mode or daily.defaultMode
        mode_content = self.get_mode_content(daily, selected_mode)
        if mode_content is None:
            raise ValueError(f"Mode '{selected_mode}' is not available for this date")

        now = datetime.now(timezone.utc)
        first_submit = mode_content.diary.submittedAt
        mode_content.diary.responses = responses
        mode_content.diary.submitted = bool(submitted)
        if submitted and first_submit is None:
            mode_content.diary.submittedAt = now
        if not submitted:
            mode_content.diary.submittedAt = None
        mode_content.diary.updatedAt = now

        self.set_mode_content(daily, selected_mode, mode_content)
        self._save_daily(target_date, daily)
        return daily

    def is_submitted(self, target_date: date) -> bool:
        try:
            daily = self.get_daily(target_date)
            return any(
                bool(mode_content.diary.submitted)
                for mode_content in self.iter_mode_contents(daily)
            )
        except FileNotFoundError:
            return False

    def build_summary(self, daily: DailyContent, timezone_name: str = "UTC") -> DailySummary:
        day = date.fromisoformat(daily.date)
        today = self._local_today(timezone_name)
        mode_contents = list(self.iter_mode_contents(daily))
        has_interaction = any(bool(item.dashboard.hasInteraction) for item in mode_contents)
        diary_submitted = any(bool(item.diary.submitted) for item in mode_contents)
        is_today = day == today
        return DailySummary(
            date=daily.date,
            availableModes=self.available_modes(daily),
            defaultMode=daily.defaultMode,
            isToday=is_today,
            hasInteraction=has_interaction,
            diarySubmitted=diary_submitted,
            todayBlueDot=is_today and diary_submitted,
            diarySelectable=is_today or (day < today and diary_submitted),
            dashboardSelectable=has_interaction,
            diaryEditable=is_today,
        )

    def build_mode_summary(self, daily: DailyContent, mode: ModeType, timezone_name: str = "UTC") -> DailySummary:
        mode_content = self.get_mode_content(daily, mode)
        if mode_content is None:
            raise ValueError(f"Mode '{mode}' is not available for this date")
        day = date.fromisoformat(daily.date)
        today = self._local_today(timezone_name)
        has_interaction = bool(mode_content.dashboard.hasInteraction)
        diary_submitted = bool(mode_content.diary.submitted)
        is_today = day == today
        return DailySummary(
            date=daily.date,
            availableModes=self.available_modes(daily),
            defaultMode=daily.defaultMode,
            isToday=is_today,
            hasInteraction=has_interaction,
            diarySubmitted=diary_submitted,
            todayBlueDot=is_today and diary_submitted,
            diarySelectable=is_today or (day < today and diary_submitted),
            dashboardSelectable=has_interaction,
            diaryEditable=is_today,
        )

    def build_mode_content(self, mode: ModeType) -> RobotModeContent | ParentModeContent:
        template = self._load_latest_diary_template(mode)
        common_diary = DiaryContent(
            submitted=False,
            submittedAt=None,
            updatedAt=None,
            instructions=template["instructions"],
            questions=template["questions"],
            responses={},
        )
        if mode == "parent":
            return ParentModeContent(
                dashboard=ParentDashboardContent(
                    hasInteraction=False,
                    words=[],
                    highlight=[],
                    ask=[],
                ),
                diary=common_diary,
                parentAudio=ParentAudioMeta(enabled=True, activeSession=None),
            )
        return RobotModeContent(
            dashboard=RobotDashboardContent(
                hasInteraction=False,
                photos=[],
                words=[],
                highlight=[],
                ask=[],
            ),
            diary=common_diary,
        )

    def get_mode_content(self, daily: DailyContent, mode: ModeType) -> RobotModeContent | ParentModeContent | None:
        return getattr(daily.modes, mode)

    def set_mode_content(self, daily: DailyContent, mode: ModeType, mode_content: RobotModeContent | ParentModeContent | None) -> None:
        setattr(daily.modes, mode, mode_content)
        daily.availableModes = self.available_modes(daily)
        if daily.defaultMode not in daily.availableModes:
            daily.defaultMode = daily.availableModes[0] if daily.availableModes else "robot"

    def available_modes(self, daily: DailyContent) -> list[ModeType]:
        result: list[ModeType] = []
        if daily.modes.robot is not None:
            result.append("robot")
        if daily.modes.parent is not None:
            result.append("parent")
        return result

    def iter_mode_contents(self, daily: DailyContent) -> list[RobotModeContent | ParentModeContent]:
        result: list[RobotModeContent | ParentModeContent] = []
        for mode in ("robot", "parent"):
            mode_content = getattr(daily.modes, mode)
            if mode_content is not None:
                result.append(mode_content)
        return result

    def normalize_daily_payload(self, payload: dict, target_date: date | None = None) -> DailyContent:
        if "modes" in payload:
            daily = DailyContent.model_validate(payload)
            daily.availableModes = self.available_modes(daily)
            if daily.defaultMode not in daily.availableModes:
                daily.defaultMode = daily.availableModes[0] if daily.availableModes else "robot"
            return daily

        fallback_mode: ModeType = payload.get("condition", "robot")
        if fallback_mode not in ("robot", "parent"):
            fallback_mode = "robot"

        diary = DiaryContent.model_validate(payload.get("diary") or {})
        parent_audio_payload = payload.get("parentAudio")
        parent_audio = ParentAudioMeta.model_validate(parent_audio_payload) if isinstance(parent_audio_payload, dict) else None
        modes = DailyModes()
        if fallback_mode == "parent":
            dashboard = ParentDashboardContent.model_validate(payload.get("dashboard") or {})
            modes.parent = ParentModeContent(
                dashboard=dashboard,
                diary=diary,
                parentAudio=parent_audio,
            )
        else:
            dashboard = RobotDashboardContent.model_validate(payload.get("dashboard") or {})
            modes.robot = RobotModeContent(
                dashboard=dashboard,
                diary=diary,
            )
        resolved_date = payload.get("date") or (target_date.isoformat() if target_date else "")
        return DailyContent(
            date=resolved_date,
            availableModes=[fallback_mode],
            defaultMode=fallback_mode,
            modes=modes,
        )

    def _save_daily(self, target_date: date, daily: DailyContent) -> None:
        ref = get_rtdb_reference(f"{self.settings.firebase_daily_root}/{target_date.isoformat()}")
        ref.set(daily.model_dump(mode="json", exclude_none=True))

    def _load_latest_diary_template(self, mode: ModeType | None = None) -> dict:
        records = list(self._iter_daily_records())
        if not records:
            return {"instructions": [], "questions": []}
        records.sort(key=lambda item: item.date)
        for item in reversed(records):
            template_mode = None
            if mode is not None:
                template_mode = self.get_mode_content(item, mode)
            if template_mode is None:
                template_mode = self.get_mode_content(item, item.defaultMode) or next(iter(self.iter_mode_contents(item)), None)
            if template_mode is None:
                continue
            try:
                return {
                    "instructions": template_mode.diary.instructions or [],
                    "questions": template_mode.diary.questions or [],
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
