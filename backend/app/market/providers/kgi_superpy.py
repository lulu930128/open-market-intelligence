from __future__ import annotations

import atexit
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Event, RLock, Thread, Timer
import time
from typing import Any
from uuid import uuid4

from app.config import PROJECT_ROOT, settings
from app.market.providers.kgi_canonical import (
    canonical_snapshot_from_kgi,
    kgi_quote_has_actual_trade_evidence,
    kgi_quote_is_indicative,
)
from app.market.trading_calendar import taiwan_market_session_phase
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


LOGGER = logging.getLogger(__name__)
KGI_SUPERPY_PROVIDER = "kgi_superpy"
KGI_SUPERPY_SOURCE = "kgi_superpy_quote_all"
KGI_SUPERPY_FALLBACK_SOURCE = "twse_mis_quote_depth"
KGI_SUPERPY_PROTOCOL = "kgi-superpy-quote-v1"
KGI_SUPERPY_STREAM_CONTRACT = "omi.tw.realtime_stream.v2"
KGI_SUPERPY_LEASE_OWNER_KINDS = frozenset({"frontend_viewer", "acceptance_probe"})
RECENT_TRADE_LIMIT = 60
AUCTION_OBSERVATION_LIMIT = 120
MINUTE_KBAR_LIMIT = 120
QUOTE_EVENT_LIMIT = 240
DIAGNOSTIC_EVENT_LIMIT = 240

DIAGNOSTIC_COUNTER_KEYS = (
    "callback_count",
    "baseline_only_count",
    "cumulative_advanced_count",
    "same_cumulative_count",
    "decreasing_cumulative_count",
    "missing_cumulative_count",
    "invalid_cumulative_count",
    "trade_addition_count",
    "auction_addition_count",
    "trade_signature_suppression_count",
    "auction_signature_suppression_count",
    "non_trade_suppression_count",
    "trial_leak_count",
    "cross_date_rejected_count",
)


@dataclass
class _Lease:
    lease_id: str
    symbol: str
    expires_at: float
    owner_kind: str = "frontend_viewer"


@dataclass(frozen=True)
class KgiSuperPyQuoteSnapshot:
    quote: dict[str, Any] | None
    status: str
    error: str | None
    active_leases: int
    last_event: dict[str, Any] | None = None


class KgiSuperPyQuoteManager:
    def __init__(self, config: Any = settings) -> None:
        self._config = config
        self._lock = RLock()
        self._start_lock = RLock()
        self._write_lock = RLock()
        self._process: subprocess.Popen[str] | None = None
        self._ready = Event()
        self._ready_error: str | None = None
        self._pending: dict[str, Queue[dict[str, Any]]] = {}
        self._quotes: dict[str, dict[str, Any]] = {}
        self._quote_events: dict[str, deque[dict[str, Any]]] = {}
        self._diagnostic_events: dict[str, deque[dict[str, Any]]] = {}
        self._diagnostic_counters: dict[str, Counter[str]] = {}
        self._recent_trades: dict[str, deque[dict[str, Any]]] = {}
        self._auction_observations: dict[str, deque[dict[str, Any]]] = {}
        self._minute_kbars: dict[str, deque[dict[str, Any]]] = {}
        self._last_trade_signatures: dict[str, tuple[Any, ...]] = {}
        self._last_auction_signatures: dict[str, tuple[Any, ...]] = {}
        self._last_trade_prices: dict[str, float] = {}
        self._last_cumulative_volume_lots: dict[str, int] = {}
        self._stream_trade_dates: dict[str, str] = {}
        self._stream_sequences: dict[str, int] = {}
        self._stream_received_at: dict[str, str] = {}
        self._stream_session_phases: dict[str, str] = {}
        self._capability_warnings: dict[str, dict[str, str]] = {}
        self._symbol_status: dict[str, str] = {}
        self._symbol_errors: dict[str, str] = {}
        self._last_event: dict[str, Any] | None = None
        self._leases: dict[str, _Lease] = {}
        self._symbol_leases: dict[str, set[str]] = {}
        self._subscription_workers: set[str] = set()
        self._idle_timer: Timer | None = None
        self._stopped = Event()
        Thread(target=self._reap_expired_leases, daemon=True).start()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._config, "enable_kgi_superpy_quote", False))

    def _lease_ttl_seconds(self) -> int:
        return max(int(getattr(self._config, "kgi_superpy_lease_ttl_seconds", 60)), 15)

    def _stale_seconds(self) -> int:
        return max(int(getattr(self._config, "kgi_superpy_quote_stale_seconds", 180)), 1)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = str(symbol or "").strip()
        if not normalized or not normalized.isalnum() or len(normalized) > 16:
            raise ValueError("A valid Taiwan stock symbol is required.")
        return normalized

    @staticmethod
    def _normalize_lease_owner_kind(owner_kind: str) -> str:
        normalized = str(owner_kind or "").strip().lower()
        if normalized not in KGI_SUPERPY_LEASE_OWNER_KINDS:
            raise ValueError(
                "Realtime quote lease owner_kind must be frontend_viewer or "
                "acceptance_probe."
            )
        return normalized

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number else None

    @classmethod
    def _integer(cls, value: Any) -> int | None:
        number = cls._number(value)
        return int(number) if number is not None else None

    @staticmethod
    def _bounded_list(values: Any, *, limit: int = 5) -> list[Any]:
        if not isinstance(values, (list, tuple)):
            return []
        return list(values[:limit])

    @staticmethod
    def _received_at(value: Any) -> str:
        raw = str(value or "").strip()
        if raw:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _event_time_iso(cls, raw: Any, *, kbar: bool = False) -> str | None:
        value = str(raw or "").strip()
        expected_length = 12 if kbar else 14
        if len(value) != expected_length or not value.isdigit():
            return None
        try:
            from app.market.trading_calendar import TAIWAN_TZ

            parsed = datetime.strptime(
                value,
                "%Y%m%d%H%M" if kbar else "%Y%m%d%H%M%S",
            ).replace(tzinfo=TAIWAN_TZ)
        except ValueError:
            return None
        return parsed.isoformat()

    @classmethod
    def _depth_metrics(cls, quote: dict[str, Any] | None) -> dict[str, Any] | None:
        if not quote:
            return None
        bid_prices = [cls._number(value) for value in cls._bounded_list(quote.get("bid_prices"))]
        ask_prices = [cls._number(value) for value in cls._bounded_list(quote.get("ask_prices"))]
        bid_volumes = [cls._integer(value) for value in cls._bounded_list(quote.get("bid_volumes"))]
        ask_volumes = [cls._integer(value) for value in cls._bounded_list(quote.get("ask_volumes"))]
        diff_bid = [cls._integer(value) for value in cls._bounded_list(quote.get("diff_bid_vol"))]
        diff_ask = [cls._integer(value) for value in cls._bounded_list(quote.get("diff_ask_vol"))]
        best_bid = next((value for value in bid_prices if value is not None and value > 0), None)
        best_ask = next((value for value in ask_prices if value is not None and value > 0), None)
        top5_bid = sum(value for value in bid_volumes if value is not None and value > 0)
        top5_ask = sum(value for value in ask_volumes if value is not None and value > 0)
        denominator = top5_bid + top5_ask
        spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
        return {
            "event_time": cls._event_time_iso(quote.get("datetime")),
            "received_at": cls._received_at(quote.get("received_at")),
            "best_bid_price": best_bid,
            "best_ask_price": best_ask,
            "spread": spread,
            "spread_pct": (
                spread / best_bid * 100
                if spread is not None and best_bid is not None and best_bid > 0
                else None
            ),
            "top5_bid_volume_lots": top5_bid if top5_bid > 0 else None,
            "top5_ask_volume_lots": top5_ask if top5_ask > 0 else None,
            "top5_imbalance": (
                (top5_bid - top5_ask) / denominator if denominator > 0 else None
            ),
            "top5_imbalance_formula": (
                "(bid_volume_lots-ask_volume_lots)/(bid_volume_lots+ask_volume_lots)"
                if denominator > 0
                else None
            ),
            "diff_bid_volume_lots": diff_bid,
            "diff_ask_volume_lots": diff_ask,
            "simtrade": cls._integer(quote.get("simtrade")) == 1,
        }

    def _python_path(self) -> Path:
        configured = str(getattr(self._config, "kgi_superpy_python", "") or "").strip()
        if configured:
            configured_path = Path(configured).expanduser()
            return (
                configured_path
                if configured_path.is_absolute()
                else PROJECT_ROOT / configured_path
            )
        windows_path = PROJECT_ROOT / ".venv-kgi" / "Scripts" / "python.exe"
        if os.name == "nt":
            return windows_path
        return PROJECT_ROOT / ".venv-kgi" / "bin" / "python"

    def _configuration_error(self) -> str | None:
        if not self.enabled:
            return "KGI SuperPy quote source is disabled."
        if not str(getattr(self._config, "kgi_superpy_person_id", "") or "").strip():
            return "KGI_SUPERPY_PERSON_ID is not configured."
        if not str(getattr(self._config, "kgi_superpy_password", "") or "").strip():
            return "KGI_SUPERPY_PASSWORD is not configured."
        python_path = self._python_path()
        if not python_path.is_file():
            return f"KGI SuperPy Python was not found: {python_path}"
        return None

    def _lease_response(
        self,
        *,
        symbol: str,
        lease_id: str | None,
        owner_kind: str,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "lease_id": lease_id,
            "stock_id": symbol,
            "provider": KGI_SUPERPY_PROVIDER,
            "owner_kind": owner_kind,
            "status": status,
            "expires_in_seconds": self._lease_ttl_seconds() if lease_id else None,
            "fallback_source": KGI_SUPERPY_FALLBACK_SOURCE,
            "message": {
                "disabled": "凱基即時行情尚未啟用，維持既有行情來源。",
                "unavailable": "凱基即時行情設定尚未完成，維持既有行情來源。",
                "starting": "正在連線凱基即時行情；就緒前維持既有行情來源。",
                "subscribing": "凱基即時行情訂閱中；首筆資料前維持既有行情來源。",
                "live": "凱基即時行情已連線。",
                "released": "凱基即時行情 viewer lease 已釋放。",
            }.get(status, "凱基即時行情狀態已更新。"),
            "error": error,
        }

    def acquire(
        self,
        symbol: str,
        *,
        owner_kind: str = "frontend_viewer",
    ) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        normalized_owner_kind = self._normalize_lease_owner_kind(owner_kind)
        config_error = self._configuration_error()
        if not self.enabled:
            return self._lease_response(
                symbol=normalized,
                lease_id=None,
                owner_kind=normalized_owner_kind,
                status="disabled",
            )
        if config_error:
            lease_id = uuid4().hex
            with self._lock:
                lease = _Lease(
                    lease_id=lease_id,
                    symbol=normalized,
                    expires_at=time.monotonic() + self._lease_ttl_seconds(),
                    owner_kind=normalized_owner_kind,
                )
                self._leases[lease_id] = lease
                self._symbol_leases.setdefault(normalized, set()).add(lease_id)
                self._symbol_status[normalized] = "unavailable"
                self._symbol_errors[normalized] = config_error
            return self._lease_response(
                symbol=normalized,
                lease_id=lease_id,
                owner_kind=normalized_owner_kind,
                status="unavailable",
                error=config_error,
            )

        lease_id = uuid4().hex
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            lease = _Lease(
                lease_id=lease_id,
                symbol=normalized,
                expires_at=time.monotonic() + self._lease_ttl_seconds(),
                owner_kind=normalized_owner_kind,
            )
            self._leases[lease_id] = lease
            refs = self._symbol_leases.setdefault(normalized, set())
            first_viewer = not refs
            refs.add(lease_id)
            quote_available = normalized in self._quotes
            if first_viewer and not quote_available:
                self._symbol_status[normalized] = "starting"

        if first_viewer:
            self._ensure_subscription_async(normalized)
        status = "live" if quote_available else self._symbol_status.get(normalized, "starting")
        return self._lease_response(
            symbol=normalized,
            lease_id=lease_id,
            owner_kind=normalized_owner_kind,
            status=status,
        )

    def heartbeat(self, lease_id: str) -> dict[str, Any] | None:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return None
            lease.expires_at = time.monotonic() + self._lease_ttl_seconds()
            symbol = lease.symbol
        snapshot = self.snapshot(symbol)
        if snapshot.status == "unavailable" and self._configuration_error() is None:
            self._ensure_subscription_async(symbol)
        return self._lease_response(
            symbol=symbol,
            lease_id=lease_id,
            owner_kind=lease.owner_kind,
            status=snapshot.status,
            error=snapshot.error,
        )

    def release(self, lease_id: str) -> dict[str, Any] | None:
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            if lease is None:
                return None
            refs = self._symbol_leases.get(lease.symbol)
            if refs is not None:
                refs.discard(lease_id)
                if not refs:
                    self._symbol_leases.pop(lease.symbol, None)
                    Thread(
                        target=self._unsubscribe_if_unwatched,
                        args=(lease.symbol,),
                        daemon=True,
                    ).start()
            if not self._leases:
                self._schedule_idle_shutdown_locked()
        return self._lease_response(
            symbol=lease.symbol,
            lease_id=None,
            owner_kind=lease.owner_kind,
            status="released",
        )

    def lease_summary(self) -> dict[str, Any]:
        """Return redacted process-local viewer ownership and lifecycle counts."""
        with self._lock:
            owner_counts = Counter(lease.owner_kind for lease in self._leases.values())
            symbol_counts = {
                symbol: len(lease_ids)
                for symbol, lease_ids in sorted(self._symbol_leases.items())
                if lease_ids
            }
            process = self._process
            process_running = process is not None and process.poll() is None
            return {
                "provider": KGI_SUPERPY_PROVIDER,
                "total_active_leases": len(self._leases),
                "active_symbol_count": len(symbol_counts),
                "leases_by_owner_kind": dict(sorted(owner_counts.items())),
                "leases_by_symbol": symbol_counts,
                "bridge_process_running": process_running,
                "idle_shutdown_pending": self._idle_timer is not None,
                "subscription_worker_count": len(self._subscription_workers),
            }

    def runtime_status(self) -> dict[str, Any]:
        """Return redacted quote runtime readiness for market-owned planning."""
        configuration_error = self._configuration_error()
        with self._lock:
            process = self._process
            process_running = process is not None and process.poll() is None
        return {
            "enabled": self.enabled,
            "configured": self.enabled and configuration_error is None,
            "process_running": process_running,
            "status": (
                "disabled"
                if not self.enabled
                else "unavailable"
                if configuration_error is not None
                else "connected"
                if process_running
                else "ready_to_connect"
            ),
        }

    def snapshot(self, symbol: str) -> KgiSuperPyQuoteSnapshot:
        normalized = self._normalize_symbol(symbol)
        if not self.enabled:
            return KgiSuperPyQuoteSnapshot(None, "disabled", None, 0)
        config_error = self._configuration_error()
        with self._lock:
            active_leases = len(self._symbol_leases.get(normalized, set()))
            quote = self._quotes.get(normalized)
            status = self._symbol_status.get(
                normalized,
                "not_subscribed" if active_leases == 0 else "starting",
            )
            error = config_error or self._symbol_errors.get(normalized)
            event = dict(self._last_event) if self._last_event else None

        if config_error:
            return KgiSuperPyQuoteSnapshot(
                None,
                "unavailable",
                config_error,
                active_leases,
                event,
            )
        if active_leases == 0:
            return KgiSuperPyQuoteSnapshot(None, "not_subscribed", error, 0, event)
        if status in {
            "reconnecting",
            "resubscribe_requested",
            "reconnect_failed",
            "unavailable",
        }:
            return KgiSuperPyQuoteSnapshot(None, status, error, active_leases, event)
        if quote is None:
            return KgiSuperPyQuoteSnapshot(None, status, error, active_leases, event)

        event_time = self._parse_quote_time(quote)
        age_seconds = (
            max((datetime.now(timezone.utc) - event_time).total_seconds(), 0)
            if event_time is not None
            else None
        )
        if age_seconds is None or age_seconds > self._stale_seconds():
            return KgiSuperPyQuoteSnapshot(
                None,
                "stale",
                f"KGI quote event is older than {self._stale_seconds()} seconds.",
                active_leases,
                event,
            )
        return KgiSuperPyQuoteSnapshot(
            dict(quote),
            "live",
            error,
            active_leases,
            event,
        )

    def _next_sequence_locked(self, symbol: str) -> int:
        sequence = self._stream_sequences.get(symbol, 0) + 1
        self._stream_sequences[symbol] = sequence
        return sequence

    def _reset_stream_day_locked(self, symbol: str, event_date: str) -> bool:
        previous_date = self._stream_trade_dates.get(symbol)
        if previous_date is not None and event_date < previous_date:
            return False
        if previous_date is not None and previous_date != event_date:
            self._recent_trades.pop(symbol, None)
            self._auction_observations.pop(symbol, None)
            self._quote_events.pop(symbol, None)
            self._diagnostic_events.pop(symbol, None)
            self._diagnostic_counters.pop(symbol, None)
            self._minute_kbars.pop(symbol, None)
            self._last_trade_signatures.pop(symbol, None)
            self._last_auction_signatures.pop(symbol, None)
            self._last_trade_prices.pop(symbol, None)
            self._last_cumulative_volume_lots.pop(symbol, None)
            self._stream_session_phases.pop(symbol, None)
        self._stream_trade_dates[symbol] = event_date
        return True

    def _record_callback_diagnostic_locked(
        self,
        symbol: str,
        *,
        sequence: int,
        event_time: str | None,
        received_at: str,
        manager_ingested_at: str,
        session_phase: str,
        provider_trial_flag: bool,
        actual_trade_evidence: bool,
        cumulative_volume_lots: int | None,
        previous_cumulative_volume_lots: int | None,
        cumulative_relation: str,
        projection_action: str,
        projection_event_id: str | None = None,
    ) -> None:
        diagnostics = self._diagnostic_events.setdefault(
            symbol,
            deque(maxlen=DIAGNOSTIC_EVENT_LIMIT),
        )
        diagnostics.append(
            {
                "sequence": sequence,
                "event_time": event_time,
                "received_at": received_at,
                "manager_ingested_at": manager_ingested_at,
                "session_phase": session_phase,
                "provider_trial_flag": provider_trial_flag,
                "actual_trade_evidence": actual_trade_evidence,
                "cumulative_volume_lots": cumulative_volume_lots,
                "previous_cumulative_volume_lots": previous_cumulative_volume_lots,
                "cumulative_relation": cumulative_relation,
                "projection_action": projection_action,
                "projection_event_id": projection_event_id,
            }
        )
        counters = self._diagnostic_counters.setdefault(symbol, Counter())
        counters["callback_count"] += 1
        relation_counter = {
            "advanced": "cumulative_advanced_count",
            "unchanged": "same_cumulative_count",
            "decreased": "decreasing_cumulative_count",
            "missing": "missing_cumulative_count",
            "invalid": "invalid_cumulative_count",
            "cross_date_rejected": "cross_date_rejected_count",
        }.get(cumulative_relation)
        if relation_counter:
            counters[relation_counter] += 1
        action_counter = {
            "baseline_only": "baseline_only_count",
            "trade_added": "trade_addition_count",
            "auction_added": "auction_addition_count",
            "trade_signature_suppressed": "trade_signature_suppression_count",
            "auction_signature_suppressed": "auction_signature_suppression_count",
            "same_cumulative_suppressed": "non_trade_suppression_count",
            "decreasing_cumulative_suppressed": "non_trade_suppression_count",
            "non_trade_suppressed": "non_trade_suppression_count",
        }.get(projection_action)
        if action_counter:
            counters[action_counter] += 1
        if provider_trial_flag and projection_action == "trade_added":
            counters["trial_leak_count"] += 1

    @staticmethod
    def _diagnostic_counter_payload(counters: Counter[str] | None) -> dict[str, int]:
        values = counters or Counter()
        return {key: max(int(values.get(key, 0)), 0) for key in DIAGNOSTIC_COUNTER_KEYS}

    def _accept_quote(self, quote: dict[str, Any]) -> None:
        symbol = self._normalize_symbol(str(quote.get("symbol") or ""))
        received_at = self._received_at(quote.get("received_at"))
        manager_ingested_at = datetime.now(timezone.utc).isoformat()
        normalized_quote = dict(quote)
        normalized_quote["received_at"] = received_at
        normalized_quote["manager_ingested_at"] = manager_ingested_at
        event_time = self._event_time_iso(normalized_quote.get("datetime"))
        event_date = event_time[:10] if event_time is not None else None
        session_phase = (
            taiwan_market_session_phase(datetime.fromisoformat(event_time))
            if event_time is not None
            else "unknown"
        )
        with self._lock:
            if event_date is not None and not self._reset_stream_day_locked(
                symbol,
                event_date,
            ):
                sequence = self._next_sequence_locked(symbol)
                self._record_callback_diagnostic_locked(
                    symbol,
                    sequence=sequence,
                    event_time=event_time,
                    received_at=received_at,
                    manager_ingested_at=manager_ingested_at,
                    session_phase=session_phase,
                    provider_trial_flag=self._integer(normalized_quote.get("simtrade")) == 1,
                    actual_trade_evidence=False,
                    cumulative_volume_lots=self._integer(
                        normalized_quote.get("total_volume")
                    ),
                    previous_cumulative_volume_lots=self._last_cumulative_volume_lots.get(
                        symbol
                    ),
                    cumulative_relation="cross_date_rejected",
                    projection_action="cross_date_rejected",
                )
                return
            previous_quote = self._quotes.get(symbol)
            self._quotes[symbol] = normalized_quote
            self._symbol_status[symbol] = "live"
            self._symbol_errors.pop(symbol, None)
            sequence = self._next_sequence_locked(symbol)
            self._stream_received_at[symbol] = received_at
            self._stream_session_phases[symbol] = session_phase
            self._quote_events.setdefault(
                symbol,
                deque(maxlen=QUOTE_EVENT_LIMIT),
            ).append(
                {
                    "sequence": sequence,
                    "quote": dict(normalized_quote),
                    "manager_ingested_at": manager_ingested_at,
                    "session_phase": session_phase,
                }
            )

            price = self._number(normalized_quote.get("close"))
            volume_lots = self._integer(normalized_quote.get("volume"))
            total_volume_lots = self._integer(normalized_quote.get("total_volume"))
            simtrade = self._integer(normalized_quote.get("simtrade")) == 1
            indicative = kgi_quote_is_indicative(
                normalized_quote,
                session=session_phase,
            )
            actual_trade = kgi_quote_has_actual_trade_evidence(
                normalized_quote,
                session=session_phase,
            )
            actual_trade_evidence = actual_trade
            previous_cumulative_volume_lots = self._last_cumulative_volume_lots.get(
                symbol
            )
            cumulative_relation = (
                "missing"
                if total_volume_lots is None
                else "invalid"
                if total_volume_lots < 0
                else "baseline"
                if previous_cumulative_volume_lots is None
                else "advanced"
                if total_volume_lots > previous_cumulative_volume_lots
                else "unchanged"
                if total_volume_lots == previous_cumulative_volume_lots
                else "decreased"
            )
            cumulative_volume_advanced = cumulative_relation == "advanced"
            baseline_only = actual_trade and cumulative_relation == "baseline"
            if baseline_only:
                actual_trade = False
            paired_trial_callback = (
                kgi_quote_has_actual_trade_evidence(normalized_quote)
                and previous_cumulative_volume_lots is not None
                and total_volume_lots == previous_cumulative_volume_lots
                and bool(
                    self._integer(
                        (previous_quote or {}).get("simtrade")
                    )
                    == 1
                )
            )
            if actual_trade and not cumulative_volume_advanced:
                actual_trade = False
                indicative = indicative or paired_trial_callback
            if (
                total_volume_lots is not None
                and total_volume_lots >= 0
                and (
                    previous_cumulative_volume_lots is None
                    or total_volume_lots >= previous_cumulative_volume_lots
                )
            ):
                self._last_cumulative_volume_lots[symbol] = total_volume_lots

            if indicative:
                bid_prices = self._bounded_list(normalized_quote.get("bid_prices"))
                ask_prices = self._bounded_list(normalized_quote.get("ask_prices"))
                bid_volumes = self._bounded_list(normalized_quote.get("bid_volumes"))
                ask_volumes = self._bounded_list(normalized_quote.get("ask_volumes"))
                signature = (
                    normalized_quote.get("datetime"),
                    price,
                    volume_lots,
                    total_volume_lots,
                    simtrade,
                    tuple(bid_prices),
                    tuple(ask_prices),
                    tuple(bid_volumes),
                    tuple(ask_volumes),
                )
                projection_event_id = None
                if signature != self._last_auction_signatures.get(symbol):
                    metrics = self._depth_metrics(normalized_quote) or {}
                    observations = self._auction_observations.setdefault(
                        symbol,
                        deque(maxlen=AUCTION_OBSERVATION_LIMIT),
                    )
                    projection_event_id = f"auction:{symbol}:{sequence}"
                    observations.append(
                        {
                            "event_id": projection_event_id,
                            "sequence": sequence,
                            "event_time": event_time,
                            "received_at": received_at,
                            "manager_ingested_at": manager_ingested_at,
                            "session_phase": session_phase,
                            "provider_delay_raw": normalized_quote.get("delay_time"),
                            "provider_delay_unit": "unknown",
                            "indicative_match_price": price,
                            "indicative_match_volume_lots": volume_lots,
                            "best_bid_price": metrics.get("best_bid_price"),
                            "best_ask_price": metrics.get("best_ask_price"),
                            "top5_bid_volume_lots": metrics.get("top5_bid_volume_lots"),
                            "top5_ask_volume_lots": metrics.get("top5_ask_volume_lots"),
                            "top5_imbalance": metrics.get("top5_imbalance"),
                            "diff_bid_volume_lots": metrics.get("diff_bid_volume_lots", []),
                            "diff_ask_volume_lots": metrics.get("diff_ask_volume_lots", []),
                            "semantics": (
                                "provider_simtrade_indicative_not_formal_trade"
                                if simtrade
                                else "provider_unchanged_cumulative_volume_trial_not_formal_trade"
                                if paired_trial_callback
                                else f"session_{session_phase}_indicative_not_formal_trade"
                                if session_phase
                                in {
                                    "preopen_pending",
                                    "preopen",
                                    "closing_auction",
                                    "market_closed",
                                }
                                else "provider_zero_cumulative_volume_indicative_not_formal_trade"
                            ),
                        }
                    )
                    self._last_auction_signatures[symbol] = signature
                    projection_action = "auction_added"
                else:
                    projection_action = "auction_signature_suppressed"
                self._record_callback_diagnostic_locked(
                    symbol,
                    sequence=sequence,
                    event_time=event_time,
                    received_at=received_at,
                    manager_ingested_at=manager_ingested_at,
                    session_phase=session_phase,
                    provider_trial_flag=simtrade,
                    actual_trade_evidence=actual_trade_evidence,
                    cumulative_volume_lots=total_volume_lots,
                    previous_cumulative_volume_lots=previous_cumulative_volume_lots,
                    cumulative_relation=cumulative_relation,
                    projection_action=projection_action,
                    projection_event_id=projection_event_id,
                )
                return

            if not actual_trade:
                projection_action = (
                    "baseline_only"
                    if baseline_only
                    else "same_cumulative_suppressed"
                    if actual_trade_evidence and cumulative_relation == "unchanged"
                    else "decreasing_cumulative_suppressed"
                    if actual_trade_evidence and cumulative_relation == "decreased"
                    else "non_trade_suppressed"
                )
                self._record_callback_diagnostic_locked(
                    symbol,
                    sequence=sequence,
                    event_time=event_time,
                    received_at=received_at,
                    manager_ingested_at=manager_ingested_at,
                    session_phase=session_phase,
                    provider_trial_flag=simtrade,
                    actual_trade_evidence=actual_trade_evidence,
                    cumulative_volume_lots=total_volume_lots,
                    previous_cumulative_volume_lots=previous_cumulative_volume_lots,
                    cumulative_relation=cumulative_relation,
                    projection_action=projection_action,
                )
                return
            signature = (
                normalized_quote.get("datetime"),
                price,
                volume_lots,
                total_volume_lots,
            )
            if signature == self._last_trade_signatures.get(symbol):
                self._record_callback_diagnostic_locked(
                    symbol,
                    sequence=sequence,
                    event_time=event_time,
                    received_at=received_at,
                    manager_ingested_at=manager_ingested_at,
                    session_phase=session_phase,
                    provider_trial_flag=simtrade,
                    actual_trade_evidence=actual_trade_evidence,
                    cumulative_volume_lots=total_volume_lots,
                    previous_cumulative_volume_lots=previous_cumulative_volume_lots,
                    cumulative_relation=cumulative_relation,
                    projection_action="trade_signature_suppressed",
                )
                return
            previous_price = self._last_trade_prices.get(symbol)
            direction = (
                "up"
                if previous_price is not None and price > previous_price
                else "down"
                if previous_price is not None and price < previous_price
                else "flat"
            )
            trades = self._recent_trades.setdefault(
                symbol,
                deque(maxlen=RECENT_TRADE_LIMIT),
            )
            projection_event_id = f"trade:{symbol}:{sequence}"
            trades.append(
                {
                    "event_id": projection_event_id,
                    "sequence": sequence,
                    "event_time": event_time,
                    "received_at": received_at,
                    "manager_ingested_at": manager_ingested_at,
                    "session_phase": session_phase,
                    "provider_delay_raw": normalized_quote.get("delay_time"),
                    "provider_delay_unit": "unknown",
                    "price": price,
                    "volume_lots": volume_lots,
                    "total_volume_lots": total_volume_lots,
                    "amount": self._number(normalized_quote.get("amount")),
                    "price_direction": direction,
                    "direction_semantics": "price_change_from_previous_observed_trade",
                }
            )
            self._last_trade_signatures[symbol] = signature
            self._last_trade_prices[symbol] = price
            self._record_callback_diagnostic_locked(
                symbol,
                sequence=sequence,
                event_time=event_time,
                received_at=received_at,
                manager_ingested_at=manager_ingested_at,
                session_phase=session_phase,
                provider_trial_flag=simtrade,
                actual_trade_evidence=actual_trade_evidence,
                cumulative_volume_lots=total_volume_lots,
                previous_cumulative_volume_lots=previous_cumulative_volume_lots,
                cumulative_relation=cumulative_relation,
                projection_action="trade_added",
                projection_event_id=projection_event_id,
            )

    def _accept_kbar(self, kbar: dict[str, Any]) -> None:
        symbol = self._normalize_symbol(str(kbar.get("symbol") or ""))
        timeframe = self._integer(kbar.get("timeframe"))
        if timeframe != 1:
            return
        raw_datetime = str(kbar.get("datetime") or "").strip()
        event_time = self._event_time_iso(raw_datetime, kbar=True)
        if event_time is None:
            return
        received_at = self._received_at(kbar.get("received_at"))
        with self._lock:
            event_date = event_time[:10]
            current_date = self._stream_trade_dates.get(symbol)
            if current_date is not None and event_date != current_date:
                return
            if current_date is None:
                self._stream_trade_dates[symbol] = event_date
            sequence = self._next_sequence_locked(symbol)
            self._stream_received_at[symbol] = received_at
            record = {
                "event_id": f"kbar:{symbol}:{raw_datetime}:1",
                "sequence": sequence,
                "event_time": event_time,
                "received_at": received_at,
                "timeframe_minutes": 1,
                "open": self._number(kbar.get("open")),
                "high": self._number(kbar.get("high")),
                "low": self._number(kbar.get("low")),
                "close": self._number(kbar.get("close")),
                "volume_lots": self._integer(kbar.get("volume")),
                "average_price": self._number(kbar.get("avg_price")),
                "total_amount": self._number(kbar.get("total_amount")),
            }
            bars = self._minute_kbars.setdefault(
                symbol,
                deque(maxlen=MINUTE_KBAR_LIMIT),
            )
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(bars)
                    if existing.get("event_id") == record["event_id"]
                ),
                None,
            )
            if existing_index is None:
                bars.append(record)
            else:
                bars[existing_index] = record
            self._capability_warnings.get(symbol, {}).pop("minute_kbars", None)

    def market_stream_snapshot(
        self,
        symbol: str,
        *,
        recent_trade_limit: int = 40,
        auction_limit: int = 40,
        kbar_limit: int = 60,
        diagnostic_limit: int = 0,
    ) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        recent_trade_limit = max(1, min(int(recent_trade_limit), RECENT_TRADE_LIMIT))
        auction_limit = max(1, min(int(auction_limit), AUCTION_OBSERVATION_LIMIT))
        kbar_limit = max(1, min(int(kbar_limit), MINUTE_KBAR_LIMIT))
        diagnostic_limit = max(0, min(int(diagnostic_limit), DIAGNOSTIC_EVENT_LIMIT))
        provider_snapshot = self.snapshot(normalized)
        with self._lock:
            quote = dict(self._quotes.get(normalized) or {}) or None
            trades = list(self._recent_trades.get(normalized, ()))
            auctions = list(self._auction_observations.get(normalized, ()))
            kbars = list(self._minute_kbars.get(normalized, ()))
            diagnostics = list(self._diagnostic_events.get(normalized, ()))
            diagnostic_counters = self._diagnostic_counter_payload(
                self._diagnostic_counters.get(normalized)
            )
            current_date = self._stream_trade_dates.get(normalized)
            if current_date is not None:
                trades = [
                    item
                    for item in trades
                    if str(item.get("event_time") or "")[:10] == current_date
                ]
                auctions = [
                    item
                    for item in auctions
                    if str(item.get("event_time") or "")[:10] == current_date
                ]
                kbars = [
                    item
                    for item in kbars
                    if str(item.get("event_time") or "")[:10] == current_date
                ]
            sequence = self._stream_sequences.get(normalized, 0)
            received_at = self._stream_received_at.get(normalized)
            capability_warnings = dict(self._capability_warnings.get(normalized, {}))
            session_phase = self._stream_session_phases.get(normalized)

        status = provider_snapshot.status
        active = provider_snapshot.active_leases > 0
        warming = active and status in {
            "starting",
            "subscribing",
            "reconnecting",
            "resubscribe_requested",
        }
        sampled_at = datetime.now(timezone.utc)
        depth, depth_warnings = self._canonical_depth_projection(
            normalized,
            quote,
            session_phase=session_phase,
            status=status,
            sampled_at=sampled_at,
        )
        latency, latency_warnings = self._latency_projection(
            quote,
            sampled_at=sampled_at,
        )
        capability_status = {
            "recent_trades": "available" if trades else "warming" if warming else "empty",
            "auction_observations": "available" if auctions else "warming" if warming else "empty",
            "minute_kbars": (
                "unavailable"
                if "minute_kbars" in capability_warnings
                else "available"
                if kbars
                else "warming"
                if warming
                else "empty"
            ),
            "depth_metrics": "available" if quote else "warming" if warming else "empty",
            "depth": (
                "available"
                if depth is not None
                else "warming"
                if warming
                else "unavailable"
                if quote
                else "empty"
            ),
            "latency": "available" if latency else "warming" if warming else "empty",
            "diagnostics": (
                "available"
                if diagnostic_counters["callback_count"] > 0
                else "warming"
                if warming
                else "empty"
            ),
        }
        warnings = [
            *capability_warnings.values(),
            *depth_warnings,
            *latency_warnings,
        ]
        if provider_snapshot.error:
            warnings.append(provider_snapshot.error)
        return {
            "kind": "taiwan_realtime_quote_stream",
            "contract_version": KGI_SUPERPY_STREAM_CONTRACT,
            "stock_id": normalized,
            "provider": KGI_SUPERPY_PROVIDER,
            "source": KGI_SUPERPY_SOURCE,
            "status": status,
            "active_leases": provider_snapshot.active_leases,
            "sequence": sequence,
            "generated_at": sampled_at.isoformat(),
            "event_time": self._event_time_iso(quote.get("datetime")) if quote else None,
            "received_at": received_at,
            "session_phase": session_phase,
            "selection_reason": (
                "active_kgi_viewer_or_acceptance_lease"
                if active
                else "latest_kgi_callback_cache"
            ),
            "fallback_used": False,
            "is_stale": status == "stale",
            "capability_status": capability_status,
            "limits": {
                "recent_trades": RECENT_TRADE_LIMIT,
                "auction_observations": AUCTION_OBSERVATION_LIMIT,
                "minute_kbars": MINUTE_KBAR_LIMIT,
                "quote_events": QUOTE_EVENT_LIMIT,
                "diagnostic_events": DIAGNOSTIC_EVENT_LIMIT,
            },
            "recent_trades": trades[-recent_trade_limit:][::-1],
            "auction_observations": auctions[-auction_limit:][::-1],
            "minute_kbars": kbars[-kbar_limit:],
            "depth_metrics": self._depth_metrics(quote),
            "depth": depth,
            "latency": latency,
            "diagnostic_counters": diagnostic_counters,
            "diagnostic_events": (
                diagnostics[-diagnostic_limit:] if diagnostic_limit > 0 else []
            ),
            "warnings": list(dict.fromkeys(warnings)),
        }

    @staticmethod
    def _duration_ms(
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[float | None, bool]:
        if start is None or end is None:
            return None, False
        duration = (end - start).total_seconds() * 1000
        if duration < 0:
            return None, True
        return round(duration, 3), False

    @staticmethod
    def _parse_aware_iso(value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed

    @classmethod
    def _latency_projection(
        cls,
        quote: dict[str, Any] | None,
        *,
        sampled_at: datetime,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not quote:
            return None, []
        event_at = cls._parse_quote_time(quote)
        bridge_received_at = cls._parse_aware_iso(quote.get("received_at"))
        manager_ingested_at = cls._parse_aware_iso(
            quote.get("manager_ingested_at")
        )
        event_to_bridge_ms, invalid_event_bridge = cls._duration_ms(
            event_at,
            bridge_received_at,
        )
        bridge_to_manager_ms, invalid_bridge_manager = cls._duration_ms(
            bridge_received_at,
            manager_ingested_at,
        )
        manager_to_stream_ms, invalid_manager_stream = cls._duration_ms(
            manager_ingested_at,
            sampled_at,
        )
        event_to_stream_ms, invalid_event_stream = cls._duration_ms(
            event_at,
            sampled_at,
        )
        warnings: list[str] = []
        if any(
            (
                invalid_event_bridge,
                invalid_bridge_manager,
                invalid_manager_stream,
                invalid_event_stream,
            )
        ):
            warnings.append(
                "One or more realtime latency stages were negative and were omitted."
            )
        return (
            {
                "event_at": event_at.isoformat() if event_at else None,
                "bridge_received_at": (
                    bridge_received_at.isoformat() if bridge_received_at else None
                ),
                "manager_ingested_at": (
                    manager_ingested_at.isoformat() if manager_ingested_at else None
                ),
                "stream_sampled_at": sampled_at.isoformat(),
                "event_to_bridge_ms": event_to_bridge_ms,
                "bridge_to_manager_ms": bridge_to_manager_ms,
                "manager_to_stream_ms": manager_to_stream_ms,
                "event_to_stream_ms": event_to_stream_ms,
                "provider_delay_raw": quote.get("delay_time"),
                "provider_delay_unit": "unknown",
                "provider_delay_semantics": (
                    "provider_reported_raw_value_unit_not_verified"
                ),
            },
            warnings,
        )

    @classmethod
    def _canonical_depth_projection(
        cls,
        symbol: str,
        quote: dict[str, Any] | None,
        *,
        session_phase: str | None,
        status: str,
        sampled_at: datetime,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not quote or not session_phase:
            return None, []
        try:
            snapshot = canonical_snapshot_from_kgi(
                instrument=InstrumentKey(
                    market=Market.TW,
                    symbol=symbol,
                    instrument_type=InstrumentType.STOCK,
                    venue=str(quote.get("exchange") or "UNKNOWN"),
                ),
                quote=quote,
                session=session_phase,
            )
        except (TypeError, ValueError) as exc:
            return None, [f"Canonical KGI depth projection unavailable: {exc}"]
        observation = snapshot.depth
        if observation is None:
            return None, []

        def project_level(level: Any) -> dict[str, Any]:
            quantity = level.quantity
            return {
                "level": level.level,
                "price": float(level.price) if level.price is not None else None,
                "price_state": level.price_state.value,
                "size_shares": (
                    float(quantity.value) if quantity is not None else None
                ),
                "size_lots": (
                    float(quantity.original_value)
                    if quantity is not None and quantity.original_value is not None
                    else None
                ),
            }

        received_at = cls._parse_aware_iso(quote.get("received_at"))
        age_seconds = (
            max((sampled_at - received_at).total_seconds(), 0)
            if received_at is not None
            else None
        )
        return (
            {
                "provider": observation.lineage.provider,
                "source": observation.lineage.source,
                "capability": observation.capability.value,
                "state": observation.state.value,
                "event_time": (
                    observation.lineage.event_at.isoformat()
                    if observation.lineage.event_at
                    else None
                ),
                "received_at": (
                    received_at.isoformat() if received_at is not None else None
                ),
                "manager_ingested_at": quote.get("manager_ingested_at"),
                "stream_sampled_at": sampled_at.isoformat(),
                "freshness_status": "stale" if status == "stale" else "live",
                "is_stale": status == "stale",
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "bid_levels": [project_level(level) for level in observation.bids],
                "ask_levels": [project_level(level) for level in observation.asks],
            },
            [],
        )

    @staticmethod
    def _parse_quote_time(quote: dict[str, Any]) -> datetime | None:
        raw = str(quote.get("datetime") or "").strip()
        if len(raw) != 14 or not raw.isdigit():
            return None
        try:
            from app.market.trading_calendar import TAIWAN_TZ

            return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(
                tzinfo=TAIWAN_TZ
            ).astimezone(timezone.utc)
        except ValueError:
            return None

    def _ensure_subscription_async(self, symbol: str) -> None:
        with self._lock:
            if symbol in self._subscription_workers:
                return
            self._subscription_workers.add(symbol)
        Thread(target=self._subscribe_worker, args=(symbol,), daemon=True).start()

    def _subscribe_worker(self, symbol: str) -> None:
        try:
            with self._lock:
                if not self._symbol_leases.get(symbol):
                    return
                self._symbol_status[symbol] = "subscribing"
                self._symbol_errors.pop(symbol, None)
            last_error: BaseException | None = None
            for attempt in range(1, 4):
                with self._lock:
                    if not self._symbol_leases.get(symbol):
                        return
                try:
                    response = self._request("subscribe", symbol=symbol)
                    if not response.get("ok"):
                        raise RuntimeError(
                            str(response.get("error") or "KGI subscribe failed.")
                        )
                    result = response.get("result")
                    if isinstance(result, dict):
                        kbar_warning = str(result.get("kbar_warning") or "").strip()
                        with self._lock:
                            warnings = self._capability_warnings.setdefault(symbol, {})
                            if kbar_warning:
                                warnings["minute_kbars"] = (
                                    f"KGI 1-minute KBar subscription is unavailable: {kbar_warning}"
                                )[:1000]
                            else:
                                warnings.pop("minute_kbars", None)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 3:
                        time.sleep(attempt * 2)
            if last_error is not None:
                raise last_error
            with self._lock:
                if self._symbol_leases.get(symbol) and symbol not in self._quotes:
                    self._symbol_status[symbol] = "subscribing"
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            with self._lock:
                self._symbol_status[symbol] = "unavailable"
                self._symbol_errors[symbol] = message[:1000]
            LOGGER.warning("KGI SuperPy quote subscription failed for %s: %s", symbol, message)
        finally:
            with self._lock:
                self._subscription_workers.discard(symbol)

    def _unsubscribe_if_unwatched(self, symbol: str) -> None:
        with self._lock:
            if self._symbol_leases.get(symbol):
                return
            process_running = self._process is not None and self._process.poll() is None
        try:
            if process_running:
                self._request("unsubscribe", symbol=symbol)
        except Exception as exc:
            LOGGER.warning(
                "KGI SuperPy quote unsubscribe failed for %s: %s",
                symbol,
                str(exc) or type(exc).__name__,
            )
        finally:
            with self._lock:
                if not self._symbol_leases.get(symbol):
                    self._quotes.pop(symbol, None)
                    self._quote_events.pop(symbol, None)
                    self._diagnostic_events.pop(symbol, None)
                    self._diagnostic_counters.pop(symbol, None)
                    self._recent_trades.pop(symbol, None)
                    self._auction_observations.pop(symbol, None)
                    self._minute_kbars.pop(symbol, None)
                    self._last_trade_signatures.pop(symbol, None)
                    self._last_auction_signatures.pop(symbol, None)
                    self._last_trade_prices.pop(symbol, None)
                    self._last_cumulative_volume_lots.pop(symbol, None)
                    self._stream_trade_dates.pop(symbol, None)
                    self._stream_sequences.pop(symbol, None)
                    self._stream_received_at.pop(symbol, None)
                    self._stream_session_phases.pop(symbol, None)
                    self._capability_warnings.pop(symbol, None)
                    self._symbol_status.pop(symbol, None)
                    self._symbol_errors.pop(symbol, None)

    def _schedule_idle_shutdown_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        delay = max(
            int(getattr(self._config, "kgi_superpy_idle_shutdown_seconds", 120)),
            0,
        )
        self._idle_timer = Timer(delay, self._shutdown_if_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _shutdown_if_idle(self) -> None:
        with self._lock:
            if self._leases:
                return
        self.shutdown()

    def _reap_expired_leases(self) -> None:
        while not self._stopped.wait(5):
            now = time.monotonic()
            with self._lock:
                expired = [
                    lease_id
                    for lease_id, lease in self._leases.items()
                    if lease.expires_at <= now
                ]
            for lease_id in expired:
                self.release(lease_id)

    def fetch_data_backfill(
        self,
        *,
        resource: str,
        symbol: str,
        trade_date: str,
        timeframe_minutes: int = 1,
        days: int = 1,
        limit: int = 200,
    ) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        if not self.enabled:
            return {
                "resource": resource,
                "status": "disabled",
                "error": "KGI SuperPy market data is disabled.",
            }
        config_error = self._configuration_error()
        if config_error:
            return {
                "resource": resource,
                "status": "unavailable",
                "error": config_error,
            }

        try:
            response = self._request(
                "data_get",
                payload={
                    "resource": resource,
                    "symbol": normalized,
                    "trade_date": trade_date,
                    "timeframe_minutes": timeframe_minutes,
                    "days": days,
                    "limit": limit,
                },
            )
            if not response.get("ok"):
                error = str(response.get("error") or "KGI Data request failed.")[:1000]
                normalized_error = error.lower()
                status = (
                    "plan_restricted"
                    if "d403" in normalized_error
                    or "permission" in normalized_error
                    or "權限" in normalized_error
                    else "failed"
                )
                return {"resource": resource, "status": status, "error": error}

            result = response.get("result")
            if not isinstance(result, dict):
                return {
                    "resource": resource,
                    "status": "failed",
                    "error": "KGI Data bridge returned an invalid response.",
                }
            row_count = int(result.get("row_count") or 0)
            return {
                **result,
                "status": "available" if row_count > 0 else "empty",
                "error": None,
            }
        except Exception as exc:
            return {
                "resource": resource,
                "status": "failed",
                "error": (str(exc) or type(exc).__name__)[:1000],
            }
        finally:
            with self._lock:
                if not self._leases:
                    self._schedule_idle_shutdown_locked()

    def fetch_portfolio_holdings(self, market: str) -> dict[str, Any]:
        normalized_market = str(market or "").strip().lower()
        if normalized_market not in {"tw", "us"}:
            raise ValueError("KGI portfolio market must be tw or us.")
        if not self.enabled:
            return {
                "market": normalized_market,
                "status": "disabled",
                "error": "KGI SuperPy source is disabled.",
            }
        config_error = self._configuration_error()
        if config_error:
            return {
                "market": normalized_market,
                "status": "unavailable",
                "error": config_error,
            }

        try:
            response = self._request(
                "portfolio_get",
                payload={"market": normalized_market},
            )
            if not response.get("ok"):
                error = str(response.get("error") or "KGI portfolio request failed.")[:1000]
                normalized_error = error.lower()
                status = (
                    "configuration_required"
                    if "configure kgi_superpy_" in normalized_error
                    or "no kgi" in normalized_error
                    else "permission_denied"
                    if "permission" in normalized_error
                    or "d403" in normalized_error
                    or "權限" in normalized_error
                    else "failed"
                )
                return {
                    "market": normalized_market,
                    "status": status,
                    "error": error,
                }

            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("KGI portfolio bridge returned an invalid response.")
            if result.get("market") != normalized_market:
                raise RuntimeError("KGI portfolio bridge returned the wrong market.")
            records = result.get("records")
            if not isinstance(records, list):
                raise RuntimeError("KGI portfolio bridge returned invalid holdings.")
            holding_count = int(result.get("holding_count") or 0)
            if holding_count != len(records):
                raise RuntimeError("KGI portfolio bridge returned an inconsistent holding count.")
            return {
                **result,
                "status": "available" if records else "empty",
                "error": None,
            }
        except Exception as exc:
            return {
                "market": normalized_market,
                "status": "failed",
                "error": (str(exc) or type(exc).__name__)[:1000],
            }
        finally:
            with self._lock:
                if not self._leases:
                    self._schedule_idle_shutdown_locked()

    def _request(
        self,
        action: str,
        *,
        symbol: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_process()
        request_id = uuid4().hex
        response_queue: Queue[dict[str, Any]] = Queue(maxsize=1)
        with self._lock:
            process = self._process
            self._pending[request_id] = response_queue
        if process is None or process.stdin is None or process.poll() is not None:
            with self._lock:
                self._pending.pop(request_id, None)
            raise RuntimeError("KGI SuperPy quote bridge is not running.")

        request_payload: dict[str, Any] = {
            "id": request_id,
            "action": action,
            **(payload or {}),
        }
        if symbol is not None:
            request_payload["symbol"] = symbol
        try:
            with self._write_lock:
                process.stdin.write(
                    json.dumps(request_payload, separators=(",", ":")) + "\n"
                )
                process.stdin.flush()
            timeout = max(
                float(getattr(self._config, "kgi_superpy_command_timeout_seconds", 45)),
                1.0,
            )
            return response_queue.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError(f"KGI SuperPy {action} command timed out.") from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def _ensure_process(self) -> None:
        with self._start_lock:
            with self._lock:
                if self._process is not None and self._process.poll() is None:
                    return
                self._ready.clear()
                self._ready_error = None

            config_error = self._configuration_error()
            if config_error:
                raise RuntimeError(config_error)
            python_path = self._python_path()
            bridge_path = Path(__file__).with_name("kgi_superpy_bridge.py")
            child_env = os.environ.copy()
            child_env.update(
                {
                    "PYTHONUTF8": "1",
                    "PYTHONUNBUFFERED": "1",
                    "KGI_SUPERPY_PERSON_ID": str(
                        getattr(self._config, "kgi_superpy_person_id", "") or ""
                    ),
                    "KGI_SUPERPY_PASSWORD": str(
                        getattr(self._config, "kgi_superpy_password", "") or ""
                    ),
                    "KGI_SUPERPY_SIMULATION": (
                        "true"
                        if bool(getattr(self._config, "kgi_superpy_simulation", False))
                        else "false"
                    ),
                    "KGI_SUPERPY_TW_ACCOUNT": str(
                        getattr(self._config, "kgi_superpy_tw_account", "") or ""
                    ),
                    "KGI_SUPERPY_US_ACCOUNT": str(
                        getattr(self._config, "kgi_superpy_us_account", "") or ""
                    ),
                }
            )
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            )
            process = subprocess.Popen(
                [str(python_path), "-u", str(bridge_path)],
                cwd=str(PROJECT_ROOT),
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            with self._lock:
                self._process = process
            Thread(target=self._reader_loop, args=(process,), daemon=True).start()

            timeout = max(
                float(getattr(self._config, "kgi_superpy_start_timeout_seconds", 30)),
                1.0,
            )
            if not self._ready.wait(timeout):
                self._stop_process(process)
                raise TimeoutError("KGI SuperPy quote bridge startup timed out.")
            if self._ready_error:
                self._stop_process(process)
                raise RuntimeError(self._ready_error)

    def _reader_loop(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            self._ready_error = "KGI SuperPy quote bridge stdout is unavailable."
            self._ready.set()
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                message_type = message.get("type")
                if message_type == "ready":
                    if message.get("protocol") != KGI_SUPERPY_PROTOCOL:
                        self._ready_error = "KGI SuperPy bridge protocol mismatch."
                    self._ready.set()
                elif message_type == "fatal":
                    self._ready_error = str(message.get("error") or "KGI bridge failed.")
                    self._ready.set()
                elif message_type == "response":
                    request_id = str(message.get("id") or "")
                    with self._lock:
                        pending = self._pending.get(request_id)
                    if pending is not None:
                        pending.put(message)
                elif message_type == "quote":
                    quote = message.get("data")
                    symbol = str(quote.get("symbol") or "").strip() if isinstance(quote, dict) else ""
                    if symbol:
                        try:
                            self._accept_quote(dict(quote))
                        except ValueError:
                            LOGGER.warning("KGI SuperPy emitted an invalid quote symbol.")
                elif message_type == "kbar":
                    kbar = message.get("data")
                    if isinstance(kbar, dict):
                        try:
                            self._accept_kbar(dict(kbar))
                        except ValueError:
                            LOGGER.warning("KGI SuperPy emitted an invalid KBar symbol.")
                elif message_type == "event":
                    event = message.get("data")
                    if isinstance(event, dict):
                        with self._lock:
                            self._last_event = dict(event)
                            event_code = str(event.get("event_code") or "")
                            event_message = str(event.get("event_msg") or "")[:1000]
                            info = event.get("info")
                            sub_id = (
                                str(info.get("sub_id") or "")
                                if isinstance(info, dict)
                                else ""
                            )
                            affected_symbols = [
                                symbol
                                for symbol in self._symbol_leases
                                if not sub_id or symbol in sub_id.split(".")
                            ]
                            if event_code == "EVENT_SUBSCRIBE_FAIL":
                                for symbol in affected_symbols:
                                    self._symbol_status[symbol] = "unavailable"
                                    self._symbol_errors[symbol] = (
                                        event_message or "KGI subscription failed."
                                    )
                            elif event_code in {
                                "EVENT_DISCONNECTED",
                                "EVENT_RECONNECTING",
                            }:
                                for symbol in affected_symbols:
                                    self._symbol_status[symbol] = "reconnecting"
                            elif event_code in {
                                "EVENT_RECONNECT_FAILED",
                                "EVENT_RECONNECT_MAX_REACHED",
                            }:
                                for symbol in affected_symbols:
                                    self._symbol_status[symbol] = "unavailable"
                                    self._symbol_errors[symbol] = (
                                        event_message or "KGI reconnect failed."
                                    )
                elif message_type == "status":
                    symbols = message.get("symbols")
                    status = str(message.get("status") or "")
                    kbar_warnings = message.get("kbar_warnings")
                    if isinstance(symbols, list):
                        with self._lock:
                            for symbol in symbols:
                                normalized_symbol = str(symbol)
                                self._symbol_status[normalized_symbol] = status
                                if isinstance(kbar_warnings, dict):
                                    warning = str(
                                        kbar_warnings.get(normalized_symbol) or ""
                                    ).strip()
                                    warnings = self._capability_warnings.setdefault(
                                        normalized_symbol,
                                        {},
                                    )
                                    if warning:
                                        warnings["minute_kbars"] = (
                                            "KGI 1-minute KBar resubscription is unavailable: "
                                            f"{warning}"
                                        )[:1000]
        finally:
            error_response = {
                "type": "response",
                "ok": False,
                "error": "KGI SuperPy quote bridge exited.",
            }
            with self._lock:
                if self._process is process:
                    self._process = None
                pending = list(self._pending.values())
                for symbol in self._symbol_leases:
                    self._symbol_status[symbol] = "unavailable"
                    self._symbol_errors[symbol] = error_response["error"]
            for response_queue in pending:
                try:
                    response_queue.put_nowait(error_response)
                except Exception:
                    pass
            self._ready.set()

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            process.kill()

    def shutdown(self) -> None:
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            process = self._process
        if process is None:
            return
        try:
            self._request("shutdown")
            process.wait(timeout=5)
        except Exception:
            self._stop_process(process)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
                self._quotes.clear()
                self._quote_events.clear()
                self._diagnostic_events.clear()
                self._diagnostic_counters.clear()
                self._recent_trades.clear()
                self._auction_observations.clear()
                self._minute_kbars.clear()
                self._last_trade_signatures.clear()
                self._last_auction_signatures.clear()
                self._last_trade_prices.clear()
                self._last_cumulative_volume_lots.clear()
                self._stream_trade_dates.clear()
                self._stream_sequences.clear()
                self._stream_received_at.clear()
                self._stream_session_phases.clear()
                self._capability_warnings.clear()
                self._symbol_status.clear()
                self._symbol_errors.clear()

    def close(self) -> None:
        self._stopped.set()
        self.shutdown()


_KGI_SUPERPY_MANAGER = KgiSuperPyQuoteManager()
atexit.register(_KGI_SUPERPY_MANAGER.close)


def acquire_kgi_superpy_quote_lease(
    stock_id: str,
    *,
    owner_kind: str = "frontend_viewer",
) -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.acquire(stock_id, owner_kind=owner_kind)


def heartbeat_kgi_superpy_quote_lease(lease_id: str) -> dict[str, Any] | None:
    return _KGI_SUPERPY_MANAGER.heartbeat(lease_id)


def release_kgi_superpy_quote_lease(lease_id: str) -> dict[str, Any] | None:
    return _KGI_SUPERPY_MANAGER.release(lease_id)


def get_kgi_superpy_quote_lease_summary() -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.lease_summary()


def get_kgi_superpy_quote_runtime_status() -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.runtime_status()


def get_kgi_superpy_quote_snapshot(stock_id: str) -> KgiSuperPyQuoteSnapshot:
    return _KGI_SUPERPY_MANAGER.snapshot(stock_id)


def get_kgi_superpy_market_stream_snapshot(
    stock_id: str,
    *,
    recent_trade_limit: int = 40,
    auction_limit: int = 40,
    kbar_limit: int = 60,
    diagnostic_limit: int = 0,
) -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.market_stream_snapshot(
        stock_id,
        recent_trade_limit=recent_trade_limit,
        auction_limit=auction_limit,
        kbar_limit=kbar_limit,
        diagnostic_limit=diagnostic_limit,
    )


def fetch_kgi_superpy_data_backfill(
    *,
    resource: str,
    stock_id: str,
    trade_date: str,
    timeframe_minutes: int = 1,
    days: int = 1,
    limit: int = 200,
) -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.fetch_data_backfill(
        resource=resource,
        symbol=stock_id,
        trade_date=trade_date,
        timeframe_minutes=timeframe_minutes,
        days=days,
        limit=limit,
    )


def fetch_kgi_superpy_portfolio_holdings(market: str) -> dict[str, Any]:
    return _KGI_SUPERPY_MANAGER.fetch_portfolio_holdings(market)
