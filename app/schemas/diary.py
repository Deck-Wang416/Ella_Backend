from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DiaryEntryUpdate(BaseModel):
    submitted: bool
    responses: dict[str, Any] | None = None


class DiaryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    child_id: int
    entry_date: date
    submitted: bool
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
    responses: dict[str, Any] | None = None
