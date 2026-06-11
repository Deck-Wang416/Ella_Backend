class RobotIdentityService:
    def __init__(self):
        self._username_to_caregiver_id = {
            "leyun": 1,
            "yoonjae": 2,
        }

    def resolve_caregiver_id(self, username: str) -> int | None:
        normalized = username.strip().lower()
        if not normalized:
            return None
        return self._username_to_caregiver_id.get(normalized)
