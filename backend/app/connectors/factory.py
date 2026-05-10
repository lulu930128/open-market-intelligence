from app.connectors.base import BaseConnector
from app.connectors.http_api_connector import HttpAPIConnector
from app.db.models import SourceRegistry


class UnsupportedConnectorError(Exception):
    pass


def get_connector(source: SourceRegistry) -> BaseConnector:
    if source.source_type in {"api", "rss", "feed"}:
        return HttpAPIConnector()

    raise UnsupportedConnectorError(
        f"Unsupported source_type='{source.source_type}'."
    )