from dataclasses import dataclass
from datetime import date, datetime
import logging

import requests
from sqlalchemy.orm import Session

from app.db.models import (
    BrokerBranchSnapshotQuality,
    BrokerBranchTradeDaily,
    RawFetchResult,
    SourceRegistry,
)
from app.market.broker_branch_quality import (
    BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
    BROKER_BRANCH_COVERAGE_CENSORED,
    BROKER_BRANCH_COVERAGE_INVALID,
    BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
    BROKER_BRANCH_COVERAGE_PARTIAL,
    BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE,
    BROKER_BRANCH_FETCH_EMPTY,
    BROKER_BRANCH_FETCH_INVALID,
    BROKER_BRANCH_FETCH_PARTIAL,
    BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH,
    BROKER_BRANCH_FETCH_PROVIDER_FAILURE,
    BROKER_BRANCH_FETCH_SUCCESS,
    NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
    NSTOCK_BROKER_BRANCH_RANK_LIMIT,
    upsert_broker_branch_snapshot_quality,
)
from app.market.providers import http_get
from app.market.taiwan_rules import TAIWAN_BROKER_BRANCH_RELEASE_TIME
from app.market.trading_calendar import latest_released_trading_day
from app.parsers.twse_common import parse_date, parse_float, parse_int
from app.utils.hash import sha256_text


NSTOCK_BRANCH_TOP15_URL = "https://shop.nstock.tw/api/v2/branch-data/branch-top15_ad"
NSTOCK_BRANCH_SOURCE_NAME = "nStock Broker Branch Top 15"
BRANCH_DAILY_READY_TIME = TAIWAN_BROKER_BRANCH_RELEASE_TIME


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrokerBranchFetchResult:
    url: str
    status_code: int
    content_type: str | None
    raw_text: str
    payload: object | None


class BrokerBranchFetchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_kind: str = "provider_failure",
        fetch_result: BrokerBranchFetchResult | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.fetch_result = fetch_result


def _get_or_create_source(db: Session) -> SourceRegistry:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == NSTOCK_BRANCH_SOURCE_NAME)
        .first()
    )

    if source is not None:
        return source

    source = SourceRegistry(
        source_name=NSTOCK_BRANCH_SOURCE_NAME,
        source_type="http_api",
        category="broker_branch_trade",
        endpoint_url=NSTOCK_BRANCH_TOP15_URL,
        enabled=True,
        parser_type="nstock_broker_branch_top15",
        reliability_level="third_party",
    )
    db.add(source)
    db.flush()
    return source


def _fetch_nstock_branch_top15(stock_id: str) -> BrokerBranchFetchResult:
    try:
        response = http_get(
            NSTOCK_BRANCH_TOP15_URL,
            params={"stock_id": stock_id},
            headers={
                "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise BrokerBranchFetchError(
            f"分點資料來源連線失敗：{exc}",
            failure_kind="provider_failure",
        ) from exc

    transport_result = BrokerBranchFetchResult(
        url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        raw_text=response.text,
        payload=None,
    )
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BrokerBranchFetchError(
            f"分點資料來源連線失敗：{exc}",
            failure_kind="provider_failure",
            fetch_result=transport_result,
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise BrokerBranchFetchError(
            "分點資料來源回傳格式不是有效 JSON。",
            failure_kind="invalid",
            fetch_result=transport_result,
        ) from exc

    return BrokerBranchFetchResult(
        url=transport_result.url,
        status_code=transport_result.status_code,
        content_type=transport_result.content_type,
        raw_text=transport_result.raw_text,
        payload=payload,
    )


def _source_url(stock_id: str) -> str:
    return f"{NSTOCK_BRANCH_TOP15_URL}?stock_id={stock_id}"


def _source_label(payload_data: dict) -> str:
    return f"nStock branch top15 ({payload_data.get('顯示') or 'net'})"


def _row_key(row: dict) -> str:
    return str(row.get("分點代號") or row.get("分點名稱") or "").strip()


def _parse_branch_rows(payload_data: dict) -> list[dict]:
    trade_date = parse_date(payload_data.get("更新日期"))

    if trade_date is None:
        raise ValueError("Broker branch payload does not contain a valid update date.")

    stock_id = str(payload_data.get("股票代號") or "").strip()

    if not stock_id:
        raise ValueError("Broker branch payload does not contain a stock id.")

    stock_name = str(payload_data.get("股票名稱") or "").strip() or None
    source_label = _source_label(payload_data)
    rows_by_branch: dict[str, dict] = {}

    def ensure_row(row: dict) -> dict | None:
        branch_key = _row_key(row)

        if not branch_key:
            return None

        current = rows_by_branch.get(branch_key)

        if current is None:
            current = {
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "branch_code": str(row.get("分點代號") or "").strip(),
                "branch_name": str(row.get("分點名稱") or "").strip(),
                "buy_lots": parse_int(row.get("買張")),
                "sell_lots": parse_int(row.get("賣張")),
                "net_lots": None,
                "buy_avg_price": parse_float(row.get("買均價")),
                "sell_avg_price": parse_float(row.get("賣均價")),
                "buy_rank": None,
                "sell_rank": None,
                "source_label": source_label,
            }
            rows_by_branch[branch_key] = current

        return current

    for row in payload_data.get("買超top15") or []:
        if not isinstance(row, dict):
            continue

        current = ensure_row(row)

        if current is None:
            continue

        current["buy_rank"] = parse_int(row.get("買超排名"))
        current["net_lots"] = parse_int(row.get("買超"))
        current["buy_lots"] = parse_int(row.get("買張"))
        current["sell_lots"] = parse_int(row.get("賣張"))
        current["buy_avg_price"] = parse_float(row.get("買均價"))
        current["sell_avg_price"] = parse_float(row.get("賣均價"))

    for row in payload_data.get("賣超top15") or []:
        if not isinstance(row, dict):
            continue

        current = ensure_row(row)

        if current is None:
            continue

        current["sell_rank"] = parse_int(row.get("賣超排名"))
        current["net_lots"] = parse_int(row.get("賣超"))
        current["buy_lots"] = parse_int(row.get("買張"))
        current["sell_lots"] = parse_int(row.get("賣張"))
        current["buy_avg_price"] = parse_float(row.get("買均價"))
        current["sell_avg_price"] = parse_float(row.get("賣均價"))

    return list(rows_by_branch.values())


def _add_raw_fetch_result(
    db: Session,
    *,
    source_id: int,
    fetch_result: BrokerBranchFetchResult,
    error_message: str | None = None,
) -> RawFetchResult:
    raw_result = RawFetchResult(
        source_id=source_id,
        url=fetch_result.url,
        method="GET",
        status_code=fetch_result.status_code,
        content_type=fetch_result.content_type,
        content_hash=sha256_text(fetch_result.raw_text),
        raw_text=fetch_result.raw_text,
        parser_version="nstock_broker_branch_top15_v2",
        error_message=error_message,
    )
    db.add(raw_result)
    db.flush()
    return raw_result


def _base_quality_warnings() -> list[str]:
    return [
        "ranked_top_n_absence_is_censored",
        "includes_block_trades_unverified",
    ]


def _commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _normalize_observation_rows(rows: list[dict]) -> tuple[list[dict], int]:
    normalized: list[dict] = []
    invalid_identity_count = 0
    for row in rows:
        branch_code = str(row.get("branch_code") or "").strip()
        if not branch_code:
            invalid_identity_count += 1
            continue
        item = dict(row)
        item["branch_code"] = branch_code
        item["branch_name"] = str(item.get("branch_name") or "").strip()
        if item.get("buy_lots") == 0:
            item["buy_avg_price"] = None
        if item.get("sell_lots") == 0:
            item["sell_avg_price"] = None
        normalized.append(item)
    return normalized, invalid_identity_count


def _persist_fetch_failure_quality(
    db: Session,
    *,
    source: SourceRegistry,
    stock_id: str,
    expected_trade_date: date,
    error: BrokerBranchFetchError,
) -> None:
    """Persist failure evidence without replacing an already usable selection."""
    try:
        raw_result = None
        if error.fetch_result is not None:
            raw_result = _add_raw_fetch_result(
                db,
                source_id=source.id,
                fetch_result=error.fetch_result,
                error_message=str(error),
            )

        selected = (
            db.query(BrokerBranchSnapshotQuality)
            .filter(BrokerBranchSnapshotQuality.source_id == source.id)
            .filter(BrokerBranchSnapshotQuality.stock_id == stock_id)
            .filter(
                BrokerBranchSnapshotQuality.expected_trade_date
                == expected_trade_date
            )
            .one_or_none()
        )
        if selected is None or not (
            selected.coverage_status
            in {
                BROKER_BRANCH_COVERAGE_CENSORED,
                BROKER_BRANCH_COVERAGE_PARTIAL,
            }
            and selected.observed_branch_count > 0
        ):
            is_invalid = error.failure_kind == "invalid"
            upsert_broker_branch_snapshot_quality(
                db,
                source_id=source.id,
                raw_result_id=raw_result.id if raw_result is not None else None,
                stock_id=stock_id,
                expected_trade_date=expected_trade_date,
                provider_trade_date=None,
                fetched_at=(
                    raw_result.fetched_at if raw_result is not None else None
                ),
                coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
                buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
                sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
                observed_branch_count=0,
                absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
                coverage_status=(
                    BROKER_BRANCH_COVERAGE_INVALID
                    if is_invalid
                    else BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE
                ),
                fetch_status=(
                    BROKER_BRANCH_FETCH_INVALID
                    if is_invalid
                    else BROKER_BRANCH_FETCH_PROVIDER_FAILURE
                ),
                source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
                includes_block_trades=None,
                warnings=(*_base_quality_warnings(), error.failure_kind),
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to persist broker-branch failure quality stock_id=%s "
            "expected_trade_date=%s.",
            stock_id,
            expected_trade_date,
            exc_info=True,
        )


def probe_broker_branch_release(stock_id: str = "2330") -> dict:
    """Read the provider's latest release date without mutating local storage."""
    fetch_result = _fetch_nstock_branch_top15(stock_id=stock_id)
    payload_data = (
        fetch_result.payload.get("data")
        if isinstance(fetch_result.payload, dict)
        else None
    )

    if not isinstance(payload_data, dict):
        raise BrokerBranchFetchError("分點資料來源回傳格式缺少 data 物件。")

    fetched_trade_date = parse_date(payload_data.get("更新日期"))
    if fetched_trade_date is None:
        raise BrokerBranchFetchError(
            "Broker branch payload does not contain a valid update date."
        )

    try:
        rows = _parse_branch_rows(payload_data)
    except ValueError as exc:
        raise BrokerBranchFetchError(str(exc)) from exc

    return {
        "stock_id": stock_id,
        "trade_date": fetched_trade_date,
        "row_count": len(rows),
        "source_url": fetch_result.url,
    }


def fetch_and_store_broker_branch_daily(
    db: Session,
    *,
    stock_id: str,
    requested_trade_date: date | None = None,
    force: bool = False,
) -> list[BrokerBranchTradeDaily]:
    source = _get_or_create_source(db)
    expected_trade_date = requested_trade_date or expected_broker_branch_trade_date()
    try:
        fetch_result = _fetch_nstock_branch_top15(stock_id=stock_id)
    except BrokerBranchFetchError as exc:
        _persist_fetch_failure_quality(
            db,
            source=source,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            error=exc,
        )
        raise

    raw_result = _add_raw_fetch_result(
        db,
        source_id=source.id,
        fetch_result=fetch_result,
    )
    payload_data = (
        fetch_result.payload.get("data")
        if isinstance(fetch_result.payload, dict)
        else None
    )

    if not isinstance(payload_data, dict):
        error = BrokerBranchFetchError(
            "分點資料來源回傳格式缺少 data 物件。",
            failure_kind="invalid",
            fetch_result=fetch_result,
        )
        raw_result.error_message = str(error)
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=None,
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=0,
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=BROKER_BRANCH_COVERAGE_INVALID,
            fetch_status=BROKER_BRANCH_FETCH_INVALID,
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(*_base_quality_warnings(), "missing_data_object"),
        )
        _commit_or_rollback(db)
        raise error

    try:
        parsed_rows = _parse_branch_rows(payload_data)
    except ValueError as exc:
        error = BrokerBranchFetchError(
            str(exc),
            failure_kind="invalid",
            fetch_result=fetch_result,
        )
        raw_result.error_message = str(error)
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=parse_date(payload_data.get("更新日期")),
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=0,
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=BROKER_BRANCH_COVERAGE_INVALID,
            fetch_status=BROKER_BRANCH_FETCH_INVALID,
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(*_base_quality_warnings(), "payload_schema_invalid"),
        )
        _commit_or_rollback(db)
        raise error from exc

    provider_trade_date = parse_date(payload_data.get("更新日期"))
    payload_stock_id = str(payload_data.get("股票代號") or "").strip()
    if payload_stock_id != stock_id:
        error = BrokerBranchFetchError(
            "Broker branch payload stock id does not match the requested target.",
            failure_kind="invalid",
            fetch_result=fetch_result,
        )
        raw_result.error_message = str(error)
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=provider_trade_date,
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=0,
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=BROKER_BRANCH_COVERAGE_INVALID,
            fetch_status=BROKER_BRANCH_FETCH_INVALID,
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(*_base_quality_warnings(), "stock_id_mismatch"),
        )
        _commit_or_rollback(db)
        raise error

    rows, invalid_identity_count = _normalize_observation_rows(parsed_rows)
    quality_warnings = _base_quality_warnings()
    if invalid_identity_count:
        quality_warnings.append(
            f"invalid_identity_rows:{invalid_identity_count}"
        )

    if not rows:
        all_rows_invalid = bool(parsed_rows) and invalid_identity_count == len(
            parsed_rows
        )
        raw_result.error_message = (
            "Broker branch payload contains no valid branch identity."
            if all_rows_invalid
            else None
        )
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=provider_trade_date,
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=0,
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=(
                BROKER_BRANCH_COVERAGE_INVALID
                if all_rows_invalid
                else BROKER_BRANCH_COVERAGE_PARTIAL
            ),
            fetch_status=(
                BROKER_BRANCH_FETCH_INVALID
                if all_rows_invalid
                else BROKER_BRANCH_FETCH_EMPTY
            ),
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(
                *quality_warnings,
                (
                    "no_valid_branch_identity"
                    if all_rows_invalid
                    else "ranked_top_n_empty_does_not_confirm_no_activity"
                ),
            ),
        )
        _commit_or_rollback(db)
        if all_rows_invalid:
            raise BrokerBranchFetchError(
                "Broker branch payload contains no valid branch identity.",
                failure_kind="invalid",
                fetch_result=fetch_result,
            )
        return []

    fetched_trade_date = rows[0]["trade_date"]

    if expected_trade_date != fetched_trade_date:
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=fetched_trade_date,
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=len(rows),
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=BROKER_BRANCH_COVERAGE_PARTIAL,
            fetch_status=BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH,
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=(*quality_warnings, "provider_trade_date_mismatch"),
        )
        _commit_or_rollback(db)
        return []

    existing_count = (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.source_id == source.id)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == fetched_trade_date)
        .count()
    )

    if existing_count and not force:
        upsert_broker_branch_snapshot_quality(
            db,
            source_id=source.id,
            raw_result_id=raw_result.id,
            stock_id=stock_id,
            expected_trade_date=expected_trade_date,
            provider_trade_date=fetched_trade_date,
            fetched_at=raw_result.fetched_at,
            coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
            buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
            observed_branch_count=len(rows),
            absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
            coverage_status=(
                BROKER_BRANCH_COVERAGE_PARTIAL
                if invalid_identity_count
                else BROKER_BRANCH_COVERAGE_CENSORED
            ),
            fetch_status=(
                BROKER_BRANCH_FETCH_PARTIAL
                if invalid_identity_count
                else BROKER_BRANCH_FETCH_SUCCESS
            ),
            source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            includes_block_trades=None,
            warnings=quality_warnings,
        )
        _commit_or_rollback(db)
        return list_broker_branch_trades(
            db=db,
            stock_id=stock_id,
            trade_date=fetched_trade_date,
        )

    (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.source_id == source.id)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == fetched_trade_date)
        .delete(synchronize_session=False)
    )

    models = [
        BrokerBranchTradeDaily(
            source_id=source.id,
            raw_result_id=raw_result.id,
            **row,
        )
        for row in rows
    ]
    db.add_all(models)
    upsert_broker_branch_snapshot_quality(
        db,
        source_id=source.id,
        raw_result_id=raw_result.id,
        stock_id=stock_id,
        expected_trade_date=expected_trade_date,
        provider_trade_date=fetched_trade_date,
        fetched_at=raw_result.fetched_at,
        coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
        buy_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
        sell_rank_limit=NSTOCK_BROKER_BRANCH_RANK_LIMIT,
        observed_branch_count=len(rows),
        absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
        coverage_status=(
            BROKER_BRANCH_COVERAGE_PARTIAL
            if invalid_identity_count
            else BROKER_BRANCH_COVERAGE_CENSORED
        ),
        fetch_status=(
            BROKER_BRANCH_FETCH_PARTIAL
            if invalid_identity_count
            else BROKER_BRANCH_FETCH_SUCCESS
        ),
        source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
        includes_block_trades=None,
        warnings=quality_warnings,
    )
    _commit_or_rollback(db)

    return list_broker_branch_trades(
        db=db,
        stock_id=stock_id,
        trade_date=fetched_trade_date,
    )


def expected_broker_branch_trade_date(now: datetime | None = None) -> date:
    return latest_released_trading_day(
        release_time=BRANCH_DAILY_READY_TIME,
        include_today=None,
        now=now,
    )


def has_broker_branch_trades(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
) -> bool:
    return (
        db.query(BrokerBranchTradeDaily.id)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == trade_date)
        .limit(1)
        .scalar()
        is not None
    )


def ensure_broker_branch_daily(
    db: Session,
    *,
    stock_id: str,
    trade_date: date | None = None,
    force: bool = False,
) -> list[BrokerBranchTradeDaily]:
    target_trade_date = trade_date or expected_broker_branch_trade_date()

    if not force and has_broker_branch_trades(
        db=db,
        stock_id=stock_id,
        trade_date=target_trade_date,
    ):
        return list_broker_branch_trades(
            db=db,
            stock_id=stock_id,
            trade_date=target_trade_date,
        )

    return fetch_and_store_broker_branch_daily(
        db=db,
        stock_id=stock_id,
        requested_trade_date=target_trade_date,
        force=force,
    )


def latest_broker_branch_trade_date(db: Session, stock_id: str) -> date | None:
    return (
        db.query(BrokerBranchTradeDaily.trade_date)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .order_by(BrokerBranchTradeDaily.trade_date.desc())
        .limit(1)
        .scalar()
    )


def list_recent_broker_branch_trade_dates(
    db: Session,
    *,
    stock_id: str,
    days: int,
    trade_date: date | None = None,
) -> list[date]:
    query = (
        db.query(BrokerBranchTradeDaily.trade_date)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
    )

    if trade_date is not None:
        query = query.filter(BrokerBranchTradeDaily.trade_date <= trade_date)

    return [
        row[0]
        for row in (
            query.distinct()
            .order_by(BrokerBranchTradeDaily.trade_date.desc())
            .limit(max(days, 1))
            .all()
        )
    ]


def list_broker_branch_trades(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
) -> list[BrokerBranchTradeDaily]:
    return (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date == trade_date)
        .order_by(
            BrokerBranchTradeDaily.net_lots.desc().nullslast(),
            BrokerBranchTradeDaily.branch_code.asc(),
        )
        .all()
    )


def list_broker_branch_trades_for_dates(
    db: Session,
    *,
    stock_id: str,
    trade_dates: list[date],
) -> list[BrokerBranchTradeDaily]:
    if not trade_dates:
        return []

    return (
        db.query(BrokerBranchTradeDaily)
        .filter(BrokerBranchTradeDaily.stock_id == stock_id)
        .filter(BrokerBranchTradeDaily.trade_date.in_(trade_dates))
        .order_by(
            BrokerBranchTradeDaily.trade_date.desc(),
            BrokerBranchTradeDaily.branch_code.asc(),
        )
        .all()
    )


def _weighted_average(total_value: float, total_lots: int) -> float | None:
    if total_lots <= 0:
        return None

    return total_value / total_lots


def aggregate_broker_branch_trades(
    rows: list[BrokerBranchTradeDaily],
    *,
    trade_date: date,
    source_label: str,
) -> list[dict]:
    aggregated: dict[str, dict] = {}

    for row in rows:
        branch_key = row.branch_code or row.branch_name
        current = aggregated.get(branch_key)

        if current is None:
            current = {
                "id": row.id,
                "source_id": row.source_id,
                "raw_result_id": row.raw_result_id,
                "trade_date": trade_date,
                "stock_id": row.stock_id,
                "stock_name": row.stock_name,
                "branch_code": row.branch_code,
                "branch_name": row.branch_name,
                "buy_lots": 0,
                "sell_lots": 0,
                "net_lots": 0,
                "buy_avg_price": None,
                "sell_avg_price": None,
                "buy_rank": None,
                "sell_rank": None,
                "source_label": source_label,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "_buy_value": 0.0,
                "_sell_value": 0.0,
            }
            aggregated[branch_key] = current

        buy_lots = row.buy_lots or 0
        sell_lots = row.sell_lots or 0
        current["buy_lots"] += buy_lots
        current["sell_lots"] += sell_lots
        current["net_lots"] += row.net_lots or 0

        if row.buy_avg_price is not None and buy_lots > 0:
            current["_buy_value"] += row.buy_avg_price * buy_lots

        if row.sell_avg_price is not None and sell_lots > 0:
            current["_sell_value"] += row.sell_avg_price * sell_lots

        if row.updated_at > current["updated_at"]:
            current["updated_at"] = row.updated_at

    result = []

    for current in aggregated.values():
        current["buy_avg_price"] = _weighted_average(
            current.pop("_buy_value"),
            current["buy_lots"],
        )
        current["sell_avg_price"] = _weighted_average(
            current.pop("_sell_value"),
            current["sell_lots"],
        )
        result.append(current)

    return result


def get_broker_branch_trade_summary(
    db: Session,
    *,
    stock_id: str,
    trade_date: date | None = None,
    days: int = 1,
    ensure_daily: bool = False,
    force: bool = False,
) -> dict:
    if ensure_daily:
        ensure_broker_branch_daily(
            db=db,
            stock_id=stock_id,
            trade_date=trade_date,
            force=force,
        )

    requested_days = max(days, 1)
    trade_dates = list_recent_broker_branch_trade_dates(
        db=db,
        stock_id=stock_id,
        days=requested_days,
        trade_date=trade_date,
    )
    target_date = trade_dates[0] if trade_dates else None

    if target_date is None:
        return {
            "stock_id": stock_id,
            "stock_name": None,
            "trade_date": None,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "source_url": _source_url(stock_id),
            "source_label": None,
            "is_latest": False,
            "requested_days": requested_days,
            "available_days": 0,
            "trade_dates": [],
            "is_partial": True,
            "aggregation_window": {
                "mode": "single_session" if requested_days == 1 else "multi_session_net",
                "anchor_trade_date": None,
                "requested_trading_days": requested_days,
                "available_trading_days": 0,
                "included_trade_dates": [],
            },
            "date_semantics": {
                "trade_date": "market_observation_date",
                "trade_dates": "sessions_included_in_the_aggregation",
                "created_at": "local_ingestion_timestamp_not_market_freshness",
            },
            "row_count": 0,
            "buy_top": [],
            "sell_top": [],
        }

    rows = list_broker_branch_trades_for_dates(
        db=db,
        stock_id=stock_id,
        trade_dates=trade_dates,
    )

    if requested_days <= 1:
        buy_top = sorted(
            [row for row in rows if row.buy_rank is not None],
            key=lambda row: row.buy_rank or 999,
        )
        sell_top = sorted(
            [row for row in rows if row.sell_rank is not None],
            key=lambda row: row.sell_rank or 999,
        )
        source_label = rows[0].source_label if rows else None
        row_count = len(rows)
    else:
        source_label = f"nStock branch top15 aggregate ({len(trade_dates)} days)"
        aggregated_rows = aggregate_broker_branch_trades(
            rows,
            trade_date=target_date,
            source_label=source_label,
        )
        buy_top = sorted(
            [row for row in aggregated_rows if (row["net_lots"] or 0) > 0],
            key=lambda row: row["net_lots"] or 0,
            reverse=True,
        )[:15]
        sell_top = sorted(
            [row for row in aggregated_rows if (row["net_lots"] or 0) < 0],
            key=lambda row: row["net_lots"] or 0,
        )[:15]

        for index, row in enumerate(buy_top, start=1):
            row["buy_rank"] = index

        for index, row in enumerate(sell_top, start=1):
            row["sell_rank"] = index

        row_count = len(aggregated_rows)

    first_row = rows[0] if rows else None

    return {
        "stock_id": stock_id,
        "stock_name": first_row.stock_name if first_row else None,
        "trade_date": target_date,
        "source_name": NSTOCK_BRANCH_SOURCE_NAME,
        "source_url": _source_url(stock_id),
        "source_label": source_label,
        "is_latest": True,
        "requested_days": requested_days,
        "available_days": len(trade_dates),
        "trade_dates": trade_dates,
        "is_partial": len(trade_dates) < requested_days,
        "aggregation_window": {
            "mode": "single_session" if requested_days == 1 else "multi_session_net",
            "anchor_trade_date": target_date,
            "requested_trading_days": requested_days,
            "available_trading_days": len(trade_dates),
            "included_trade_dates": trade_dates,
        },
        "date_semantics": {
            "trade_date": "market_observation_date",
            "trade_dates": "sessions_included_in_the_aggregation",
            "created_at": "local_ingestion_timestamp_not_market_freshness",
        },
        "row_count": row_count,
        "buy_top": buy_top,
        "sell_top": sell_top,
    }
