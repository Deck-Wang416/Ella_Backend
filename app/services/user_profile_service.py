from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import ConditionType
from app.schemas.profile import ConditionRange, UserProfileContent
from app.services.firebase_notification_state_service import FirebaseNotificationStateService


class UserProfileService:
    def __init__(self):
        self.root = "userProfiles"
        self.notification_state_service = FirebaseNotificationStateService()

    def get_profile(self, caregiver_id: int) -> UserProfileContent | None:
        ref = get_rtdb_reference(f"{self.root}/{caregiver_id}")
        payload = ref.get()
        if not isinstance(payload, dict):
            return None
        payload.setdefault("caregiverId", caregiver_id)
        profile = UserProfileContent.model_validate(payload)
        self._apply_mode_scoped_fields(caregiver_id, profile)
        profile.dayCount = self._compute_day_count(caregiver_id, profile)
        return profile

    def update_themes(
        self,
        caregiver_id: int,
        themes: list[str],
    ) -> UserProfileContent:
        ref = get_rtdb_reference(f"{self.root}/{caregiver_id}")
        raw_payload = ref.get()
        if not isinstance(raw_payload, dict):
            raise FileNotFoundError(caregiver_id)
        raw_payload.setdefault("caregiverId", caregiver_id)
        existing = UserProfileContent.model_validate(raw_payload)
        self._apply_mode_scoped_fields(caregiver_id, existing)
        if self._active_condition_for_today(caregiver_id, existing) != "robot":
            raise ValueError("Themes can only be updated during robot mode")
        resolved_themes = self._normalize_themes(themes) or []

        raw_payload["themes"] = resolved_themes
        raw_payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
        ref.set(raw_payload)

        payload = UserProfileContent.model_validate(raw_payload)
        self._apply_mode_scoped_fields(caregiver_id, payload)
        payload.dayCount = self._compute_day_count(caregiver_id, payload)
        return payload

    def get_caregiver_id_by_username(self, username: str) -> int | None:
        normalized = self._normalize_username(username)
        if normalized is None:
            return None

        for raw_caregiver_id, raw_profile in self._iter_profiles():
            if not isinstance(raw_profile, dict):
                continue
            profile_username = self._normalize_username(raw_profile.get("username"))
            if profile_username != normalized:
                continue
            try:
                return int(raw_profile.get("caregiverId", raw_caregiver_id))
            except (TypeError, ValueError):
                continue
        return None

    def authenticate(self, username: str, password: str) -> UserProfileContent | None:
        normalized = self._normalize_username(username)
        if normalized is None:
            return None

        for raw_caregiver_id, raw_profile in self._iter_profiles():
            if not isinstance(raw_profile, dict):
                continue
            profile_username = self._normalize_username(raw_profile.get("username"))
            if profile_username != normalized:
                continue
            if str(raw_profile.get("password") or "") != password:
                return None
            try:
                caregiver_id = int(raw_profile.get("caregiverId", raw_caregiver_id))
            except (TypeError, ValueError):
                continue
            return self.get_profile(caregiver_id)
        return None

    def resolve_condition_for_date(self, caregiver_id: int, target_date: date) -> ConditionType | None:
        profile = self.get_profile(caregiver_id)
        if profile is None:
            return None

        robot_hit = self._date_in_range(target_date, profile.robot_condition_range)
        parent_hit = self._date_in_range(target_date, profile.parent_condition_range)

        if robot_hit and parent_hit:
            raise ValueError("robot_condition_range and parent_condition_range must not overlap")
        if robot_hit:
            return "robot"
        if parent_hit:
            return "parent"
        return None

    def list_scheduled_dates(self, caregiver_id: int) -> list[date]:
        profile = self.get_profile(caregiver_id)
        if profile is None:
            return []

        days: set[date] = set()
        for rng in (profile.robot_condition_range, profile.parent_condition_range):
            if rng is None:
                continue
            start = date.fromisoformat(rng.startDate)
            end = date.fromisoformat(rng.endDate)
            current = start
            while current <= end:
                days.add(current)
                current += timedelta(days=1)
        return sorted(days)

    def _normalized_bounds(self, rng: ConditionRange | None) -> tuple[date, date] | None:
        if rng is None:
            return None
        start = date.fromisoformat(rng.startDate)
        end = date.fromisoformat(rng.endDate)
        if end < start:
            raise ValueError("Condition range endDate must be on or after startDate")
        return start, end

    def _date_in_range(self, target_date: date, rng: ConditionRange | None) -> bool:
        bounds = self._normalized_bounds(rng)
        if bounds is None:
            return False
        start, end = bounds
        return start <= target_date <= end

    def _normalize_username(self, username: str | None) -> str | None:
        if username is None:
            return None
        normalized = username.strip().lower()
        return normalized or None

    def _normalize_themes(self, themes: list[str] | None) -> list[str] | None:
        if themes is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for theme in themes:
            cleaned = str(theme).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    def _iter_profiles(self):
        payload = get_rtdb_reference(self.root).get()
        if isinstance(payload, list):
            return enumerate(payload)
        if isinstance(payload, dict):
            return payload.items()
        return ()

    def _compute_day_count(self, caregiver_id: int, profile: UserProfileContent) -> int | None:
        today = self._local_today(caregiver_id)
        active_range: ConditionRange | None = None
        if self._active_condition_for_date(today, profile) == "robot":
            active_range = profile.robot_condition_range
        elif self._active_condition_for_date(today, profile) == "parent":
            active_range = profile.parent_condition_range

        if active_range is None:
            return None

        start = date.fromisoformat(active_range.startDate)
        return (today - start).days + 1

    def _apply_mode_scoped_fields(self, caregiver_id: int, profile: UserProfileContent) -> None:
        if self._active_condition_for_today(caregiver_id, profile) != "robot":
            profile.themes = []

    def _active_condition_for_today(
        self,
        caregiver_id: int,
        profile: UserProfileContent,
    ) -> ConditionType | None:
        return self._active_condition_for_date(self._local_today(caregiver_id), profile)

    def _active_condition_for_date(
        self,
        target_date: date,
        profile: UserProfileContent,
    ) -> ConditionType | None:
        robot_hit = self._date_in_range(target_date, profile.robot_condition_range)
        parent_hit = self._date_in_range(target_date, profile.parent_condition_range)
        if robot_hit and parent_hit:
            raise ValueError("robot_condition_range and parent_condition_range must not overlap")
        if robot_hit:
            return "robot"
        if parent_hit:
            return "parent"
        return None

    def _local_today(self, caregiver_id: int) -> date:
        timezone_name = "UTC"
        settings = self.notification_state_service.get_reminder(caregiver_id)
        if isinstance(settings, dict) and settings.get("timezone"):
            timezone_name = str(settings["timezone"])
        try:
            return datetime.now(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError:
            return datetime.now(timezone.utc).date()
