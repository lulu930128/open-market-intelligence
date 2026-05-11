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

class SourceRunRead(BaseModel):
    source_id: int
    source_name: str

    fetch_log_id: int
    raw_result_id: int | None = None

    data_quality_status: str | None = None
    data_quality_message: str | None = None
    data_quality_row_count: int | None = None
    is_duplicate: bool | None = None

    status: str
    status_code: int | None = None
    content_hash: str | None = None

    duration_ms: int | None = None

    message: str | None = None
    error_message: str | None = None

    fetched_at: datetime


class FetchLogRead(BaseModel):
    id: int

    source_id: int | None = None
    job_name: str
    status: str

    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None

    message: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RawFetchResultListRead(BaseModel):
    id: int

    source_id: int
    fetch_log_id: int | None = None

    fetched_at: datetime

    url: str | None = None
    method: str
    status_code: int | None = None
    content_type: str | None = None
    content_hash: str | None = None

    raw_text_length: int | None = None
    parser_version: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RawFetchResultRead(BaseModel):
    id: int

    source_id: int
    fetch_log_id: int | None = None

    fetched_at: datetime

    url: str | None = None
    method: str
    status_code: int | None = None
    content_type: str | None = None
    content_hash: str | None = None

    raw_text_preview: str | None = None
    raw_text_length: int | None = None
    raw_text_truncated: bool = False

    raw_file_path: str | None = None
    parser_version: str | None = None
    error_message: str | None = None


class SourceRefreshRead(BaseModel):
    source_id: int
    source_name: str

    fetch_status: str
    fetch_log_id: int
    raw_result_id: int | None = None

    data_quality_status: str | None = None
    data_quality_message: str | None = None
    data_quality_row_count: int | None = None
    is_duplicate: bool | None = None

    parse_status: str | None = None
    parser_type: str | None = None
    parsed_count: int | None = None
    skipped_count: int | None = None
    inserted_count: int | None = None

    message: str | None = None
    error_message: str | None = None

    fetched_at: datetime | None = None


class SourceStatusRead(BaseModel):
    id: int
    source_name: str
    source_type: str
    category: str

    enabled: bool
    parser_type: str | None = None
    reliability_level: str

    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None

    total_fetch_count: int
    success_fetch_count: int
    error_fetch_count: int
    raw_result_count: int

    latest_fetch_log_id: int | None = None
    latest_fetch_status: str | None = None
    latest_fetch_message: str | None = None
    latest_fetch_error_message: str | None = None
    latest_fetch_duration_ms: int | None = None

    latest_raw_result_id: int | None = None
    latest_raw_status_code: int | None = None
    latest_raw_content_hash: str | None = None


class DataQualityCheckRead(BaseModel):
    id: int

    source_id: int
    fetch_log_id: int | None = None
    raw_result_id: int | None = None

    status: str
    check_name: str
    message: str

    row_count: int | None = None
    is_duplicate: bool
    detail_json: str | None = None

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)