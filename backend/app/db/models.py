from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    __tablename__ = "app_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    setting_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value_json: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), default="user", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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


class DispatchRecipientGroup(Base):
    __tablename__ = "dispatch_recipient_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    emails_json: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    deliveries: Mapped[list["DispatchDelivery"]] = relationship(
        back_populates="recipient_group",
    )
    schedules: Mapped[list["DispatchSchedule"]] = relationship(
        back_populates="recipient_group",
    )


class DispatchDelivery(Base):
    __tablename__ = "dispatch_delivery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_run.id"),
        nullable=True,
        index=True,
    )
    recipient_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_recipient_group.id"),
        nullable=True,
        index=True,
    )

    template_key: Mapped[str] = mapped_column(String(80), index=True)
    scope_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    subject: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    recipients_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    recipient_group: Mapped[DispatchRecipientGroup | None] = relationship(
        back_populates="deliveries",
    )


class DispatchSchedule(Base):
    __tablename__ = "dispatch_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    recipient_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_recipient_group.id"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    send_time: Mapped[str] = mapped_column(String(5), index=True)
    day_of_week: Mapped[str] = mapped_column(String(80), default="mon-fri", index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Taipei", index=True)

    template_key: Mapped[str] = mapped_column(String(80), index=True)
    scope_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    request_json: Mapped[str] = mapped_column(Text)

    last_run_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_delivery.id"),
        nullable=True,
        index=True,
    )
    last_job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_run.id"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    recipient_group: Mapped[DispatchRecipientGroup | None] = relationship(
        back_populates="schedules",
    )


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


class ProviderEvent(Base):
    __tablename__ = "provider_event"

    __table_args__ = (
        Index(
            "ix_provider_event_market_resource_target_time",
            "market",
            "resource",
            "target",
            "event_time",
            "id",
        ),
        Index(
            "ix_provider_event_market_resource_provider_target_time",
            "market",
            "resource",
            "provider",
            "target",
            "event_time",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    market: Mapped[str] = mapped_column(String(20), index=True)
    provider: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    resource: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(160), default="all", index=True)

    status: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(30), default="info", index=True)
    event_type: Mapped[str] = mapped_column(String(60), default="fetch", index=True)

    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    rate_limited: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    job_run_id: Mapped[int | None] = mapped_column(ForeignKey("job_run.id"), nullable=True, index=True)
    fetch_log_id: Mapped[int | None] = mapped_column(ForeignKey("fetch_log.id"), nullable=True, index=True)
    raw_result_id: Mapped[int | None] = mapped_column(ForeignKey("raw_fetch_result.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceHealthSnapshot(Base):
    __tablename__ = "source_health_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "market",
            "resource",
            "target",
            "provider",
            name="uq_source_health_market_resource_target_provider",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    market: Mapped[str] = mapped_column(String(20), index=True)
    resource: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(160), default="all", index=True)
    provider: Mapped[str] = mapped_column(String(80), default="all", index=True)

    status: Mapped[str] = mapped_column(String(40), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    data_quality: Mapped[str] = mapped_column(String(60), default="unknown", index=True)

    latest_data_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    latest_data_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    latest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expected_data_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    freshness_lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_status: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    latest_event_id: Mapped[int | None] = mapped_column(ForeignKey("provider_event.id"), nullable=True, index=True)
    latest_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    latest_event_status: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    latest_event_severity: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    latest_event_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_event_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_error_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_error_count: Mapped[int] = mapped_column(Integer, default=0)

    snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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


class TaiwanStockQuoteSnapshot(Base):
    __tablename__ = "taiwan_stock_quote_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "stock_id",
            "quote_time",
            name="uq_tw_stock_quote_provider_stock_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(60), index=True)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    exchange_channel: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    session_phase: Mapped[str] = mapped_column(String(40), index=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_volume_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    best_bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid_size_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    best_ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask_size_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid_total_size_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask_total_size_lots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    bid_levels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ask_levels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TaiwanFuturesQuoteSnapshot(Base):
    __tablename__ = "taiwan_futures_quote_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "session",
            "quote_time",
            name="uq_tw_futures_quote_provider_symbol_contract_session_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(60), index=True)
    market: Mapped[str] = mapped_column(String(20), default="TAIFEX", index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    product_code: Mapped[str] = mapped_column(String(20), index=True)
    product_name: Mapped[str] = mapped_column(String(80))
    contract_symbol: Mapped[str] = mapped_column(String(40), index=True)
    contract_month: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    session: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    settlement_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    amplitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TaiwanFuturesIntradayBar(Base):
    __tablename__ = "taiwan_futures_intraday_bar"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "interval",
            "bar_time",
            name="uq_tw_futures_bar_provider_symbol_contract_interval_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(60), index=True)
    market: Mapped[str] = mapped_column(String(20), default="TAIFEX", index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    product_code: Mapped[str] = mapped_column(String(20), index=True)
    product_name: Mapped[str] = mapped_column(String(80))
    contract_symbol: Mapped[str] = mapped_column(String(40), index=True)
    contract_month: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    session: Mapped[str] = mapped_column(String(20), index=True)
    interval: Mapped[str] = mapped_column(String(10), index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TaiwanFuturesDailyBar(Base):
    __tablename__ = "taiwan_futures_daily_bar"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "trade_date",
            name="uq_tw_futures_daily_provider_symbol_contract_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(60), index=True)
    market: Mapped[str] = mapped_column(String(20), default="TAIFEX", index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    product_code: Mapped[str] = mapped_column(String(20), index=True)
    product_name: Mapped[str] = mapped_column(String(80))
    contract_symbol: Mapped[str] = mapped_column(String(40), index=True)
    contract_month: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    settlement_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    after_hours_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    regular_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_low_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoTickerSnapshot(Base):
    __tablename__ = "crypto_ticker_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            name="uq_crypto_ticker_provider_symbol_instrument",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)

    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoOrderBookSnapshot(Base):
    __tablename__ = "crypto_order_book_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "depth_limit",
            name="uq_crypto_order_book_provider_symbol_instrument_depth",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)
    depth_limit: Mapped[int] = mapped_column(Integer, default=5, index=True)

    best_bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    bids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    asks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoOhlcvBar(Base):
    __tablename__ = "crypto_ohlcv_bar"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "interval",
            "bar_time",
            name="uq_crypto_ohlcv_provider_symbol_instrument_interval_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)
    interval: Mapped[str] = mapped_column(String(10), index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_volume: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoDerivativesMetric(Base):
    __tablename__ = "crypto_derivatives_metric"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            name="uq_crypto_derivatives_provider_symbol_instrument",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="perpetual", index=True)

    mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    index_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoMarketCapSnapshot(Base):
    __tablename__ = "crypto_market_cap_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "coin_id",
            "vs_currency",
            name="uq_crypto_market_cap_provider_coin_currency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    coin_id: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vs_currency: Mapped[str] = mapped_column(String(10), default="usd", index=True)

    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    total_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    circulating_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_supply: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoSpreadSnapshot(Base):
    __tablename__ = "crypto_spread_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "base_asset",
            "local_provider",
            "global_provider",
            "local_symbol",
            "global_symbol",
            "fx_symbol",
            name="uq_crypto_spread_base_local_global_fx",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), default="TWD", index=True)
    local_provider: Mapped[str] = mapped_column(String(40), index=True)
    global_provider: Mapped[str] = mapped_column(String(40), index=True)
    fx_provider: Mapped[str] = mapped_column(String(40), index=True)
    local_symbol: Mapped[str] = mapped_column(String(40), index=True)
    global_symbol: Mapped[str] = mapped_column(String(40), index=True)
    fx_symbol: Mapped[str] = mapped_column(String(40), index=True)

    local_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    global_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_twd_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    source_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoTickerHistory(Base):
    __tablename__ = "crypto_ticker_history"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "sampled_at",
            name="uq_crypto_ticker_history_provider_symbol_instrument_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)

    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoLiquidityHistory(Base):
    __tablename__ = "crypto_liquidity_history"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "depth_limit",
            "sampled_at",
            name="uq_crypto_liquidity_history_provider_symbol_instrument_depth_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)
    depth_limit: Mapped[int] = mapped_column(Integer, default=5, index=True)

    best_bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    bids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    asks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoDerivativesMetricHistory(Base):
    __tablename__ = "crypto_derivatives_metric_history"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "sampled_at",
            name="uq_crypto_derivatives_history_provider_symbol_instrument_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="perpetual", index=True)

    mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    index_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoSpreadHistory(Base):
    __tablename__ = "crypto_spread_history"

    __table_args__ = (
        UniqueConstraint(
            "base_asset",
            "local_provider",
            "global_provider",
            "local_symbol",
            "global_symbol",
            "fx_symbol",
            "sampled_at",
            name="uq_crypto_spread_history_base_local_global_fx_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), default="TWD", index=True)
    local_provider: Mapped[str] = mapped_column(String(40), index=True)
    global_provider: Mapped[str] = mapped_column(String(40), index=True)
    fx_provider: Mapped[str] = mapped_column(String(40), index=True)
    local_symbol: Mapped[str] = mapped_column(String(40), index=True)
    global_symbol: Mapped[str] = mapped_column(String(40), index=True)
    fx_symbol: Mapped[str] = mapped_column(String(40), index=True)

    local_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    global_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_twd_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoLiquidationEvent(Base):
    __tablename__ = "crypto_liquidation_event"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "event_time",
            "liquidation_side",
            "price",
            "quantity",
            name="uq_crypto_liquidation_event_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="perpetual", index=True)

    liquidation_side: Mapped[str] = mapped_column(String(20), index=True)
    order_side: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoLiquidationHeatmapCell(Base):
    __tablename__ = "crypto_liquidation_heatmap_cell"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "source_kind",
            "method",
            "symbol",
            "instrument_type",
            "time_bucket",
            "bucket_seconds",
            "price_bucket",
            "liquidation_side",
            name="uq_crypto_liquidation_heatmap_cell_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    source_kind: Mapped[str] = mapped_column(String(40), index=True)
    method: Mapped[str] = mapped_column(String(80), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="perpetual", index=True)

    time_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bucket_seconds: Mapped[int] = mapped_column(Integer, default=300, index=True)
    price_bucket: Mapped[float] = mapped_column(Float, index=True)
    price_bucket_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_side: Mapped[str] = mapped_column(String(20), index=True)
    liquidation_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    intensity: Mapped[float | None] = mapped_column(Float, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoCvdHistory(Base):
    __tablename__ = "crypto_cvd_history"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "bucket_seconds",
            "sampled_at",
            name="uq_crypto_cvd_history_provider_symbol_instrument_bucket_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="spot", index=True)

    bucket_seconds: Mapped[int] = mapped_column(Integer, default=60, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    buy_base_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_base_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_quote_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_quote_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_base_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_quote_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_base_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_quote_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CryptoLongShortRatioHistory(Base):
    __tablename__ = "crypto_long_short_ratio_history"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "ratio_scope",
            "sampled_at",
            name="uq_crypto_long_short_ratio_provider_symbol_scope_sampled",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(60), index=True)
    base_asset: Mapped[str] = mapped_column(String(20), index=True)
    quote_asset: Mapped[str] = mapped_column(String(20), index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="perpetual", index=True)
    ratio_scope: Mapped[str] = mapped_column(String(60), default="global_account", index=True)

    long_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    long_short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ResourceMarketInstrument(Base):
    __tablename__ = "resource_market_instrument"

    __table_args__ = (
        UniqueConstraint("key", name="uq_resource_market_instrument_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    key: Mapped[str] = mapped_column(String(80), index=True)
    root_folder: Mapped[str] = mapped_column(String(40), default="commodity", index=True)
    group: Mapped[str] = mapped_column(String(40), index=True)
    asset_class: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(80), index=True)
    base_asset: Mapped[str] = mapped_column(String(30), index=True)
    quote_asset: Mapped[str] = mapped_column(String(30), default="USD", index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="futures", index=True)
    contract_type: Mapped[str] = mapped_column(String(40), default="front_month", index=True)
    tradable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trade_candidate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resources_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_status: Mapped[str] = mapped_column(String(40), default="provider_pending", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ResourceQuoteSnapshot(Base):
    __tablename__ = "resource_quote_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            name="uq_resource_quote_provider_symbol_instrument_contract",
        ),
        Index(
            "ix_resource_quote_symbol_fetched",
            "symbol",
            "fetched_at",
            "id",
        ),
        Index(
            "ix_resource_quote_contract_fetched",
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            "fetched_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    root_folder: Mapped[str] = mapped_column(String(40), default="commodity", index=True)
    group: Mapped[str] = mapped_column(String(40), index=True)
    asset_class: Mapped[str] = mapped_column(String(40), index=True)
    base_asset: Mapped[str] = mapped_column(String(30), index=True)
    quote_asset: Mapped[str] = mapped_column(String(30), default="USD", index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="futures", index=True)
    contract_key: Mapped[str] = mapped_column(String(80), default="front_month", index=True)
    contract_month: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ResourceOhlcvBar(Base):
    __tablename__ = "resource_ohlcv_bar"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            "interval",
            "bar_time",
            name="uq_resource_ohlcv_provider_symbol_instrument_contract_interval_time",
        ),
        Index(
            "ix_resource_ohlcv_symbol_interval_bar_time",
            "symbol",
            "interval",
            "bar_time",
            "id",
        ),
        Index(
            "ix_resource_ohlcv_contract_interval_bar_time",
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            "interval",
            "bar_time",
            "id",
        ),
        Index(
            "ix_resource_ohlcv_contract_interval_fetched",
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            "interval",
            "fetched_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    root_folder: Mapped[str] = mapped_column(String(40), default="commodity", index=True)
    group: Mapped[str] = mapped_column(String(40), index=True)
    asset_class: Mapped[str] = mapped_column(String(40), index=True)
    base_asset: Mapped[str] = mapped_column(String(30), index=True)
    quote_asset: Mapped[str] = mapped_column(String(30), default="USD", index=True)
    instrument_type: Mapped[str] = mapped_column(String(30), default="futures", index=True)
    contract_key: Mapped[str] = mapped_column(String(80), default="front_month", index=True)
    contract_month: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    interval: Mapped[str] = mapped_column(String(10), index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

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


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holding"

    __table_args__ = (
        UniqueConstraint(
            "market",
            "symbol",
            name="uq_portfolio_holding_market_symbol",
        ),
        Index("ix_portfolio_holding_market_symbol", "market", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    market: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    symbol_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    quantity: Mapped[float] = mapped_column(Float)
    cost_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), index=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_horizon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

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


class JPStockMaster(Base):
    __tablename__ = "jp_stock_master"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            name="uq_jp_stock_master_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    local_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    security_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    exchange: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    market_segment: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sector_33_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sector_33_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    sector_17_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sector_17_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    size_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    size_name: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    listing_source: Mapped[str] = mapped_column(String(40), default="discovered_yahoo_chart", index=True)
    currency: Mapped[str] = mapped_column(String(10), default="JPY", index=True)
    exchange_timezone_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPDailyPrice(Base):
    __tablename__ = "jp_daily_price"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "trade_date",
            name="uq_jp_daily_price_provider_symbol_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="JPY", index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPCompanyFundamental(Base):
    __tablename__ = "jp_company_fundamental"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            name="uq_jp_company_fundamental_provider_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)

    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enterprise_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trailing_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_to_book: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)

    disclosed_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    fiscal_year_end: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    document_type: Mapped[str | None] = mapped_column(String(120), nullable=True)

    eps_ttm: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_ttm: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_sales: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ordinary_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forecast_net_sales: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forecast_operating_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forecast_ordinary_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forecast_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_on_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_on_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnings_growth: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    equity_to_asset_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_debt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_cash_flow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investing_cash_flow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    financing_cash_flow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    quick_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    book_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    earnings_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    ex_dividend_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPMarginInterest(Base):
    __tablename__ = "jp_margin_interest"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "report_date",
            name="uq_jp_margin_interest_provider_symbol_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)

    short_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    long_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_negotiable_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    long_negotiable_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_standardized_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    long_standardized_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    issue_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPInvestorType(Base):
    __tablename__ = "jp_investor_type"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "section",
            "published_date",
            "start_date",
            "end_date",
            name="uq_jp_investor_type_provider_section_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    section: Mapped[str] = mapped_column(String(80), index=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    proprietary_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proprietary_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proprietary_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proprietary_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    broker_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    broker_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    broker_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    broker_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    total_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_traded: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    individual_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    individual_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    individual_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    individual_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    foreign_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    foreign_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    investment_trust_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    trust_bank_sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trust_bank_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trust_bank_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trust_bank_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPWatchlistGroup(Base):
    __tablename__ = "jp_watchlist_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("jp_watchlist_group.id"),
        nullable=True,
        index=True,
    )

    group_name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class JPWatchlistItem(Base):
    __tablename__ = "jp_watchlist_item"

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "symbol",
            name="uq_jp_watchlist_item_group_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("jp_watchlist_group.id"),
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


class KRStockMaster(Base):
    __tablename__ = "kr_stock_master"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            name="uq_kr_stock_master_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    local_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    security_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    security_name_kr: Mapped[str | None] = mapped_column(String(240), nullable=True)

    exchange: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    market_segment: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    listing_source: Mapped[str] = mapped_column(String(40), default="krx_data", index=True)
    currency: Mapped[str] = mapped_column(String(10), default="KRW", index=True)
    exchange_timezone_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRDailyPrice(Base):
    __tablename__ = "kr_daily_price"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "trade_date",
            name="uq_kr_daily_price_provider_symbol_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="KRW", index=True)

    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)

    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    listed_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRMarketIndex(Base):
    __tablename__ = "kr_market_index"

    __table_args__ = (
        UniqueConstraint(
            "index_id",
            name="uq_kr_market_index_index_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    index_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    provider_symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    short_name: Mapped[str] = mapped_column(String(80))
    name_kr: Mapped[str | None] = mapped_column(String(160), nullable=True)
    market_segment: Mapped[str] = mapped_column(String(80), index=True)
    index_family: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="naver_sise_index", index=True)
    currency: Mapped[str] = mapped_column(String(10), default="KRW", index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_timezone_name: Mapped[str] = mapped_column(String(80), default="Asia/Seoul")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRIndexDailyPrice(Base):
    __tablename__ = "kr_index_daily_price"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "index_id",
            "trade_date",
            name="uq_kr_index_daily_provider_index_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    index_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="KRW", index=True)

    open_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRCompanyFundamental(Base):
    __tablename__ = "kr_company_fundamental"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "fiscal_year",
            "report_code",
            "statement_name",
            "account_name",
            name="uq_kr_company_fundamental_provider_symbol_account",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    corp_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    report_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    report_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statement_name: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    account_name: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    current_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    disclosed_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    receipt_no: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRInvestorTradeDaily(Base):
    __tablename__ = "kr_investor_trade_daily"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "trade_date",
            "investor_type",
            name="uq_kr_investor_trade_provider_symbol_date_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    investor_type: Mapped[str] = mapped_column(String(80), index=True)
    buy_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_buy_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    buy_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_buy_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRWatchlistGroup(Base):
    __tablename__ = "kr_watchlist_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("kr_watchlist_group.id"),
        nullable=True,
        index=True,
    )

    group_name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KRWatchlistItem(Base):
    __tablename__ = "kr_watchlist_item"

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "symbol",
            name="uq_kr_watchlist_item_group_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("kr_watchlist_group.id"),
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


class WatchlistRadarSnapshotRun(Base):
    __tablename__ = "watchlist_radar_snapshot_run"

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "mode",
            "snapshot_date",
            "radar_rule_version",
            "include_children",
            "enabled_only",
            name="uq_watchlist_radar_snapshot_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_group.id"),
        nullable=False,
        index=True,
    )

    include_children: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    enabled_only: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    mode: Mapped[str] = mapped_column(String(40), index=True)
    max_results: Mapped[int] = mapped_column(Integer, default=30)
    calculation_limit: Mapped[int] = mapped_column(Integer, default=100)
    radar_rule_version: Mapped[str] = mapped_column(String(80), default="radar_v1", index=True)

    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    target_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    current_stock_count: Mapped[int] = mapped_column(Integer, default=0)
    stale_stock_count: Mapped[int] = mapped_column(Integer, default=0)

    requested_stock_count: Mapped[int] = mapped_column(Integer, default=0)
    ranked_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    radar_count: Mapped[int] = mapped_column(Integer, default=0)
    no_data_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    buckets_json: Mapped[str] = mapped_column(Text, default="[]")
    data_limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    request_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WatchlistRadarSnapshotItem(Base):
    __tablename__ = "watchlist_radar_snapshot_item"

    __table_args__ = (
        UniqueConstraint(
            "snapshot_run_id",
            "rank",
            "stock_id",
            "bucket",
            name="uq_watchlist_radar_snapshot_item_rank",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    snapshot_run_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_radar_snapshot_run.id"),
        nullable=False,
        index=True,
    )

    rank: Mapped[int] = mapped_column(Integer, index=True)
    source_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bucket: Mapped[str] = mapped_column(String(80), index=True)
    bucket_label: Mapped[str] = mapped_column(String(120))
    urgency: Mapped[str] = mapped_column(String(40), index=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0)
    technical_evidence_score: Mapped[float] = mapped_column(Float, default=0)
    technical_score: Mapped[float] = mapped_column(Float, default=0)
    technical_grade: Mapped[str] = mapped_column(String(40), default="watch", index=True)
    direction: Mapped[str] = mapped_column(String(40), default="neutral", index=True)

    signal_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_status: Mapped[str | None] = mapped_column(String(40), nullable=True)

    action_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    matched_signal_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    context_signals_json: Mapped[str] = mapped_column(Text, default="[]")
    factor_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    price_levels_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_item_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WatchlistRadarOutcome(Base):
    __tablename__ = "watchlist_radar_outcome"

    __table_args__ = (
        UniqueConstraint("snapshot_item_id", name="uq_watchlist_radar_outcome_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    snapshot_run_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_radar_snapshot_run.id"),
        nullable=False,
        index=True,
    )
    snapshot_item_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_radar_snapshot_item.id"),
        nullable=False,
        index=True,
    )

    group_id: Mapped[int] = mapped_column(Integer, index=True)
    stock_id: Mapped[str] = mapped_column(String(20), index=True)
    bucket: Mapped[str] = mapped_column(String(80), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    outcome_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")

    signal_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    open_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    intraday_range_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
