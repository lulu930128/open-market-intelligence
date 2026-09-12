"""Pure Taiwan breadth coverage projection shared by outward consumers."""

from collections.abc import Mapping
from typing import Any


def project_breadth_coverage(raw: Mapping[str, Any]) -> dict[str, Any]:
    directions = {key: int(raw.get(f"{key}_count") or 0)
                  for key in ("advance", "decline", "unchanged")}
    classified = sum(directions.values())
    universe = int(raw.get("total_count", raw.get("universe_count", classified)))
    missing = raw.get("not_received_count", raw.get("missing_count"))
    missing = int(missing) if missing is not None else None
    unclassified = raw.get("received_unclassified_count")
    if unclassified is None and missing is not None:
        unclassified = universe - classified - missing
    unclassified = int(unclassified) if unclassified is not None else None
    if min(universe, classified, *(directions.values())) < 0 or classified > universe:
        raise ValueError("invalid breadth universe/direction partition")
    if missing is not None and (missing < 0 or missing > universe - classified):
        raise ValueError("invalid breadth missing partition")
    if unclassified is not None and (
        unclassified < 0 or unclassified > universe - classified
        or missing is not None and classified + unclassified + missing != universe
    ):
        raise ValueError("invalid breadth received partition")
    summary = dict(classified=classified, received_unclassified=unclassified,
                   not_received=missing)
    details = dict(raw.get("coverage_reason_counts") or {})
    if details:
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in details.values()):
            raise ValueError("invalid breadth reason count")
        if sum(details.values()) != universe or any(details.get(k) != v for k, v in directions.items()):
            raise ValueError("breadth reasons must reconcile to universe and directions")
        if missing is not None and details.get("provider_missing", 0) != missing:
            raise ValueError("breadth reasons must reconcile to missing")
    return {
        "classification_summary": summary,
        "classification_reason_counts": details,
        "received_count": universe - missing if missing is not None else None,
        "received_coverage_ratio": (universe - missing) / universe if universe and missing is not None else None,
        "classified_coverage_ratio": classified / universe if universe else None,
    }
