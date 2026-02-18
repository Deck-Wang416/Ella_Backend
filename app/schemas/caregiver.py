from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CaregiverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class CaregiverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    timezone: str
    created_at: datetime


class ChildCreate(BaseModel):
    caregiver_id: int
    name: str = Field(min_length=1, max_length=100)


class ChildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    caregiver_id: int
    name: str
    created_at: datetime
