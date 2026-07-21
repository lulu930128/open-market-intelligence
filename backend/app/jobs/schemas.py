from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobRunRead(BaseModel):
    id: int
    job_type: str
    status: str
    public_status: str | None = None
    target: str | None = None

    progress_current: int
    progress_total: int

    message: str | None = None
    error_message: str | None = None

    request: Any = None
    result: Any = None

    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    updated_at: datetime
