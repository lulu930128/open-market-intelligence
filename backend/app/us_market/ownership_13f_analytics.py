from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import groupby
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    USSec13FFiling,
    USSec13FManager,
    USSec13FSymbolQuarter,
    USSec13FWarehousePartition,
    USSecDatasetRelease,
    USSecurityIdentifierMap,
    USStockMaster,
)
from app.us_market.errors import USStockNotFoundError
from app.us_market.ownership_13f_manifest import load_cached_13f_manifest
from app.us_market.sec_ownership.form13f_warehouse import (
    iter_13f_parquet_context,
    query_13f_parquet_context,
)
from app.us_market.sources import normalize_us_symbol


CONTRACT_VERSION = "omi.sec.13f.v1"
EFFECTIVE_FILING_STATUSES = ("effective_base", "effective_additive")
LIMITATIONS = [
    "Form 13F is a delayed quarterly filing and is not a current-position feed.",
    "Reported value preserves the SEC raw unit and is normalized to US dollars using the filing-date rule; no market-price recomputation is implied.",
    "Confidential treatment, other included managers, shared discretion, options, and amendments can limit direct manager comparison.",
    "CUSIP-to-symbol output is shown only when the versioned mapping is approved; unresolved identifiers remain visible in coverage.",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal(0)


def _text(value: Decimal | int | None) -> str | None:
    return None if value is None else format(value, "f")


def _quarter(value: date) -> str:
    return f"{value.year}Q{((value.month - 1) // 3) + 1}"


def _current_partitions(db: Session) -> list[USSec13FWarehousePartition]:
    return (
        db.query(USSec13FWarehousePartition)
        .filter(
            USSec13FWarehousePartition.is_current.is_(True),
            USSec13FWarehousePartition.status == "completed",
        )
        .order_by(USSec13FWarehousePartition.period_key.asc())
        .all()
    )


def _approved_mapping_pairs(
    db: Session,
    *,
    symbols: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    version = str(settings.openfigi_mapping_version)
    query = db.query(USSecurityIdentifierMap).filter(
        USSecurityIdentifierMap.mapping_version == version,
        USSecurityIdentifierMap.status == "approved",
        USSecurityIdentifierMap.symbol.isnot(None),
    )
    normalized_symbols = sorted({normalize_us_symbol(item) for item in symbols or []})
    if normalized_symbols:
        query = query.filter(USSecurityIdentifierMap.symbol.in_(normalized_symbols))
    candidates: dict[str, set[str]] = defaultdict(set)
    for row in query.all():
        if row.symbol:
            candidates[row.identifier_value].add(row.symbol)
    return sorted(
        (cusip, next(iter(mapped_symbols)))
        for cusip, mapped_symbols in candidates.items()
        if len(mapped_symbols) == 1
    )


def _filing_context(
    db: Session,
    partitions: list[USSec13FWarehousePartition],
    *,
    manager_id: int | None = None,
    primary_period_only: bool = True,
) -> list[tuple[str, int, int, str, str]]:
    release_ids = [item.dataset_release_id for item in partitions]
    if not release_ids:
        return []
    query = db.query(USSec13FFiling).filter(
        USSec13FFiling.dataset_release_id.in_(release_ids)
    )
    if manager_id is not None:
        query = query.filter(USSec13FFiling.manager_id == manager_id)
    filings = query.all()
    primary_periods: dict[int, date] = {}
    if primary_period_only:
        counts: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        for item in filings:
            if item.effective_status not in EFFECTIVE_FILING_STATUSES:
                continue
            period = item.report_calendar_or_quarter or item.period_of_report
            counts[item.dataset_release_id][period] += 1
        primary_periods = {
            release_id: max(period_counts, key=lambda period: (period_counts[period], period))
            for release_id, period_counts in counts.items()
            if period_counts
        }
    return [
        (
            item.accession_number,
            item.manager_id,
            item.dataset_release_id,
            (item.report_calendar_or_quarter or item.period_of_report).isoformat(),
            item.effective_status,
        )
        for item in filings
        if not primary_period_only
        or (item.report_calendar_or_quarter or item.period_of_report)
        == primary_periods.get(item.dataset_release_id)
    ]


def _aggregate_rows(
    db: Session,
    *,
    symbols: Iterable[str] | None = None,
    manager_id: int | None = None,
) -> Iterable[dict[str, Any]]:
    partitions = _current_partitions(db)
    mappings = _approved_mapping_pairs(db, symbols=symbols)
    normalized_symbols = sorted({normalize_us_symbol(item) for item in symbols or []})
    where = ["f.effective_status IN ('effective_base', 'effective_additive')"]
    parameters: list[Any] = []
    if normalized_symbols:
        where.append("m.symbol IN (" + ",".join("?" for _ in normalized_symbols) + ")")
        parameters.extend(normalized_symbols)
    if manager_id is not None:
        where.append("f.manager_id = ?")
        parameters.append(manager_id)
    mapping_join = "JOIN identifier_map m ON m.cusip = h.cusip"
    if manager_id is not None and not normalized_symbols:
        mapping_join = "LEFT JOIN identifier_map m ON m.cusip = h.cusip"
    return iter_13f_parquet_context(
        [Path(item.holdings_path) for item in partitions],
        f"""
        SELECT
          m.symbol,
          f.manager_id,
          max(f.dataset_release_id) AS source_release_id,
          f.report_period,
          count(*)::BIGINT AS reported_row_count,
          coalesce(sum(h.shares_or_principal) FILTER (
            WHERE h.put_call IS NULL AND h.shares_or_principal_type = 'SH'
          ), 0) AS reported_long_shares,
          coalesce(sum(h.reported_value_usd) FILTER (WHERE h.put_call IS NULL), 0)
            AS reported_long_value_usd,
          coalesce(sum(h.reported_value_usd) FILTER (WHERE h.put_call = 'PUT'), 0)
            AS reported_put_value_usd,
          coalesce(sum(h.reported_value_usd) FILTER (WHERE h.put_call = 'CALL'), 0)
            AS reported_call_value_usd
        FROM holdings h
        JOIN filing_context f ON f.accession_number = h.accession_number
        {mapping_join}
        WHERE {' AND '.join(where)}
        GROUP BY m.symbol, f.manager_id, f.report_period
        ORDER BY m.symbol, f.report_period, f.manager_id
        """,
        identifier_mappings=mappings,
        filing_context=_filing_context(db, partitions, manager_id=manager_id),
        parameters=parameters,
        memory_limit=str(settings.us_sec_13f_projection_memory_limit),
        temp_directory=Path(settings.us_sec_13f_projection_temp_path),
    )


def _coverage(
    db: Session,
    *,
    prefer_materialized: bool = True,
) -> dict[str, Any]:
    partitions = _current_partitions(db)
    mappings = _approved_mapping_pairs(db)
    materialized = None
    if prefer_materialized:
        materialized = (
            db.query(USSec13FSymbolQuarter)
            .filter(
                USSec13FSymbolQuarter.mapping_version
                == str(settings.openfigi_mapping_version),
            )
            .order_by(USSec13FSymbolQuarter.computed_at.desc())
            .first()
        )
    if materialized is not None:
        total_rows = sum(item.row_count for item in partitions)
        total_value = sum(
            (_decimal(item.total_reported_value_usd_text) for item in partitions),
            Decimal(0),
        )
        unresolved_rows = min(max(int(materialized.unresolved_row_count), 0), total_rows)
        unresolved_value = min(
            max(_decimal(materialized.unresolved_value_usd_text), Decimal(0)),
            total_value,
        )
        mapped_rows = max(total_rows - unresolved_rows, 0)
        mapped_value = max(total_value - unresolved_value, Decimal(0))
        return {
            "total_rows": total_rows,
            "mapped_rows": mapped_rows,
            "unresolved_rows": unresolved_rows,
            "total_value_usd": _text(total_value),
            "mapped_value_usd": _text(mapped_value),
            "unresolved_value_usd": _text(unresolved_value),
            "row_coverage": mapped_rows / total_rows if total_rows else 0.0,
            "value_coverage": float(mapped_value / total_value) if total_value else 0.0,
            "approved_identifier_count": len(mappings),
            "basis": "materialized_symbol_projection",
            "computed_at": materialized.computed_at.isoformat(),
        }
    rows = query_13f_parquet_context(
        [Path(item.holdings_path) for item in partitions],
        """
        SELECT
          count(*)::BIGINT AS total_rows,
          count(*) FILTER (WHERE m.symbol IS NOT NULL)::BIGINT AS mapped_rows,
          coalesce(sum(h.reported_value_usd), 0) AS total_value,
          coalesce(sum(h.reported_value_usd) FILTER (WHERE m.symbol IS NOT NULL), 0)
            AS mapped_value
        FROM holdings h
        LEFT JOIN identifier_map m ON m.cusip = h.cusip
        """,
        identifier_mappings=mappings,
    )
    row = rows[0] if rows else {}
    total_rows = int(row.get("total_rows") or 0)
    mapped_rows = int(row.get("mapped_rows") or 0)
    total_value = _decimal(row.get("total_value"))
    mapped_value = _decimal(row.get("mapped_value"))
    return {
        "total_rows": total_rows,
        "mapped_rows": mapped_rows,
        "unresolved_rows": max(total_rows - mapped_rows, 0),
        "total_value_usd": _text(total_value),
        "mapped_value_usd": _text(mapped_value),
        "unresolved_value_usd": _text(max(total_value - mapped_value, Decimal(0))),
        "row_coverage": mapped_rows / total_rows if total_rows else 0.0,
        "value_coverage": float(mapped_value / total_value) if total_value else 0.0,
        "approved_identifier_count": len(mappings),
        "basis": "warehouse_scan",
        "computed_at": None,
    }


def _manager_projection_items(
    *,
    current: dict[int, dict[str, Decimal]],
    previous: dict[int, dict[str, Decimal]] | None,
    managers: dict[int, dict[str, str | None]],
    report_period: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    total_value = sum((item["value"] for item in current.values()), Decimal(0))
    items: list[dict[str, Any]] = []
    for manager_id, current_position in current.items():
        previous_position = previous.get(manager_id) if previous is not None else None
        prior_shares = previous_position["shares"] if previous_position else Decimal(0)
        share_change = current_position["shares"] - prior_shares
        direction = (
            "not_observed"
            if previous is None
            else "new"
            if previous_position is None
            else "increased"
            if share_change > 0
            else "reduced"
            if share_change < 0
            else "unchanged"
        )
        manager = managers.get(manager_id)
        items.append(
            {
                "manager_cik": manager.get("cik") if manager else None,
                "manager_name": (
                    manager.get("name") if manager else f"Manager {manager_id}"
                ),
                "report_period_end": report_period,
                "reported_long_shares": _text(current_position["shares"]),
                "reported_value_usd": _text(current_position["value"]),
                "prior_reported_long_shares": (
                    _text(previous_position["shares"]) if previous_position else None
                ),
                "reported_long_shares_change": (
                    _text(share_change) if previous_position else None
                ),
                "direction": direction,
                "reported_value_share": (
                    float(current_position["value"] / total_value) if total_value else 0.0
                ),
            }
        )
    items.sort(key=lambda item: _decimal(item["reported_value_usd"]), reverse=True)
    return items[:limit]


def rebuild_13f_symbol_quarter_projections(
    db: Session,
    *,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    requested_symbols = sorted({normalize_us_symbol(item) for item in symbols or []})
    mapping_pairs = _approved_mapping_pairs(db, symbols=requested_symbols or None)
    projection_symbols = sorted({symbol for _cusip, symbol in mapping_pairs})
    rows = _aggregate_rows(db, symbols=requested_symbols or None)
    # A rebuild must scan the warehouse against the latest approved mapping set.
    # Reusing the previous materialized coverage here would carry stale coverage
    # into every newly written projection row.
    coverage = _coverage(db, prefer_materialized=False)
    mapping_version = str(settings.openfigi_mapping_version)
    staging_prefix = f"{mapping_version}.staging."
    projection_temp_root = Path(settings.us_sec_13f_projection_temp_path)
    projection_temp_root.mkdir(parents=True, exist_ok=True)
    projection_path = projection_temp_root / f"symbol-quarter-{uuid4().hex}.jsonl"
    stocks = {
        row.symbol: row.cik
        for row in db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(projection_symbols or ["<none>"]))
        .all()
    }
    managers = {
        row.id: {"cik": row.cik, "name": row.name}
        for row in db.query(USSec13FManager).all()
    }
    db.expunge_all()
    # All DB-backed inputs are now copied into plain Python values. Release the
    # read transaction and checked-out connection before the long DuckDB scan so
    # API polling and unrelated jobs do not exhaust the SQLAlchemy pool.
    db.rollback()
    inserted = 0
    written_symbols: set[str] = set()
    previous_symbol: str | None = None
    previous_positions: dict[int, dict[str, Decimal]] | None = None
    try:
        with projection_path.open("w", encoding="utf-8", newline="\n") as output:
            for (symbol, period), period_rows in groupby(
                rows,
                key=lambda row: (
                    str(row.get("symbol") or ""),
                    str(row["report_period"]),
                ),
            ):
                if not symbol:
                    continue
                current: dict[int, dict[str, Decimal]] = {}
                source_release_id = 0
                reported_row_count = 0
                long_shares = Decimal(0)
                long_value = Decimal(0)
                put_value = Decimal(0)
                call_value = Decimal(0)
                for row in period_rows:
                    manager_id = int(row["manager_id"])
                    manager_long_shares = _decimal(row["reported_long_shares"])
                    manager_long_value = _decimal(row["reported_long_value_usd"])
                    manager_put_value = _decimal(row["reported_put_value_usd"])
                    manager_call_value = _decimal(row["reported_call_value_usd"])
                    current[manager_id] = {
                        "shares": manager_long_shares,
                        "value": (
                            manager_long_value
                            + manager_put_value
                            + manager_call_value
                        ),
                    }
                    source_release_id = max(
                        source_release_id,
                        int(row["source_release_id"]),
                    )
                    reported_row_count += int(row["reported_row_count"])
                    long_shares += manager_long_shares
                    long_value += manager_long_value
                    put_value += manager_put_value
                    call_value += manager_call_value

                previous = previous_positions if previous_symbol == symbol else None
                if previous is None:
                    new_count = increased_count = reduced_count = exited_count = None
                else:
                    new_count = sum(
                        1 for manager in current if manager not in previous
                    )
                    increased_count = sum(
                        1
                        for manager, value in current.items()
                        if manager in previous
                        and value["shares"] > previous[manager]["shares"]
                    )
                    reduced_count = sum(
                        1
                        for manager, value in current.items()
                        if manager in previous
                        and value["shares"] < previous[manager]["shares"]
                    )
                    exited_count = sum(
                        1 for manager in previous if manager not in current
                    )
                top_managers = _manager_projection_items(
                    current=current,
                    previous=previous,
                    managers=managers,
                    report_period=period,
                )
                payload = {
                    "symbol": symbol,
                    "issuer_cik": stocks.get(symbol),
                    "report_quarter": _quarter(date.fromisoformat(period)),
                    "report_period_end": period,
                    "mapping_version": mapping_version,
                    "source_release_id": source_release_id,
                    "reporting_manager_count": len(current),
                    "reported_row_count": reported_row_count,
                    "reported_long_shares_text": _text(long_shares),
                    "reported_long_value_usd_text": _text(long_value),
                    "reported_put_value_usd_text": _text(put_value),
                    "reported_call_value_usd_text": _text(call_value),
                    "new_manager_count": new_count,
                    "increased_manager_count": increased_count,
                    "reduced_manager_count": reduced_count,
                    "exited_manager_count": exited_count,
                    "mapping_row_coverage": coverage["row_coverage"],
                    "mapping_value_coverage": coverage["value_coverage"],
                    "unresolved_row_count": coverage["unresolved_rows"],
                    "unresolved_value_usd_text": coverage["unresolved_value_usd"],
                    "status": (
                        "current" if coverage["row_coverage"] >= 0.999 else "partial"
                    ),
                    "limitations_json": _json(LIMITATIONS),
                    "top_managers_json": _json(top_managers),
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                }
                output.write(_json(payload) + "\n")
                inserted += 1
                written_symbols.add(symbol)
                previous_symbol = symbol
                previous_positions = current

        db.rollback()
        db.query(USSec13FSymbolQuarter).filter(
            USSec13FSymbolQuarter.mapping_version.like(f"{staging_prefix}%")
        ).delete(synchronize_session=False)
        live_query = db.query(USSec13FSymbolQuarter).filter(
            USSec13FSymbolQuarter.mapping_version == mapping_version
        )
        if requested_symbols:
            live_query = live_query.filter(
                USSec13FSymbolQuarter.symbol.in_(requested_symbols)
            )
        live_query.delete(synchronize_session=False)
        batch: list[dict[str, Any]] = []
        with projection_path.open("r", encoding="utf-8") as source:
            for line in source:
                payload = json.loads(line)
                payload["report_period_end"] = date.fromisoformat(
                    payload["report_period_end"]
                )
                payload["computed_at"] = datetime.fromisoformat(payload["computed_at"])
                batch.append(payload)
                if len(batch) >= 1_000:
                    db.execute(insert(USSec13FSymbolQuarter), batch)
                    batch.clear()
            if batch:
                db.execute(insert(USSec13FSymbolQuarter), batch)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        projection_path.unlink(missing_ok=True)
    return {
        "status": "current" if inserted else "ready_empty",
        "mapping_version": mapping_version,
        "symbol_count": len(written_symbols),
        "projection_count": inserted,
        "coverage": coverage,
    }


def get_13f_symbol_contract(
    db: Session,
    *,
    symbol: str,
    manager_limit: int = 50,
) -> dict[str, Any]:
    if manager_limit < 1 or manager_limit > 100:
        raise ValueError("manager_limit must be between 1 and 100.")
    normalized = normalize_us_symbol(symbol)
    stock = db.query(USStockMaster).filter(USStockMaster.symbol == normalized).first()
    if stock is None:
        raise USStockNotFoundError(f"US symbol='{normalized}' was not found.")
    projections = (
        db.query(USSec13FSymbolQuarter)
        .filter(
            USSec13FSymbolQuarter.symbol == normalized,
            USSec13FSymbolQuarter.mapping_version == str(settings.openfigi_mapping_version),
        )
        .order_by(USSec13FSymbolQuarter.report_period_end.asc())
        .all()
    )
    partitions = _current_partitions(db)
    releases = {
        row.id: row
        for row in db.query(USSecDatasetRelease)
        .filter(
            USSecDatasetRelease.id.in_(
                [item.dataset_release_id for item in partitions] or [-1]
            )
        )
        .all()
    }
    if not projections:
        return {
            "contract_version": CONTRACT_VERSION,
            "symbol": normalized,
            "cik": stock.cik,
            "status": "missing",
            "as_of": None,
            "freshness": {
                "status": "missing",
                "latest_release_period": partitions[-1].period_key if partitions else None,
                "reason": "No approved CUSIP-to-symbol projection is available for this symbol.",
            },
            "summary": {},
            "quarters": [],
            "managers": [],
            "quality": {"decision_usable": False, "limitations": LIMITATIONS},
            "source_refs": [
                {"period_key": item.period_key, "source_url": releases[item.dataset_release_id].source_url}
                for item in partitions
                if item.dataset_release_id in releases
            ],
        }

    latest_projection = projections[-1]
    try:
        parsed_managers = json.loads(latest_projection.top_managers_json or "[]")
        manager_items = parsed_managers if isinstance(parsed_managers, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        manager_items = []
    quarters = [
        {
            "report_quarter": item.report_quarter,
            "report_period_end": item.report_period_end.isoformat(),
            "reporting_manager_count": item.reporting_manager_count,
            "reported_row_count": item.reported_row_count,
            "reported_long_shares": item.reported_long_shares_text,
            "reported_long_value_usd": item.reported_long_value_usd_text,
            "reported_put_value_usd": item.reported_put_value_usd_text,
            "reported_call_value_usd": item.reported_call_value_usd_text,
            "new_manager_count": item.new_manager_count,
            "increased_manager_count": item.increased_manager_count,
            "reduced_manager_count": item.reduced_manager_count,
            "exited_manager_count": item.exited_manager_count,
            "status": item.status,
        }
        for item in projections
    ]
    latest = projections[-1]
    return {
        "contract_version": CONTRACT_VERSION,
        "symbol": normalized,
        "cik": stock.cik,
        "status": latest.status,
        "as_of": latest.computed_at.isoformat(),
        "freshness": {
            "status": "current",
            "latest_release_period": partitions[-1].period_key if partitions else None,
            "latest_report_period_end": latest.report_period_end.isoformat(),
            "basis": "latest_promoted_sec_form13f_dataset_release",
            "is_delayed_quarterly_filing": True,
        },
        "summary": quarters[-1],
        "quarters": quarters,
        "managers": manager_items[:manager_limit],
        "quality": {
            "decision_usable": True,
            "mapping_version": latest.mapping_version,
            "mapping_row_coverage": latest.mapping_row_coverage,
            "mapping_value_coverage": latest.mapping_value_coverage,
            "unresolved_row_count": latest.unresolved_row_count,
            "unresolved_value_usd": latest.unresolved_value_usd_text,
            "limitations": LIMITATIONS,
        },
        "source_refs": [
            {
                "period_key": item.period_key,
                "source_url": releases[item.dataset_release_id].source_url,
                "source_sha256": item.source_sha256,
                "holdings_sha256": item.holdings_sha256,
            }
            for item in partitions
            if item.dataset_release_id in releases
        ],
    }


def get_13f_coverage_contract(db: Session) -> dict[str, Any]:
    partitions = _current_partitions(db)
    release_ids = [item.dataset_release_id for item in partitions]
    releases = {
        row.id: row
        for row in db.query(USSecDatasetRelease)
        .filter(USSecDatasetRelease.id.in_(release_ids or [-1]))
        .all()
    }
    coverage = _coverage(db)
    manifest = load_cached_13f_manifest()
    manifest_entries = (
        [item for item in manifest.get("entries") or [] if isinstance(item, dict)]
        if manifest
        else []
    )
    completed_urls = {
        releases[item.dataset_release_id].source_url
        for item in partitions
        if item.dataset_release_id in releases
    }
    completed_manifest_count = sum(
        1 for item in manifest_entries if str(item.get("source_url") or "") in completed_urls
    )
    status_counts = {
        status: int(count)
        for status, count in db.query(
            USSecurityIdentifierMap.status,
            func.count(USSecurityIdentifierMap.id),
        )
        .filter(
            USSecurityIdentifierMap.mapping_version == str(settings.openfigi_mapping_version)
        )
        .group_by(USSecurityIdentifierMap.status)
        .all()
    }
    status = "current" if partitions and coverage["row_coverage"] >= 0.999 else "partial" if partitions else "missing"
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "warehouse": {
            "schema_version": "omi.sec.13f.parquet.v3",
            "partition_count": len(partitions),
            "row_count": sum(item.row_count for item in partitions),
            "file_size_bytes": sum(item.file_size_bytes for item in partitions),
            "storage_budget_bytes": int(float(settings.us_sec_13f_storage_budget_gb) * 1024**3),
            "manifest": {
                "status": (
                    "missing"
                    if not manifest
                    else "current"
                    if completed_manifest_count == len(manifest_entries)
                    else "partial"
                ),
                "contract_version": manifest.get("contract_version") if manifest else None,
                "checked_at": manifest.get("checked_at") if manifest else None,
                "source_url": manifest.get("source_url") if manifest else None,
                "manifest_sha256": manifest.get("manifest_sha256") if manifest else None,
                "expected_release_count": len(manifest_entries),
                "completed_release_count": completed_manifest_count,
                "pending_release_count": max(len(manifest_entries) - completed_manifest_count, 0),
            },
            "partitions": [
                {
                    "period_key": item.period_key,
                    "row_count": item.row_count,
                    "distinct_cusip_count": item.distinct_cusip_count,
                    "file_size_bytes": item.file_size_bytes,
                    "source_sha256": item.source_sha256,
                    "holdings_sha256": item.holdings_sha256,
                    "source_url": releases[item.dataset_release_id].source_url
                    if item.dataset_release_id in releases
                    else None,
                }
                for item in partitions
            ],
        },
        "mapping": {
            "mapping_version": str(settings.openfigi_mapping_version),
            "status_counts": status_counts,
            **coverage,
        },
        "quality": {
            "decision_usable": bool(partitions),
            "limitations": LIMITATIONS,
        },
    }


__all__ = [
    "CONTRACT_VERSION",
    "LIMITATIONS",
    "get_13f_coverage_contract",
    "get_13f_symbol_contract",
    "rebuild_13f_symbol_quarter_projections",
]
