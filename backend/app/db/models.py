from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)

    endpoint_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    fetch_interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)

    parser_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(50), default="none")
    reliability_level: Mapped[str] = mapped_column(String(50), default="unknown")

    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    fetch_logs: Mapped[list["FetchLog"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )

    raw_results: Mapped[list["RawFetchResult"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class FetchLog(Base):
    __tablename__ = "fetch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=True,
        index=True,
    )

    job_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[Optional["SourceRegistry"]] = relationship(back_populates="fetch_logs")


class RawFetchResult(Base):
    __tablename__ = "raw_fetch_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    fetch_log_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fetch_log.id"),
        nullable=True,
        index=True,
    )

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(20), default="GET")

    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    content_hash: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)

    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    parser_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped["SourceRegistry"] = relationship(back_populates="raw_results")


class JobRun(Base):
    __tablename__ = "job_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    target: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)

    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=1)

    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AiMemory(Base):
    __tablename__ = "ai_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_type: Mapped[str] = mapped_column(String(50), default="global", index=True)
    scope_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text)

    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    importance: Mapped[int] = mapped_column(Integer, default=50, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    source: Mapped[str] = mapped_column(String(80), default="user")
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AiReport(Base):
    __tablename__ = "ai_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    report_type: Mapped[str] = mapped_column(String(80), index=True)
    scope_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    strategy_profile: Mapped[str] = mapped_column(String(80), default="balanced", index=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    as_of: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(30), default="success", index=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_run.id"),
        nullable=True,
        index=True,
    )

    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    tool_calls: Mapped[list["AiToolCall"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )


class AiToolCall(Base):
    __tablename__ = "ai_tool_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_report.id"),
        nullable=True,
        index=True,
    )

    tool_name: Mapped[str] = mapped_column(String(140), index=True)
    status: Mapped[str] = mapped_column(String(30), default="success", index=True)
    source: Mapped[str] = mapped_column(String(80), default="backend")

    arguments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    report: Mapped[AiReport | None] = relationship(back_populates="tool_calls")


class DataQualityCheck(Base):
    __tablename__ = "data_quality_check"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    fetch_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("fetch_log.id"),
        nullable=True,
        index=True,
    )

    raw_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(String(30), index=True)
    check_name: Mapped[str] = mapped_column(String(120), index=True)

    message: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketDailyPrice(Base):
    __tablename__ = "market_daily_price"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "trade_date",
            name="uq_market_daily_source_stock_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    trade_date: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketIntradayBar(Base):
    __tablename__ = "market_intraday_bar"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "stock_id",
            "interval",
            "bar_time",
            name="uq_market_intraday_provider_stock_interval_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(60), index=True)
    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    interval: Mapped[str] = mapped_column(String(10), index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ChartDrawingSnapshot(Base):
    __tablename__ = "chart_drawing_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "market",
            "symbol",
            "timeframe",
            name="uq_chart_drawing_snapshot_market_symbol_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    market: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(20), index=True)

    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    time_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_drawing_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    drawing_count: Mapped[int] = mapped_column(Integer, default=0)

    drawings_json: Mapped[str] = mapped_column(Text, default="[]")
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="frontend", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketIndexDailyStat(Base):
    __tablename__ = "market_index_daily_stat"

    __table_args__ = (
        UniqueConstraint(
            "index_id",
            "trade_date",
            name="uq_market_index_daily_stat_index_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    index_id: Mapped[str] = mapped_column(String(20), index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)

    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    close_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketChipDaily(Base):
    __tablename__ = "market_chip_daily"

    __table_args__ = (
        UniqueConstraint(
            "index_id",
            "trade_date",
            name="uq_market_chip_daily_index_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    index_id: Mapped[str] = mapped_column(String(20), index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)

    close_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    foreign_futures_net_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    foreign_futures_net_oi_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retail_futures_net_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retail_futures_net_oi_change: Mapped[int | None] = mapped_column(Integer, nullable=True)

    total_institutional_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_investor_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_self_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_hedge_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    government_bank_net_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    margin_balance_change_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_balance_change_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_balance_change_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_grade: Mapped[str] = mapped_column(String(50), default="mixed", index=True)
    source_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class InstitutionalTradeDaily(Base):
    __tablename__ = "institutional_trade_daily"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "trade_date",
            name="uq_institutional_trade_source_stock_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    trade_date: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    foreign_investor_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_investor_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_investor_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    foreign_dealer_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_dealer_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_dealer_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    investment_trust_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dealer_self_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_self_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_self_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dealer_hedge_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_hedge_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_hedge_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dealer_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    total_institutional_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarginTradingDaily(Base):
    __tablename__ = "margin_trading_daily"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "trade_date",
            name="uq_margin_trading_source_stock_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    trade_date: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    margin_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_cash_repayment: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_previous_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_today_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margin_next_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    short_covering: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_sale: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_stock_repayment: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_previous_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_today_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_next_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    offset: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class BrokerBranchTradeDaily(Base):
    __tablename__ = "broker_branch_trade_daily"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "trade_date",
            "branch_code",
            name="uq_broker_branch_source_stock_date_branch",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    trade_date: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    branch_code: Mapped[str] = mapped_column(String(20), index=True)
    branch_name: Mapped[str] = mapped_column(String(160), index=True)

    buy_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    buy_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    buy_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ShareholdingDistributionWeekly(Base):
    __tablename__ = "shareholding_distribution_weekly"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "data_date",
            "holding_level",
            name="uq_shareholding_source_stock_date_level",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    data_date: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    holding_level: Mapped[str] = mapped_column(String(20), index=True)
    holding_level_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    holder_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MonthlyRevenue(Base):
    __tablename__ = "monthly_revenue"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "period",
            name="uq_monthly_revenue_source_stock_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    period: Mapped[date] = mapped_column(Date, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    market: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    monthly_revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_month_revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_year_month_revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    month_over_month_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_over_year_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    cumulative_revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_year_cumulative_revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cumulative_year_over_year_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class FinancialMetricQuarterly(Base):
    __tablename__ = "financial_metric_quarterly"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "stock_id",
            "fiscal_year",
            "quarter",
            name="uq_financial_metric_source_stock_year_quarter",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer, index=True)
    period: Mapped[str] = mapped_column(String(12), index=True)

    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    market: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income_attributable_parent: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    parent_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    book_value_per_share: Mapped[float | None] = mapped_column(Float, nullable=True)

    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    roa: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)




class StockMaster(Base):
    __tablename__ = "stock_master"

    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            name="uq_stock_master_stock_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    market: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    instrument_type: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class StockProfile(Base):
    __tablename__ = "stock_profile"

    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            name="uq_stock_profile_stock_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_registry.id"),
        nullable=False,
        index=True,
    )

    raw_result_id: Mapped[int] = mapped_column(
        ForeignKey("raw_fetch_result.id"),
        nullable=False,
        index=True,
    )

    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    stock_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    short_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    market: Mapped[str] = mapped_column(String(50), default="TWSE", index=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    listed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    established_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    paid_in_capital: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    issued_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    private_placement_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    preferred_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    chairman: Mapped[str | None] = mapped_column(String(120), nullable=True)
    general_manager: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spokesman: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spokesman_title: Mapped[str | None] = mapped_column(String(120), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USStockMaster(Base):
    __tablename__ = "us_stock_master"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            name="uq_us_stock_master_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    security_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    exchange: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    listing_source: Mapped[str] = mapped_column(String(40), default="nasdaq_trader", index=True)

    market_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    financial_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cqs_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    nasdaq_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    cik: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sec_company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    is_etf: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    is_test_issue: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    round_lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USDailyPrice(Base):
    __tablename__ = "us_daily_price"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "trade_date",
            name="uq_us_daily_price_provider_symbol_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dividend_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_coefficient: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USSecCompanyFact(Base):
    __tablename__ = "us_sec_company_fact"

    __table_args__ = (
        UniqueConstraint(
            "fact_key",
            name="uq_us_sec_company_fact_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    fact_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    cik: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    taxonomy: Mapped[str] = mapped_column(String(40), index=True)
    tag: Mapped[str] = mapped_column(String(160), index=True)
    label: Mapped[str | None] = mapped_column(String(240), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String(80), index=True)

    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    form: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    period_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    period_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    accession_number: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    frame: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USCompanyProfile(Base):
    __tablename__ = "us_company_profile"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            name="uq_us_company_profile_provider_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    exchange: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)

    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ebitda: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    peg_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_ttm: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    profit_margin: Mapped[float | None] = mapped_column(Float, nullable=True)

    fiscal_year_end: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latest_quarter: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USCorporateAction(Base):
    __tablename__ = "us_corporate_action"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "action_type",
            "event_date",
            name="uq_us_corporate_action_provider_symbol_type_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)

    declaration_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_from: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_to: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USShortVolumeDaily(Base):
    __tablename__ = "us_short_volume_daily"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "trade_date",
            "market_center",
            name="uq_us_short_volume_provider_symbol_date_market",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    market_center: Mapped[str] = mapped_column(String(40), default="", index=True)

    short_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_exempt_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MacroSeriesObservation(Base):
    __tablename__ = "macro_series_observation"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "series_id",
            "observation_date",
            name="uq_macro_series_observation_provider_series_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    series_id: Mapped[str] = mapped_column(String(80), index=True)
    series_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    observation_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(80), nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USWatchlistGroup(Base):
    __tablename__ = "us_watchlist_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("us_watchlist_group.id"),
        nullable=True,
        index=True,
    )

    group_name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class USWatchlistItem(Base):
    __tablename__ = "us_watchlist_item"

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "symbol",
            name="uq_us_watchlist_item_group_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("us_watchlist_group.id"),
        nullable=False,
        index=True,
    )

    symbol: Mapped[str] = mapped_column(String(32), index=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)

    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WatchlistGroup(Base):
    __tablename__ = "watchlist_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlist_group.id"),
        nullable=True,
        index=True,
    )

    group_name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WatchlistItem(Base):
    __tablename__ = "watchlist_item"

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "stock_id",
            name="uq_watchlist_item_group_stock",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_group.id"),
        nullable=False,
        index=True,
    )

    stock_id: Mapped[str] = mapped_column(String(20), index=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)

    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
