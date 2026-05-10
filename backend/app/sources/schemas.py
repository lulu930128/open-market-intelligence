from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceBase(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=120)
    source_type: str = Field(..., min_length=1, max_length=50)
    category: str = Field(..., min_length=1, max_length=80)

    endpoint_url: str | None = None
    enabled: bool = True

    fetch_interval_minutes: int | None = None
    priority: int = 100

    parser_type: str | None = None
    auth_type: str = "none"
    reliability_level: str = "unknown"


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    source_name: str | None = Field(default=None, min_length=1, max_length=120)
    source_type: str | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, min_length=1, max_length=80)

    endpoint_url: str | None = None
    enabled: bool | None = None

    fetch_interval_minutes: int | None = None
    priority: int | None = None

    parser_type: str | None = None
    auth_type: str | None = None
    reliability_level: str | None = None


class SourceRead(SourceBase):
    id: int

    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)