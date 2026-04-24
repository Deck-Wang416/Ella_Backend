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
        return UserProfileContent.model_validate(payload)

    def upsert_profile(
        self,
        caregiver_id: int,
        robot_condition_range: ConditionRange | None,
        parent_condition_range: ConditionRange | None,
    ) -> UserProfileContent:
        self._validate_ranges(robot_condition_range, parent_condition_range)
        payload = UserProfileContent(
            caregiverId=caregiver_id,
            robot_condition_range=robot_condition_range,
            parent_condition_range=parent_condition_range,
            updatedAt=datetime.now(timezone.utc),
        )
        get_rtdb_reference(f"{self.root}/{caregiver_id}").set(
            payload.model_dump(mode="json", exclude_none=True)
        )
        return payload

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
