from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import ConditionType, DailyContent, DailyQuestion, DailySummary, DiaryContent, DashboardContent, ParentDashboardContent
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

    def build_empty_daily(self, caregiver_id: int, target_date: date, condition: ConditionType = "robot") -> DailyContent:
        template = self._diary_template_for_condition(condition)
        dashboard = (
            ParentDashboardContent(hasInteraction=False, book=None, words=[])
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

    def _save_daily(self, caregiver_id: int, target_date: date, daily: DailyContent) -> None:
        ref = get_rtdb_reference(f"{self._daily_root(caregiver_id)}/{target_date.isoformat()}")
        ref.set(daily.model_dump(mode="json", exclude_none=True))

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
