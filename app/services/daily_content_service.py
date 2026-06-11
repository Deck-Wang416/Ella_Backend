from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import (
    ConditionType,
    DailyContent,
    DailyQuestion,
    DailySummary,
    DiaryContent,
    DashboardContent,
    ParentDashboardContent,
    WeeklyProgress,
)
from app.services.user_profile_service import UserProfileService


class DailyContentService:
    def __init__(self):
        self.settings = get_settings()
        self.profile_service = UserProfileService()
        if not self.settings.firebase_database_url or not self.settings.firebase_credentials_path:
            raise RuntimeError("Firebase is required. Set FIREBASE_DATABASE_URL and FIREBASE_CREDENTIALS_PATH.")

    def list_summaries(self, caregiver_id: int, timezone_name: str = "UTC") -> list[DailySummary]:
        result: list[DailySummary] = []
        for day in self.profile_service.list_scheduled_dates(caregiver_id):
            daily = self.get_daily(caregiver_id, day)
            result.append(self.build_summary(daily, timezone_name))
        result.sort(key=lambda item: item.date)
        return result

    def get_daily(self, caregiver_id: int, target_date: date) -> DailyContent:
        expected_condition = self.resolve_condition_for_date(caregiver_id, target_date)
        if expected_condition is None:
            raise FileNotFoundError(target_date.isoformat())

        ref = get_rtdb_reference(f"{self._daily_root(caregiver_id)}/{target_date.isoformat()}")
        payload = ref.get()
        if payload:
            return self.normalize_daily_payload(payload, target_date)
        daily = self.build_empty_daily(caregiver_id, target_date, condition=expected_condition)
        self._save_daily(caregiver_id, target_date, daily)
        return daily

    def enrich_dashboard_with_weekly_progress(self, caregiver_id: int, daily: DailyContent) -> DailyContent:
        progress = self.get_weekly_progress(
            caregiver_id=caregiver_id,
            target_date=date.fromisoformat(daily.date),
            condition=daily.condition,
        )
        daily.dashboard.weeklyProgress = progress
        return daily

    def build_empty_daily(self, caregiver_id: int, target_date: date, condition: ConditionType = "robot") -> DailyContent:
        template = self._diary_template_for_condition(condition)
        dashboard = (
            ParentDashboardContent(book=None, words=[])
            if condition == "parent"
            else DashboardContent(photos=[], storyCount=0, words=[], highlight=[], ask=[])
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
        )

    def initialize_daily_today(
        self,
        caregiver_id: int,
        target_date: date,
        timezone_name: str,
    ) -> DailyContent:
        today = self._local_today(timezone_name)
        if target_date != today:
            raise PermissionError("Only today's daily content can be initialized")
        expected_condition = self.resolve_condition_for_date(caregiver_id, target_date)
        if expected_condition is None:
            raise PermissionError("Today's date is outside configured condition ranges")
        daily = self.get_daily(caregiver_id, target_date)
        return daily

    def upsert_diary_today(
        self,
        caregiver_id: int,
        target_date: date,
        timezone_name: str,
        responses: dict,
        submitted: bool,
    ) -> DailyContent:
        today = self._local_today(timezone_name)
        if target_date != today:
            raise PermissionError("Only today's daily diary is editable")

        daily = self.get_daily(caregiver_id, target_date)

        now = datetime.now(timezone.utc)
        first_submit = daily.diary.submittedAt
        daily.diary.responses = responses
        daily.diary.submitted = bool(submitted)
        if submitted and first_submit is None:
            daily.diary.submittedAt = now
        if not submitted:
            daily.diary.submittedAt = None
        daily.diary.updatedAt = now

        self._save_daily(caregiver_id, target_date, daily)
        return daily

    def is_submitted(self, caregiver_id: int, target_date: date) -> bool:
        try:
            daily = self.get_daily(caregiver_id, target_date)
            return bool(daily.diary.submitted)
        except FileNotFoundError:
            return False

    def resolve_condition_for_date(self, caregiver_id: int, target_date: date) -> ConditionType | None:
        return self.profile_service.resolve_condition_for_date(caregiver_id, target_date)

    def build_summary(self, daily: DailyContent, timezone_name: str = "UTC") -> DailySummary:
        day = date.fromisoformat(daily.date)
        today = self._local_today(timezone_name)
        submitted = bool(daily.diary.submitted)
        has_interaction = self._has_dashboard_interaction(daily)
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
        template = self._diary_template_for_condition(condition)
        diary.instructions = template["instructions"]
        diary.questions = template["questions"]
        resolved_date = payload.get("date") or (target_date.isoformat() if target_date else "")

        return DailyContent(
            date=resolved_date,
            condition=condition,
            dashboard=dashboard,
            diary=diary,
        )

    def get_weekly_progress(
        self,
        caregiver_id: int,
        target_date: date,
        condition: ConditionType,
    ) -> WeeklyProgress:
        week_start, week_end = self._resolve_condition_week_range(caregiver_id, target_date, condition)
        if condition == "robot":
            current_value = float(self._count_robot_stories(caregiver_id, week_start, week_end))
            target_value = 14.0
            unit = "stories"
        else:
            current_value = self._display_parent_hours(
                self._sum_parent_recording_seconds(caregiver_id, week_start, week_end)
            )
            target_value = 1.5
            unit = "hours"

        return WeeklyProgress(
            startDate=week_start.isoformat(),
            endDate=week_end.isoformat(),
            currentValue=current_value,
            targetValue=target_value,
            unit=unit,
        )

    def _resolve_condition_week_range(
        self,
        caregiver_id: int,
        target_date: date,
        condition: ConditionType,
    ) -> tuple[date, date]:
        profile = self.profile_service.get_profile(caregiver_id)
        if profile is None:
            raise FileNotFoundError(caregiver_id)

        condition_range = (
            profile.robot_condition_range if condition == "robot" else profile.parent_condition_range
        )
        if condition_range is None:
            raise FileNotFoundError(target_date.isoformat())

        range_start = date.fromisoformat(condition_range.startDate)
        range_end = date.fromisoformat(condition_range.endDate)
        if not (range_start <= target_date <= range_end):
            raise FileNotFoundError(target_date.isoformat())

        delta_days = (target_date - range_start).days
        week_index = delta_days // 7
        week_start = range_start + timedelta(days=week_index * 7)
        week_end = min(week_start + timedelta(days=6), range_end)
        return week_start, week_end

    def _count_robot_stories(self, caregiver_id: int, week_start: date, week_end: date) -> int:
        count = 0
        current = week_start
        while current <= week_end:
            payload = self._get_daily_payload(caregiver_id, current)
            if isinstance(payload, dict) and payload.get("condition") == "robot":
                dashboard_payload = payload.get("dashboard") or {}
                try:
                    story_count = int(dashboard_payload.get("storyCount", 0) or 0)
                except (TypeError, ValueError):
                    story_count = 0
                count += max(story_count, 0)
            current += timedelta(days=1)
        return count

    def upsert_robot_story_count(
        self,
        caregiver_id: int,
        target_date: date,
        story_count: int,
    ) -> DailyContent:
        daily = self.get_daily(caregiver_id, target_date)
        if daily.condition != "robot":
            raise PermissionError("Story count can only be updated for robot-mode daily content")

        daily.dashboard.storyCount = max(story_count, 0)
        self._save_daily(caregiver_id, target_date, daily)
        return daily

    def ensure_robot_daily(
        self,
        caregiver_id: int,
        target_date: date,
    ) -> DailyContent:
        daily = self.get_daily(caregiver_id, target_date)
        if daily.condition != "robot":
            raise PermissionError("Robot data can only be updated for robot-mode daily content")
        return daily

    def append_robot_photo(
        self,
        caregiver_id: int,
        target_date: date,
        photo_url: str,
    ) -> DailyContent:
        daily = self.ensure_robot_daily(caregiver_id, target_date)

        photos = list(daily.dashboard.photos)
        photos.append(photo_url)
        daily.dashboard.photos = photos
        self._save_daily(caregiver_id, target_date, daily)
        return daily

    def _sum_parent_recording_seconds(self, caregiver_id: int, week_start: date, week_end: date) -> int:
        sessions = get_rtdb_reference("recordingSessions").get()
        if not isinstance(sessions, dict):
            return 0

        total_seconds = 0
        for session in sessions.values():
            if not isinstance(session, dict):
                continue
            if session.get("caregiverId") != caregiver_id:
                continue
            if session.get("condition") != "parent":
                continue
            if session.get("status") != "completed":
                continue
            session_date_raw = session.get("date")
            duration_seconds = session.get("durationSeconds")
            if not session_date_raw or duration_seconds is None:
                continue
            try:
                session_date = date.fromisoformat(str(session_date_raw))
                seconds = int(duration_seconds)
            except (TypeError, ValueError):
                continue
            if week_start <= session_date <= week_end:
                total_seconds += max(seconds, 0)
        return total_seconds

    def _display_parent_hours(self, total_seconds: int) -> float:
        if total_seconds <= 0:
            return 0.0
        total_hours = total_seconds / 3600.0
        if total_hours < 0.1:
            return 0.0
        return round(total_hours, 1)

    def _get_daily_payload(self, caregiver_id: int, target_date: date) -> dict | None:
        payload = get_rtdb_reference(f"{self._daily_root(caregiver_id)}/{target_date.isoformat()}").get()
        return payload if isinstance(payload, dict) else None

    def _save_daily(self, caregiver_id: int, target_date: date, daily: DailyContent) -> None:
        ref = get_rtdb_reference(f"{self._daily_root(caregiver_id)}/{target_date.isoformat()}")
        ref.set(daily.model_dump(mode="json", exclude_none=True))

    def _has_dashboard_interaction(self, daily: DailyContent) -> bool:
        dashboard = daily.dashboard
        if daily.condition == "robot":
            return bool(
                getattr(dashboard, "storyCount", 0)
                or getattr(dashboard, "photos", [])
                or getattr(dashboard, "words", [])
                or getattr(dashboard, "highlight", [])
                or getattr(dashboard, "ask", [])
            )
        return bool(getattr(dashboard, "book", None) or getattr(dashboard, "words", []))

    def _parent_diary_template(self) -> dict[str, list]:
        instructions = [
            "Please complete this diary once per day, preferably at the end of the day.",
            "There are no right or wrong answers — we are interested in your observations.",
            "You may write short notes or longer reflections.",
        ]
        questions = [
            DailyQuestion.model_validate(
                {
                    "id": "story_outside_session",
                    "type": "checkbox",
                    "label": "Did your child talk about the stories outside of the story session today?",
                    "options": [
                        "Shared story with parents, siblings, or others",
                        "Asked for related books",
                        "Asked for related TV shows/movies",
                        "Asked related questions",
                        "No, my child did not mention the stories today",
                        "Unsure",
                        "Other",
                    ],
                    "followups": [
                        {
                            "label": "If yes, could you briefly describe how your child mentioned Ella or the stories:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": [
                                    "Shared story with parents, siblings, or others",
                                    "Asked for related books",
                                    "Asked for related TV shows/movies",
                                    "Asked related questions",
                                ],
                            },
                        },
                        {
                            "label": "If Other, please specify:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": ["Other"],
                            },
                        },
                    ],
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "target_words",
                    "type": "radio",
                    "label": "Did you or anyone else hear your child use any target words today?",
                    "options": [
                        "Yes, correctly",
                        "Yes, incorrectly",
                        "No, my child did not use the target words today",
                        "Unsure",
                    ],
                    "followup": {
                        "label": "If yes, could you briefly describe how your child used the target word:",
                        "showWhen": {
                            "operator": "equalsAny",
                            "value": ["Yes, correctly", "Yes, incorrectly"],
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "read_book_outside_session",
                    "type": "radio",
                    "label": "Did you read a book to your child outside of the story session today?",
                    "options": ["Yes", "No"],
                    "followup": {
                        "label": "If not, please share if there was a particular reason:",
                        "showWhen": {
                            "operator": "equals",
                            "value": "No",
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "notes",
                    "type": "textarea",
                    "label": "Any other observations, feedback, or notes from today (e.g., surprises, changes over time, comparisons to previous days).",
                }
            ),
        ]
        return {"instructions": instructions, "questions": questions}

    def _robot_diary_template(self) -> dict[str, list]:
        instructions = [
            "Please complete this diary once per day, preferably at the end of the day.",
            "There are no right or wrong answers — we are interested in your observations.",
            "You may write short notes or longer reflections.",
        ]
        questions = [
            DailyQuestion.model_validate(
                {
                    "id": "ella_or_story_outside_session",
                    "type": "checkbox",
                    "label": "Did your child talk about Ella or the stories outside of the story session today?",
                    "options": [
                        "Shared story with parents, siblings, or others",
                        "Talked about Ella with parents, siblings, or others",
                        "Asked for related books",
                        "Asked for related TV shows/movies",
                        "Asked related questions",
                        "No, my child did not mention Ella or the stories today",
                        "Unsure",
                        "Other",
                    ],
                    "followups": [
                        {
                            "label": "If yes, could you briefly describe how your child mentioned Ella or the stories:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": [
                                    "Shared story with parents, siblings, or others",
                                    "Talked about Ella with parents, siblings, or others",
                                    "Asked for related books",
                                    "Asked for related TV shows/movies",
                                    "Asked related questions",
                                ],
                            },
                        },
                        {
                            "label": "If Other, please specify:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": ["Other"],
                            },
                        },
                    ],
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "target_words",
                    "type": "radio",
                    "label": "Did you or anyone else hear your child use any target words today?",
                    "options": [
                        "Yes, correctly",
                        "Yes, incorrectly",
                        "No, my child did not use the target words today",
                        "Unsure",
                    ],
                    "followup": {
                        "label": "If yes, could you briefly describe how your child used the target word:",
                        "showWhen": {
                            "operator": "equalsAny",
                            "value": ["Yes, correctly", "Yes, incorrectly"],
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "read_book_today",
                    "type": "radio",
                    "label": "Did you read a book to your child today?",
                    "options": ["Yes", "No"],
                    "followup": {
                        "label": "If not, please share if there was a particular reason:",
                        "showWhen": {
                            "operator": "equals",
                            "value": "No",
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "notes",
                    "type": "textarea",
                    "label": "Any other observations, feedback, or notes from today (e.g., surprises, changes over time, comparisons to previous days).",
                }
            ),
        ]
        return {"instructions": instructions, "questions": questions}

    def _diary_template_for_condition(self, condition: ConditionType) -> dict[str, list]:
        if condition == "parent":
            return self._parent_diary_template()
        return self._robot_diary_template()

    def _local_today(self, timezone_name: str) -> date:
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    def local_today(self, timezone_name: str) -> date:
        return self._local_today(timezone_name)

    def _daily_root(self, caregiver_id: int) -> str:
        return f"{self.settings.firebase_daily_root}/{caregiver_id}"
