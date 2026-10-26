"""Thin projection of the US market owner's EOD distribution into existing slots."""

from copy import deepcopy
import json

from app.us_market.sector_distribution import USSectorDistributionRead


US_DISTRIBUTION_CAPABILITIES = frozenset({"market.sectors", "market.hot_groups", "market.breadth"})

# This is an outward evidence projection, not a second aggregation. Full counts
# and quality always describe the materialized universe, even when rows are cut.
US_GROUP_LIMIT = 5
US_GROUP_BYTES = 5000


def _project_groups(groups: list, limit: int) -> tuple[list[dict], dict]:
    selected = []
    used = 2
    for group in groups[:min(limit, US_GROUP_LIMIT)]:
        item = group.model_dump(mode="json", exclude={"members"})
        item["members"] = deepcopy(group.members[:1])
        item["members_truncated"] = group.members_truncated or len(group.members) > 1
        size = len(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8")) + 1
        if used + size > US_GROUP_BYTES:
            item["members"] = []
            item["members_truncated"] = bool(group.members) or group.members_truncated
            size = len(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8")) + 1
        if used + size > US_GROUP_BYTES:
            break
        selected.append(item)
        used += size
    return selected, {"available_count": len(groups), "returned_count": len(selected),
                      "truncated": len(selected) < len(groups)}


def merge_us_distribution_context(result: dict, snapshot: USSectorDistributionRead,
                                  requested: set[str], parameters: dict | None = None,
                                  limits: dict | None = None) -> dict:
    output = deepcopy(result)
    payload = snapshot.model_dump(mode="json", exclude={"sectors", "industries", "hot_groups"})
    data = output.setdefault("data", {})
    compact = data.setdefault("compact", {})
    output.setdefault("kind", "market_overview")
    output.setdefault("as_of", payload["as_of"])
    output.setdefault("generated_at", payload["evaluated_at"])
    source = {"type": "resolved_market_data", "name": "us.market.eod_distribution"}
    output.setdefault("source_refs", []).append(source)
    output.setdefault("warnings", []).extend(payload["limitations"])
    output["freshness"] = {"status": payload["status"], "as_of": payload["as_of"],
                           "is_current": payload["freshness_status"] == "current", "warnings": payload["limitations"],
                           "decision_usable": False}
    for capability in sorted(requested & US_DISTRIBUTION_CAPABILITIES):
        value = dict(payload)
        limit = max(0, int((limits or {}).get(capability, US_GROUP_LIMIT)))
        projection = {}
        value["schema_version"] = f"us.{capability}.v1"
        value["kind"] = "us_eod_market_distribution"
        value["facts_usable"] = snapshot.counts.comparable > 0
        value["coverage_status"] = "partial" if snapshot.counts.comparable else "missing"
        value["ranking_scope"] = "canonical_completed_session_universe"
        value["warnings"] = payload["limitations"]
        value["session_semantics"] = "latest_completed_session"
        # TW's indicative lane has no US equivalent. Never silently substitute EOD.
        unsupported_lane = ((parameters or {}).get(capability) or {}).get("lane") == "indicative"
        if unsupported_lane:
            value.update(status="unavailable", facts_usable=False)
            value["warnings"] = [*value["warnings"], "US_INDICATIVE_LANE_NOT_SUPPORTED"]
        if capability == "market.sectors":
            for key, groups in (("items", snapshot.sectors), ("industries", snapshot.industries)):
                value[key], projection[key] = _project_groups(groups, 0 if unsupported_lane else limit)
            path = ("market", "sectors")
        elif capability == "market.hot_groups":
            value["groups"], projection["groups"] = _project_groups(snapshot.hot_groups, 0 if unsupported_lane else limit)
            value["group_count"] = len(snapshot.hot_groups)
            path = ("screening", "hot_groups")
        else:
            path = ("breadth",)
        value["group_projection"] = projection
        value["truncated"] = any(item["truncated"] for item in projection.values())
        value["projection_policy"] = {"group_limit": US_GROUP_LIMIT, "member_limit": 1,
                                      "group_list_max_bytes": US_GROUP_BYTES,
                                      "aggregate_scope": "full_materialized_universe"}
        freshness = {"status": value["status"], "as_of": value["as_of"],
                     "freshness_status": value["freshness_status"], "decision_usable": False,
                     "facts_usable": value["facts_usable"], "refresh_recommended": False,
                     "reason": "US_EOD_MARKET_SNAPSHOT_LIMITED_EVIDENCE", "source_refs": [source]}
        for container in (data, compact):
            parent = container
            for part in path[:-1]:
                parent = parent.setdefault(part, {})
            parent[path[-1]] = deepcopy(value)
            container.setdefault("freshness_by_capability", {})[capability] = deepcopy(freshness)
            container.setdefault("slots", {})[capability.replace(".", "_")] = {
                "status": value["status"], "as_of": value["as_of"], "freshness": deepcopy(freshness),
                "payload_ref": ".".join(path), "warnings": value["warnings"],
            }
    return output
