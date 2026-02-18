from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ELLA Reminder Backend"
    env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"

    database_url: str = "sqlite:///./ella.db"
    daily_data_dir: str = "./data/daily"

    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    internal_api_key: str = ""
    notification_max_retries: int = 2

    web_push_dry_run: bool = True
    web_push_vapid_public_key: str = ""
    web_push_vapid_private_key: str = ""
    web_push_vapid_claims_sub: str = ""

    mobile_push_dry_run: bool = True

    cors_allow_all: bool = False
    cors_origins_raw: str = Field(default="http://localhost:3000,http://localhost:5173", alias="CORS_ORIGINS")
    trusted_hosts_raw: str = Field(default="*", alias="TRUSTED_HOSTS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def cors_origins(self) -> List[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    @property
    def trusted_hosts(self) -> List[str]:
        return [item.strip() for item in self.trusted_hosts_raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
