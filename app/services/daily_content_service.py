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
        template = self._current_diary_template()
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
        template = self._current_diary_template()
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

    def _current_diary_template(self) -> dict[str, list]:
        instructions = [
            "Please complete this diary once per day, preferably at the end of the day.",
            "There are no right or wrong answers — we are interested in your observations.",
            "You may write short notes or longer reflections.",
            "If your child does not interact with Ella on a given day, please still complete the entry.",
        ]
        questions = [
            DailyQuestion.model_validate(
                {
                    "id": "prompted",
                    "type": "checkbox",
                    "label": "What prompted the storytelling session? (Check all that apply)",
                    "options": [
                        "Child initiated",
                        "Parent prompted",
                        "Sibling encouraged",
                        "Scheduled routine",
                        "Unsure",
                        "My child did not engage in a session today",
                        "Other",
                    ],
                    "followup": {
                        "label": "If Other, please specify:",
                        "showWhen": {
                            "operator": "includesAny",
                            "value": ["Other"],
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "who_present",
                    "type": "checkbox",
                    "label": "Who was present or engaged during the session? (Check all that apply)",
                    "options": [
                        "Parent(s)",
                        "Other caregiver(s)",
                        "Sibling(s)",
                        "Friend(s)",
                        "Child was alone",
                        "Unsure",
                        "Other",
                    ],
                    "followup": {
                        "label": "If Other, please specify:",
                        "showWhen": {
                            "operator": "includesAny",
                            "value": ["Other"],
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "feelings",
                    "type": "checkbox",
                    "label": "How did your child feel about Ella today? (Check all that apply)",
                    "options": [
                        "Excited",
                        "Neutral",
                        "Frustrated",
                        "Hesitant",
                        "Want to continue beyond the session",
                        "Unsure",
                        "Other",
                    ],
                    "followup": {
                        "label": "If Other, please specify:",
                        "showWhen": {
                            "operator": "includesAny",
                            "value": ["Other"],
                        },
                    },
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "story_ideas",
                    "type": "checkbox",
                    "label": "Did your child use story ideas outside the session today? (Check all that apply)",
                    "options": [
                        "Wanted related books",
                        "Wanted related tv show/movies",
                        "Asked related questions",
                        "No, my child did not use story ideas outside the session today",
                        "Unsure",
                        "Other",
                    ],
                    "followups": [
                        {
                            "label": "If Other, please specify:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": ["Other"],
                            },
                        },
                        {
                            "label": "If yes, could you briefly describe how your child used the story ideas:",
                            "showWhen": {
                                "operator": "includesAny",
                                "value": [
                                    "Wanted related books",
                                    "Wanted related tv show/movies",
                                    "Asked related questions",
                                ],
                            },
                        },
                    ],
                }
            ),
            DailyQuestion.model_validate(
                {
                    "id": "read_book",
                    "type": "radio",
                    "label": "Did you read a book or tell your child a story today?",
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
                    "id": "mention_ella",
                    "type": "checkbox",
                    "label": "Did your child talk about Ella or the stories today? (Check all that apply)",
                    "options": [
                        "Shared story with caregiver",
                        "Shared story with others",
                        "Talked about Ella with caregiver",
                        "Talked about Ella with others",
                        "No, my child did not mention Ella today",
                        "Unsure",
                    ],
                    "followup": {
                        "label": "If yes, could you briefly describe how your child mentioned Ella or the stories:",
                        "showWhen": {
                            "operator": "includesAny",
                            "value": [
                                "Shared story with caregiver",
                                "Shared story with others",
                                "Talked about Ella with caregiver",
                                "Talked about Ella with others",
                            ],
                        },
                    },
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
                    "id": "no_engage_reason",
                    "type": "checkbox",
                    "label": "If your child did not engage with Ella today, why? (Check all that apply; skip if your child did engage with Ella today)",
                    "options": [
                        "Child was not interested",
                        "Time constraints",
                        "Technical issue",
                        "Child was tired or upset",
                        "Unsure",
                        "Other",
                    ],
                    "showWhen": {
                        "questionId": "prompted",
                        "operator": "includesAny",
                        "value": ["My child did not engage in a session today"],
                    },
                    "followup": {
                        "label": "If Other, please specify:",
                        "showWhen": {
                            "operator": "includesAny",
                            "value": ["Other"],
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
