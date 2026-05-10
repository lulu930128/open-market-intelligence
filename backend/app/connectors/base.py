from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.db.models import SourceRegistry


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FetchResult:
    source_name: str
    fetched_at: datetime
    status: str

    url: str | None = None
    method: str = "GET"
    status_code: int | None = None
    content_type: str | None = None

    raw_text: str | None = None
    raw_payload: Any | None = None

    message: str | None = None
    error_message: str | None = None


class BaseConnector(ABC):
    connector_name: str

    @abstractmethod
    def fetch(self, source: SourceRegistry) -> FetchResult:
        """Fetch raw data from source."""
        raise NotImplementedError