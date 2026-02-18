from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReminderSettingUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    reminder_times: list[str] = Field(default_factory=lambda: ["18:00", "21:00"], min_length=1)
    enabled: bool = True

    @field_validator("reminder_times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 5 or value[2] != ":":
                raise ValueError("reminder_times must use HH:MM format")
            hh, mm = value.split(":")
            if not (hh.isdigit() and mm.isdigit()):
                raise ValueError("reminder_times must use HH:MM format")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError("reminder_times contains invalid time")
        return sorted(set(values))


class ReminderSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caregiver_id: int
    timezone: str
    reminder_times: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
