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
