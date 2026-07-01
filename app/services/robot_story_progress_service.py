from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.firebase_client import get_rtdb_reference
from app.services.firebase_notification_state_service import FirebaseNotificationStateService
from app.services.user_profile_service import UserProfileService


class RobotStoryProgressConflictError(ValueError):
    pass


@dataclass
class RobotWeekWindow:
    caregiver_id: int
    username: str
    timezone_name: str
    week_number: int
    week_start: date
    week_end: date
    story_date: date


@dataclass
class RobotStoryCountIncrementResult:
    username: str
    event_id: str
    story_date: date
    daily_story_count: int
    week_number: int
    week_start: date
    week_end: date
    weekly_story_count: int
    applied: bool


@dataclass
class RobotCurrentWeekResult:
    username: str
    week_number: int
    week_start: date
    week_end: date
    story_count: int


class RobotStoryProgressService:
    def __init__(self):
        self.root = "robotStoryProgress"
        self.profile_service = UserProfileService()
        self.notification_state_service = FirebaseNotificationStateService()

    def increment_story_count(self, username: str, event_id: str, completed_at_raw: str) -> RobotStoryCountIncrementResult:
        week = self._resolve_week_from_completion(username, completed_at_raw)
        week_ref = get_rtdb_reference(f"{self.root}/{week.caregiver_id}/{week.week_start.isoformat()}")
        result_state: dict[str, object] = {}

        def _transaction_update(current: object):
            node = current if isinstance(current, dict) else {}
            events = dict(node.get("events") or {})
            daily_counts = dict(node.get("dailyCounts") or {})

            existing = events.get(event_id)
            story_date_key = week.story_date.isoformat()
            if isinstance(existing, dict):
                existing_completed_at = str(existing.get("completedAt") or "")
                existing_story_date = str(existing.get("storyDate") or "")
                if existing_completed_at != completed_at_raw or existing_story_date != story_date_key:
                    result_state["conflict"] = True
                    return node

                current_daily_count = self._coerce_non_negative_int(daily_counts.get(story_date_key, 0))
                current_total_count = self._coerce_non_negative_int(node.get("totalCount", 0))
                result_state["applied"] = False
                result_state["daily_story_count"] = current_daily_count
                result_state["weekly_story_count"] = current_total_count
                return node

            current_daily_count = self._coerce_non_negative_int(daily_counts.get(story_date_key, 0)) + 1
            current_total_count = self._coerce_non_negative_int(node.get("totalCount", 0)) + 1

            daily_counts[story_date_key] = current_daily_count
            events[event_id] = {
                "completedAt": completed_at_raw,
                "storyDate": story_date_key,
            }

            node["dailyCounts"] = daily_counts
            node["events"] = events
            node["totalCount"] = current_total_count

            result_state["applied"] = True
            result_state["daily_story_count"] = current_daily_count
            result_state["weekly_story_count"] = current_total_count
            return node

        week_ref.transaction(_transaction_update)

        if result_state.get("conflict"):
            raise RobotStoryProgressConflictError("eventId already exists with different completion data")

        applied = bool(result_state.get("applied"))
        daily_story_count = self._coerce_non_negative_int(result_state.get("daily_story_count", 0))
        weekly_story_count = self._coerce_non_negative_int(result_state.get("weekly_story_count", 0))

        return RobotStoryCountIncrementResult(
            username=week.username,
            event_id=event_id,
            story_date=week.story_date,
            daily_story_count=daily_story_count,
            week_number=week.week_number,
            week_start=week.week_start,
            week_end=week.week_end,
            weekly_story_count=weekly_story_count,
            applied=applied,
        )

    def get_current_week(self, username: str) -> RobotCurrentWeekResult:
        caregiver_id = self.profile_service.get_caregiver_id_by_username(username)
        if caregiver_id is None:
            raise FileNotFoundError(username)

        week = self._resolve_week_for_date(caregiver_id, username, self._local_today(caregiver_id))
        payload = get_rtdb_reference(f"{self.root}/{caregiver_id}/{week.week_start.isoformat()}").get()
        story_count = 0
        if isinstance(payload, dict):
            story_count = self._coerce_non_negative_int(payload.get("totalCount", 0))

        return RobotCurrentWeekResult(
            username=week.username,
            week_number=week.week_number,
            week_start=week.week_start,
            week_end=week.week_end,
            story_count=story_count,
        )

    def get_week_total_for_date(self, caregiver_id: int, target_date: date) -> int:
        profile = self.profile_service.get_profile(caregiver_id)
        if profile is None or profile.robot_condition_range is None:
            return 0
        username = str(profile.username or "").strip() or f"caregiver-{caregiver_id}"
        week = self._resolve_week_for_date(caregiver_id, username, target_date)
        payload = get_rtdb_reference(f"{self.root}/{caregiver_id}/{week.week_start.isoformat()}").get()
        if not isinstance(payload, dict):
            return 0
        return self._coerce_non_negative_int(payload.get("totalCount", 0))

    def get_daily_count_for_date(self, caregiver_id: int, target_date: date) -> int:
        profile = self.profile_service.get_profile(caregiver_id)
        if profile is None or profile.robot_condition_range is None:
            return 0
        username = str(profile.username or "").strip() or f"caregiver-{caregiver_id}"
        week = self._resolve_week_for_date(caregiver_id, username, target_date)
        payload = get_rtdb_reference(f"{self.root}/{caregiver_id}/{week.week_start.isoformat()}").get()
        if not isinstance(payload, dict):
            return 0
        daily_counts = payload.get("dailyCounts") or {}
        if not isinstance(daily_counts, dict):
            return 0
        return self._coerce_non_negative_int(daily_counts.get(target_date.isoformat(), 0))

    def _resolve_week_from_completion(self, username: str, completed_at_raw: str) -> RobotWeekWindow:
        caregiver_id = self.profile_service.get_caregiver_id_by_username(username)
        if caregiver_id is None:
            raise FileNotFoundError(username)
        completed_at = self._parse_completed_at(completed_at_raw)
        timezone_name = self._timezone_for_caregiver(caregiver_id)
        story_date = completed_at.astimezone(self._safe_zoneinfo(timezone_name)).date()
        return self._resolve_week_for_date(caregiver_id, username, story_date)

    def _resolve_week_for_date(self, caregiver_id: int, username: str, target_date: date) -> RobotWeekWindow:
        profile = self.profile_service.get_profile(caregiver_id)
        if profile is None or profile.robot_condition_range is None:
            raise FileNotFoundError(caregiver_id)

        range_start = date.fromisoformat(profile.robot_condition_range.startDate)
        range_end = date.fromisoformat(profile.robot_condition_range.endDate)
        if not (range_start <= target_date <= range_end):
            raise PermissionError("Story completion date is outside the configured robot deployment range")

        delta_days = (target_date - range_start).days
        week_number = (delta_days // 7) + 1
        week_start = range_start + timedelta(days=(week_number - 1) * 7)
        week_end = min(week_start + timedelta(days=6), range_end)
        return RobotWeekWindow(
            caregiver_id=caregiver_id,
            username=username,
            timezone_name=self._timezone_for_caregiver(caregiver_id),
            week_number=week_number,
            week_start=week_start,
            week_end=week_end,
            story_date=target_date,
        )

    def _local_today(self, caregiver_id: int) -> date:
        timezone_name = self._timezone_for_caregiver(caregiver_id)
        return datetime.now(self._safe_zoneinfo(timezone_name)).date()

    def _timezone_for_caregiver(self, caregiver_id: int) -> str:
        settings = self.notification_state_service.get_reminder(caregiver_id)
        if isinstance(settings, dict) and settings.get("timezone"):
            return str(settings["timezone"])
        return "UTC"

    def _safe_zoneinfo(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _parse_completed_at(self, completed_at_raw: str) -> datetime:
        normalized = completed_at_raw.replace("Z", "+00:00")
        try:
            completed_at = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("completedAt must be a valid ISO 8601 datetime with UTC offset") from exc
        if completed_at.tzinfo is None:
            raise ValueError("completedAt must include a UTC offset")
        return completed_at

    def _coerce_non_negative_int(self, value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0
