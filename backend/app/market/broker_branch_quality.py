from __future__ import annotations

from datetime import date, datetime
import json
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    BrokerBranchSnapshotQuality,
    BrokerBranchTradeDaily,
    RawFetchResult,
    SourceRegistry,
    utc_now,
)


BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N = "ranked_top_n"
BROKER_BRANCH_COVERAGE_MODE_FULL_DAILY = "full_daily"
BROKER_BRANCH_COVERAGE_MODE_PARTIAL_PROVIDER = "partial_provider"
BROKER_BRANCH_COVERAGE_MODE_UNKNOWN = "unknown"

BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED = "unknown_not_ranked"
BROKER_BRANCH_ABSENCE_CONFIRMED_ABSENT = "confirmed_absent"
BROKER_BRANCH_ABSENCE_UNKNOWN = "unknown"

BROKER_BRANCH_COVERAGE_CENSORED = "censored"
BROKER_BRANCH_COVERAGE_COMPLETE = "complete"
BROKER_BRANCH_COVERAGE_PARTIAL = "partial"
BROKER_BRANCH_COVERAGE_READY_EMPTY = "ready_empty"
BROKER_BRANCH_COVERAGE_INVALID = "invalid"
BROKER_BRANCH_COVERAGE_MISSING = "missing"
BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE = "provider_failure"

BROKER_BRANCH_FETCH_SUCCESS = "success"
BROKER_BRANCH_FETCH_EMPTY = "empty"
BROKER_BRANCH_FETCH_PARTIAL = "partial"
BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH = "provider_date_mismatch"
BROKER_BRANCH_FETCH_PROVIDER_FAILURE = "provider_failure"
BROKER_BRANCH_FETCH_INVALID = "invalid"

NSTOCK_BROKER_BRANCH_CONTRACT_VERSION = "nstock_broker_branch_top15.v1"
NSTOCK_BROKER_BRANCH_RANK_LIMIT = 15

_COVERAGE_MODES = {
    BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
    BROKER_BRANCH_COVERAGE_MODE_FULL_DAILY,
    BROKER_BRANCH_COVERAGE_MODE_PARTIAL_PROVIDER,
    BROKER_BRANCH_COVERAGE_MODE_UNKNOWN,
}
_ABSENCE_SEMANTICS = {
    BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
    BROKER_BRANCH_ABSENCE_CONFIRMED_ABSENT,
    BROKER_BRANCH_ABSENCE_UNKNOWN,
}
_COVERAGE_STATUSES = {
    BROKER_BRANCH_COVERAGE_CENSORED,
    BROKER_BRANCH_COVERAGE_COMPLETE,
    BROKER_BRANCH_COVERAGE_PARTIAL,
    BROKER_BRANCH_COVERAGE_READY_EMPTY,
    BROKER_BRANCH_COVERAGE_INVALID,
    BROKER_BRANCH_COVERAGE_MISSING,
    BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE,
}
_FETCH_STATUSES = {
    BROKER_BRANCH_FETCH_SUCCESS,
    BROKER_BRANCH_FETCH_EMPTY,
    BROKER_BRANCH_FETCH_PARTIAL,
    BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH,
    BROKER_BRANCH_FETCH_PROVIDER_FAILURE,
    BROKER_BRANCH_FETCH_INVALID,
}


def _normalized_warnings(warnings: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in warnings or ():
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _validate_quality_state(
    *,
    coverage_mode: str,
    absence_semantics: str,
    coverage_status: str,
    fetch_status: str,
    observed_branch_count: int,
    buy_rank_limit: int | None,
    sell_rank_limit: int | None,
) -> None:
    if coverage_mode not in _COVERAGE_MODES:
        raise ValueError(f"Unsupported broker-branch coverage mode: {coverage_mode}")
    if absence_semantics not in _ABSENCE_SEMANTICS:
        raise ValueError(
            f"Unsupported broker-branch absence semantics: {absence_semantics}"
        )
    if coverage_status not in _COVERAGE_STATUSES:
        raise ValueError(
            f"Unsupported broker-branch coverage status: {coverage_status}"
        )
    if fetch_status not in _FETCH_STATUSES:
        raise ValueError(f"Unsupported broker-branch fetch status: {fetch_status}")
    if int(observed_branch_count) < 0:
        raise ValueError("observed_branch_count must be non-negative")
    if buy_rank_limit is not None and int(buy_rank_limit) <= 0:
        raise ValueError("buy_rank_limit must be positive when provided")
    if sell_rank_limit is not None and int(sell_rank_limit) <= 0:
        raise ValueError("sell_rank_limit must be positive when provided")
    if (
        coverage_mode == BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N
        and coverage_status
        in {BROKER_BRANCH_COVERAGE_COMPLETE, BROKER_BRANCH_COVERAGE_READY_EMPTY}
    ):
        raise ValueError(
            "ranked_top_n observations cannot claim complete or ready_empty coverage"
        )
    if (
        absence_semantics == BROKER_BRANCH_ABSENCE_CONFIRMED_ABSENT
        and coverage_mode != BROKER_BRANCH_COVERAGE_MODE_FULL_DAILY
    ):
        raise ValueError(
            "confirmed_absent semantics require a verified full_daily contract"
        )


def upsert_broker_branch_snapshot_quality(
    db: Session,
    *,
    source_id: int,
    stock_id: str,
    expected_trade_date: date,
    provider_trade_date: date | None,
    fetched_at: datetime | None,
    coverage_mode: str,
    buy_rank_limit: int | None,
    sell_rank_limit: int | None,
    observed_branch_count: int,
    absence_semantics: str,
    coverage_status: str,
    fetch_status: str,
    source_contract_version: str,
    raw_result_id: int | None = None,
    includes_block_trades: bool | None = None,
    warnings: Iterable[str] | None = None,
) -> BrokerBranchSnapshotQuality:
    """Mutate selected snapshot-quality state without owning the transaction."""
    normalized_stock_id = str(stock_id).strip()
    if not normalized_stock_id:
        raise ValueError("stock_id is required")
    if int(source_id) <= 0:
        raise ValueError("source_id must be positive")
    normalized_contract = str(source_contract_version).strip()
    if not normalized_contract:
        raise ValueError("source_contract_version is required")

    _validate_quality_state(
        coverage_mode=coverage_mode,
        absence_semantics=absence_semantics,
        coverage_status=coverage_status,
        fetch_status=fetch_status,
        observed_branch_count=observed_branch_count,
        buy_rank_limit=buy_rank_limit,
        sell_rank_limit=sell_rank_limit,
    )

    row = (
        db.query(BrokerBranchSnapshotQuality)
        .filter(BrokerBranchSnapshotQuality.source_id == int(source_id))
        .filter(BrokerBranchSnapshotQuality.stock_id == normalized_stock_id)
        .filter(
            BrokerBranchSnapshotQuality.expected_trade_date
            == expected_trade_date
        )
        .one_or_none()
    )
    if row is None:
        row = BrokerBranchSnapshotQuality(
            source_id=int(source_id),
            stock_id=normalized_stock_id,
            expected_trade_date=expected_trade_date,
        )
        db.add(row)

    row.raw_result_id = raw_result_id
    row.provider_trade_date = provider_trade_date
    row.fetched_at = fetched_at or utc_now()
    row.coverage_mode = coverage_mode
    row.buy_rank_limit = buy_rank_limit
    row.sell_rank_limit = sell_rank_limit
    row.observed_branch_count = int(observed_branch_count)
    row.absence_semantics = absence_semantics
    row.coverage_status = coverage_status
    row.fetch_status = fetch_status
    row.source_contract_version = normalized_contract
    row.includes_block_trades = includes_block_trades
    row.warnings_json = json.dumps(
        _normalized_warnings(warnings),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    db.flush()
    return row


def reconcile_nstock_snapshot_quality_from_trade_rows(
    db: Session,
    *,
    source_name: str,
    expected_trade_date: date,
    stock_ids: Iterable[str] | None = None,
    max_stocks: int = 2500,
) -> dict[str, int | str]:
    """Materialize missing TopN quality state from already persisted trade rows.

    The caller owns commit/rollback. This reconciliation is deliberately bounded
    to one expected session and at most ``max_stocks`` distinct symbols.
    """
    limit = max(1, min(int(max_stocks), 2500))
    requested_stock_ids = list(
        dict.fromkeys(
            item
            for item in (str(value).strip() for value in stock_ids or ())
            if item
        )
    )[:limit]

    sources = (
        db.query(SourceRegistry.id)
        .filter(SourceRegistry.source_name == str(source_name).strip())
        .order_by(SourceRegistry.id.asc())
        .all()
    )
    source_ids = [int(item[0]) for item in sources]
    if not source_ids:
        return {
            "status": "source_missing",
            "candidate_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
        }

    candidate_query = (
        db.query(BrokerBranchTradeDaily.stock_id)
        .filter(BrokerBranchTradeDaily.source_id.in_(source_ids))
        .filter(BrokerBranchTradeDaily.trade_date == expected_trade_date)
    )
    if requested_stock_ids:
        candidate_query = candidate_query.filter(
            BrokerBranchTradeDaily.stock_id.in_(requested_stock_ids)
        )
    candidate_stock_ids = [
        str(item[0])
        for item in (
            candidate_query.distinct()
            .order_by(BrokerBranchTradeDaily.stock_id.asc())
            .limit(limit)
            .all()
        )
    ]
    if not candidate_stock_ids:
        return {
            "status": "no_trade_rows",
            "candidate_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
        }

    existing_by_key = {
        (int(item[0]), str(item[1])): (item[2], str(item[3]))
        for item in (
            db.query(
                BrokerBranchSnapshotQuality.source_id,
                BrokerBranchSnapshotQuality.stock_id,
                BrokerBranchSnapshotQuality.raw_result_id,
                BrokerBranchSnapshotQuality.coverage_status,
            )
            .filter(BrokerBranchSnapshotQuality.source_id.in_(source_ids))
            .filter(
                BrokerBranchSnapshotQuality.expected_trade_date
                == expected_trade_date
            )
            .filter(BrokerBranchSnapshotQuality.stock_id.in_(candidate_stock_ids))
            .all()
        )
    }

    aggregates = (
        db.query(
            BrokerBranchTradeDaily.source_id,
            BrokerBranchTradeDaily.stock_id,
            BrokerBranchTradeDaily.raw_result_id,
            func.count(BrokerBranchTradeDaily.id),
            RawFetchResult.fetched_at,
        )
        .outerjoin(
            RawFetchResult,
            RawFetchResult.id == BrokerBranchTradeDaily.raw_result_id,
        )
        .filter(BrokerBranchTradeDaily.source_id.in_(source_ids))
        .filter(BrokerBranchTradeDaily.trade_date == expected_trade_date)
        .filter(BrokerBranchTradeDaily.stock_id.in_(candidate_stock_ids))
        .group_by(
            BrokerBranchTradeDaily.source_id,
            BrokerBranchTradeDaily.stock_id,
            BrokerBranchTradeDaily.raw_result_id,
            RawFetchResult.fetched_at,
        )
        .order_by(
            BrokerBranchTradeDaily.source_id.asc(),
            BrokerBranchTradeDaily.stock_id.asc(),
            BrokerBranchTradeDaily.raw_result_id.desc(),
        )
        .all()
    )

    created_count = 0
    updated_count = 0
    skipped_count = 0
    selected_keys: set[tuple[int, str]] = set()
    for source_id, stock_id, raw_result_id, row_count, fetched_at in aggregates:
        key = (int(source_id), str(stock_id))
        if key in selected_keys:
            continue
        selected_keys.add(key)
        existing = existing_by_key.get(key)
        if (
            existing is not None
            and existing[0] == raw_result_id
            and existing[1]
            in {
                BROKER_BRANCH_COVERAGE_CENSORED,
                BROKER_BRANCH_COVERAGE_PARTIAL,
            }
        ):
            skipped_count += 1
            continue
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=key[0],
            raw_result_id=int(raw_result_id) if raw_result_id is not None else None,
            stock_id=key[1],
            expected_trade_date=expected_trade_date,
            provider_trade_date=expected_trade_date,
            fetched_at=fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=int(row_count),
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=BROKER_BRANCH_COVERAGE_CENSORED,
            fetch_status=BROKER_BRANCH_FETCH_SUCCESS,
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(
                "ranked_top_n_absence_is_censored",
                "reconciled_from_existing_trade_rows",
                "includes_block_trades_unverified",
            ),
        )
        if existing is None:
            created_count += 1
        else:
            updated_count += 1

    return {
        "status": "completed",
        "candidate_count": len(candidate_stock_ids),
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
    }
