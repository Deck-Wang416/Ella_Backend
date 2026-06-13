from datetime import date, datetime, timedelta, timezone

from app.core.firebase_client import get_rtdb_reference
from app.schemas.daily import ConditionType
from app.schemas.profile import ConditionRange, UserProfileContent


class UserProfileService:
    def __init__(self):
        self.root = "userProfiles"

    def get_profile(self, caregiver_id: int) -> UserProfileContent | None:
        ref = get_rtdb_reference(f"{self.root}/{caregiver_id}")
        payload = ref.get()
        if not isinstance(payload, dict):
            return None
        payload.setdefault("caregiverId", caregiver_id)
        profile = UserProfileContent.model_validate(payload)
        profile.dayCount = self._compute_day_count(profile)
        return profile

    def upsert_profile(
        self,
        caregiver_id: int,
        username: str | None,
        themes: list[str] | None,
        robot_condition_range: ConditionRange | None,
        parent_condition_range: ConditionRange | None,
    ) -> UserProfileContent:
        self._validate_ranges(robot_condition_range, parent_condition_range)
        existing = self.get_profile(caregiver_id)
        resolved_username = self._normalize_username(username)
        if resolved_username is None and existing is not None:
            resolved_username = existing.username
        resolved_themes = self._normalize_themes(themes)
        if resolved_themes is None and existing is not None:
            resolved_themes = existing.themes
        elif resolved_themes is None:
            resolved_themes = []

        payload = UserProfileContent(
            caregiverId=caregiver_id,
            username=resolved_username,
            themes=resolved_themes,
            dayCount=None,
            robot_condition_range=robot_condition_range,
            parent_condition_range=parent_condition_range,
            updatedAt=datetime.now(timezone.utc),
        )
        get_rtdb_reference(f"{self.root}/{caregiver_id}").set(
            payload.model_dump(mode="json", exclude_none=True)
        )
        payload.dayCount = self._compute_day_count(payload)
        return payload

    def get_caregiver_id_by_username(self, username: str) -> int | None:
        normalized = self._normalize_username(username)
        if normalized is None:
            return None

        payload = get_rtdb_reference(self.root).get()
        if isinstance(payload, list):
            iterable = enumerate(payload)
        elif isinstance(payload, dict):
            iterable = payload.items()
        else:
            return None

        for raw_caregiver_id, raw_profile in iterable:
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

    def _validate_ranges(
        self,
        robot_condition_range: ConditionRange | None,
        parent_condition_range: ConditionRange | None,
    ) -> None:
        robot_bounds = self._normalized_bounds(robot_condition_range)
        parent_bounds = self._normalized_bounds(parent_condition_range)
        if robot_bounds and parent_bounds:
            robot_start, robot_end = robot_bounds
            parent_start, parent_end = parent_bounds
            if not (robot_end < parent_start or parent_end < robot_start):
                raise ValueError("robot_condition_range and parent_condition_range must not overlap")

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

    def _compute_day_count(self, profile: UserProfileContent) -> int | None:
        today = datetime.now(timezone.utc).date()
        active_range: ConditionRange | None = None
        if self._date_in_range(today, profile.robot_condition_range):
            active_range = profile.robot_condition_range
        elif self._date_in_range(today, profile.parent_condition_range):
            active_range = profile.parent_condition_range

        if active_range is None:
            return None

        start = date.fromisoformat(active_range.startDate)
        return (today - start).days + 1
