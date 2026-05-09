from datetime import datetime

from app.connectors.base import BaseConnector, FetchResult


class TWSEConnector(BaseConnector):
    source_name = "twse"

    def fetch(self) -> FetchResult:
        return FetchResult(
            source_name=self.source_name,
            fetched_at=datetime.now(),
            status="not_implemented",
        )
