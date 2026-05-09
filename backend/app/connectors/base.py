from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class FetchResult:
    source_name: str
    fetched_at: datetime
    status: str
    raw_payload: Any | None = None
    error_message: str | None = None


class BaseConnector(ABC):
    source_name: str

    @abstractmethod
    def fetch(self) -> FetchResult:
        """Fetch raw data from source."""
        raise NotImplementedError
