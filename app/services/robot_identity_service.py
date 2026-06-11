from app.services.user_profile_service import UserProfileService


class RobotIdentityService:
    def __init__(self):
        self.profile_service = UserProfileService()

    def resolve_caregiver_id(self, username: str) -> int | None:
        return self.profile_service.get_caregiver_id_by_username(username)
