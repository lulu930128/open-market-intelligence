"""One execution transaction/session owner, independent of the OMI app lifecycle."""

from contextlib import contextmanager
from collections import deque
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from functools import wraps
import random
import time
import json
from pathlib import Path
from threading import Event, RLock, Thread

from execution.contracts import EventKind, ExecutionRejected
from execution.order_reducer import OrderFact, OrderProgress, OrderStatus, TERMINAL, reduce_order
from execution.validation import identifier, instant, require
from .contracts import BrokerKey, Command, Observation, QueryBatch, ReportDiagnostic, SourceRead, command_from, command_payload, decimal, digest, encoded, observation_from
from .kgi import KgiSessionOwner, UsSessionView, callback_observation, price_observation
from .us_contracts import UsBrokerKey, UsCommand, UsObservation
from .storage import Journal, OwnerLease, state_from, state_payload
from .review import Draft, draft_payload, REVIEW_VERSION, expected, replay, snapshot
from .candidate import validate_binding
from .strategy import (CONSENT_POLICY, STRATEGY_VERSION, SourceSnapshot, StrategyRules, price_trigger, trigger_target,
                       exit_command, quantities, replay as replay_strategies, source_payload)


def serialized(operation):
    """Lifecycle/commands share one lane; callbacks never acquire this lock."""
    @wraps(operation)
    def call(self, *args, **kwargs):
        with self.operation(operation.__name__):
            return operation(self, *args, **kwargs)
    return call


class ExecutionRuntime:
    """Explicit operator start + injected session factory only; no live default.

    Normal clients use ExecutionApplication; submit() rejects raw commands.
    _submit_engine is an internal Phase 1 primitive, retained for engine fixtures.
    It cannot bypass a persisted review. Confirmation is workflow state, not auth.
    """

    def __init__(self, journal_path, *, account_id, trade_date, session_factory,
                 clock=None, fault=None, strategy_effects=True, native_prices=False, _parent=None, _session=None):
        self.path = Path(journal_path).resolve()
        self.account_id, self.trade_date = account_id, trade_date
        self._parent = _parent
        self.market = "US" if _parent is not None else "TW"
        require((_parent is None) == (_session is None), "INVALID_SHARED_SESSION")
        require(_parent is None or type(_session) is UsSessionView, "INVALID_SHARED_SESSION")
        self.us_runtime = None
        self._us_events = deque(maxlen=256)
        self._us_event_overflow = False
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._fault = fault or (lambda stage: None)
        self._mutex = RLock()
        self._operation_lock = RLock()
        self._busy = None
        self._managed = False
        self._desired = "OFFLINE"
        self._actual = "OFFLINE"
        self._lifecycle_stop = Event()
        self._lifecycle_worker = None
        self._retry_attempt = 0
        self._retry_at = None
        self._last_connection_error = None
        self._last_broker_read = None
        self.stop_reason = None
        self._lease = OwnerLease(self.path)
        self._journal = None
        self._started = False
        self.callback_error = None
        self.strategy_error = None
        self._strategy_wake = Event()
        self._strategy_idle = Event()
        self._strategy_idle.set()
        self._strategy_stop = Event()
        self._strategy_worker = None
        require(type(strategy_effects) is bool, "INVALID_STRATEGY_EFFECTS")
        self.strategy_effects = strategy_effects
        self.native_prices = native_prices
        self._prices = {}
        self._price_error = None
        self._price_strategies = ()  # immutable projection from the canonical journal; no tick IO
        self._cash_inventory = None  # last read evidence only; never a position ledger
        self._strategy_query_needed = False
        self.session = _session or KgiSessionOwner(session_factory, account_id, trade_date, self._callback,
                                       self._native_price if native_prices else None, self._session_bound)
        self.environment = _session.context.environment if _session is not None else None

    def _session_bound(self, binding):
        if self._managed:
            self.account_id, self.trade_date = binding.account_id, binding.trade_date
            if not self._started:
                self._open_journal()  # Replay before attaching vendor callbacks.
        if binding.us is not None and binding.us.trade_date is not None:
            if self.us_runtime is None:
                child = ExecutionRuntime(self.path.with_name(self.path.stem + ".us.sqlite"),
                    account_id=binding.us.account_id, trade_date=binding.us.trade_date,
                    session_factory=None, clock=self._clock, fault=self._fault, strategy_effects=False, native_prices=self.native_prices,
                    _parent=self, _session=UsSessionView(self.session))
                child._lease.acquire()
                try:
                    child._open_journal()
                except BaseException:
                    child._lease.release()
                    raise
                self.us_runtime = child
                self.session._us_on_event = child._enqueue_us_event
                self.session._us_on_price = child._native_price
            else:
                require((self.us_runtime.account_id, self.us_runtime.environment) ==
                        (binding.us.account_id, binding.us.environment), "US_CONTEXT_BINDING_CHANGED")
                self.us_runtime.trade_date = binding.us.trade_date
            self.us_runtime._desired, self.us_runtime._actual = "ONLINE", "ONLINE"
            self.us_runtime._prices.clear()

    def _key(self, account_id, trade_date, order_id):
        if self.market == "US":
            return UsBrokerKey(account_id, trade_date, order_id, self.environment)
        return BrokerKey(account_id, trade_date, order_id)

    def _enqueue_us_event(self, value, generation):
        # SDK callback: bounded memory only. No journal, transaction, query or
        # waiting on the command lane; immutable observations were frozen by owner.
        if len(self._us_events) == self._us_events.maxlen:
            self._us_event_overflow = True
        self._us_events.append((value, generation))
        self._wake_strategies(query=True)

    def _drain_us_events(self):
        values = []
        for _ in range(256):
            try:
                values.append(self._us_events.popleft())
            except IndexError:
                break
        if self._us_event_overflow:
            values.append(("US_CALLBACK_QUEUE_OVERFLOW", self.session.generation))
            self._us_event_overflow = False
        for value, generation in values:
            if generation != self.session.generation:
                continue
            if isinstance(value, Observation):
                self._ingest(value)
            else:
                self.callback_error = value
                with self._transaction() as con:
                    con.execute("UPDATE orders SET reconcile_required=1 WHERE submit_stage!='NOT_SENT'")
                    self._append(con, "CALLBACK_UNRESOLVED", None, {"reason": value, "market": "US"})

    @contextmanager
    def operation(self, name, *, blocking=True):
        if self._parent is not None:
            with self._parent.operation("US." + name, blocking=blocking):
                yield
            return
        require(self._operation_lock.acquire(blocking=blocking), "EXECUTOR_BUSY")
        outer = self._busy is None
        if outer:
            self._busy = {"operation": name, "started_at": datetime.now(timezone.utc).isoformat()}
        try:
            yield
        finally:
            if outer:
                self._busy = None
            self._operation_lock.release()

    def connection_status(self):
        """Memory projection only: no SDK lock, IO, login, Journal or health probe."""
        read = self._last_broker_read
        if read is not None:
            age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(read["observed_at"])).total_seconds())
            read = {**read, "age_seconds": age, "stale": age > 120 or
                    read["session_generation"] != self.session.generation}
        result = {"contract": "omi.execution.connection.v1", "market": self.market,
                "timezone": "America/New_York" if self.market == "US" else "Asia/Taipei",
                "desired": self._desired, "actual": self._actual,
                "session_bound": self.session.bound, "disconnect_observed": self.session.disconnected.is_set(),
                "disconnect_callback_registered": self.session.disconnect_callback_registered,
                "session_generation": self.session.generation, "trade_date": self.trade_date,
                "date_ready": self.session.date_matches(),
                "ready": self._desired == "ONLINE" and self._actual == "ONLINE" and
                    self.session.connected and self.session.date_matches() and self._busy is None,
                "busy": self._busy, "retry_attempt": self._retry_attempt, "retry_at": self._retry_at,
                "last_error": self._last_connection_error, "last_broker_read": read}
        if self._parent is None:
            result["us"] = self.session.us_status()
            if self.session.bound and self.session._binding.us is not None and not self.session.date_matches():
                result["date_block_reason"] = "TW_MARKET_REBIND_UNQUALIFIED"
        else:
            result.update(live_execution="MANUAL", date_basis="CLIENT_SUBMISSION_UTC"
                          if self.environment == "PRODUCTION" else "FIXTURE", broker_business_date=None)
        return result

    def request_offline(self, *, reason=None):
        # Intent changes immediately even while a vendor call cannot be stopped.
        self._desired = "OFFLINE"
        if reason is not None:
            self.stop_reason = reason
        self._lifecycle_stop.set()
        self._strategy_stop.set()
        self._strategy_wake.set()
        if self._actual != "OFFLINE":
            self._actual = "STOPPING"

    @serialized
    def probe_us(self, symbol):
        require(self._parent is None and self._started, "US_PROBE_REQUIRES_ROOT_OWNER")
        return {**self.session.us_probe(symbol), "observed_at": self._now().isoformat()}

    def _manual_us_context(self):
        require(self._parent is None and self._started, "RUNTIME_NOT_STARTED")
        self.session.ensure_us_execution()
        self.trade_date = self.session.trade_date
        require(self.us_runtime is not None, "US_ACCOUNT_UNAVAILABLE")
        return self.us_runtime

    @staticmethod
    def _manual_us_review(child, request_id):
        identifier(request_id)
        with child._journal.connection(readonly=True) as con:
            matches = [r for r in child._reviews(con).values() if r.draft.command.request_id == request_id]
        require(len(matches) <= 1, "REVIEW_IDEMPOTENCY_CONFLICT")
        return matches[0] if matches else None

    def _manual_us_output(self, child, review):
        command = review.draft.command
        value = child.review_status(review.draft.review_id)
        broker = {"available": False, "reason": "NOT_SUBMITTED", "resend": False}
        if value["execution"] is not None:
            execution = value["execution"]
            try:
                broker = self.session.us_order_readback(command, original_id=execution["original_order_id"],
                                                       order_id=execution["broker_order_id"])
                if broker.get("available"):
                    child._record_us_origin(command.execution_id, broker["original_order_id"])
                    if broker["broker_order_id"]:
                        child._bind(command.execution_id, child._key(command.account_id, command.trade_date,
                                                                   broker["broker_order_id"]))
                    if broker["rejected"]:
                        child._rejected_return(command.execution_id)
            except Exception as exc:
                broker = {"available": False, "reason": exc.code if isinstance(exc, ExecutionRejected)
                          else "SDK_READ_FAILED", "resend": False}
            value = child.review_status(review.draft.review_id)
        # One concise local receipt. Full journal/audit stays with its existing owner.
        execution = value["execution"]
        submission_status = "NOT_SUBMITTED" if execution is None else (
            "UNKNOWN" if execution["submit_stage"] == "CLAIMED" or execution["state"] == "UNKNOWN"
            else "REJECTED" if execution["state"] == "REJECTED" else execution["submit_stage"])
        return {"market": "US", "environment": command.environment, "request_id": command.request_id,
                "review_id": value["review_id"], "execution_id": value["execution_id"],
                "symbol": command.symbol, "action": command.action, "quantity": command.quantity,
                "price": command.price, "trade_currency": "USD", "settlement_mode": command.settlement_mode,
                "execution": execution, "submission_status": submission_status, "broker": broker, "resend": False,
                "date_basis": "CLIENT_SUBMISSION_UTC" if command.environment == "PRODUCTION" else "FIXTURE",
                "broker_business_date": None, "observed_at": self._now().isoformat()}

    @serialized
    def manual_us_order(self, *, request_id, symbol, action, quantity, price, settlement_mode):
        """A user's explicit command persists the existing review/claim then sends once."""
        identifier(request_id)
        require(type(quantity) is int and all(type(v) is str for v in (symbol, action, price, settlement_mode)),
                "INVALID_US_COMMAND_FIELD")
        child = self._manual_us_context()
        review = self._manual_us_review(child, request_id)
        requested = (symbol, action, quantity, price, settlement_mode)
        if review is not None:
            c = review.draft.command
            require(requested == (c.symbol, c.action, c.quantity, c.price, c.settlement_mode),
                    "REVIEW_IDEMPOTENCY_CONFLICT")
            if review.execution_id is not None:
                return self._manual_us_output(child, review)  # Includes timeout/crash, across dates/restarts.
        else:
            instrument = self.session.us_instrument(symbol)
            command = UsCommand(child.account_id, child.trade_date, request_id, request_id,
                symbol, action, quantity, price, settlement_mode, child.environment, instrument["revision"])
            draft = Draft(command, "manual-cli", "MANUAL")
            child.create_review(draft)
            review = self._manual_us_review(child, request_id)
        if review.state in {"DRAFT", "PREVIEW"}:
            child.preview_review(review.draft.review_id, expected_revision=review.revision)
            review = self._manual_us_review(child, request_id)
        require(review.snapshot is not None, "REVIEW_NOT_CONFIRMABLE")
        child.confirm_review(review.draft.review_id, expected_revision=review.revision,
                             expected_digest=review.snapshot["digest"])
        return self._manual_us_output(child, self._manual_us_review(child, request_id))

    @serialized
    def manual_us_status(self, request_id=None):
        child = self._manual_us_context()
        if request_id is None:
            return {"market": "US", "environment": child.environment, "account": "SELECTED_US",
                    **self.session.us_status(), "order_effects": "NOT_REQUESTED"}
        review = self._manual_us_review(child, request_id)
        require(review is not None, "UNKNOWN_US_REQUEST")
        child.query()
        return self._manual_us_output(child, review)

    @serialized
    def manual_us_cancel(self, request_id):
        child = self._manual_us_context()
        review = self._manual_us_review(child, request_id)
        require(review is not None and review.execution_id is not None, "UNKNOWN_US_REQUEST")
        value = self._manual_us_output(child, review)
        execution, command = value["execution"], review.draft.command
        require(execution["broker_order_id"] is not None, "US_ORDER_ID_UNAVAILABLE")
        child.cancel(command.execution_id, child._key(command.account_id, command.trade_date,
                                                     execution["broker_order_id"]))
        return self._manual_us_output(child, review)

    @serialized
    def desk_submit(self, order, selection):
        """One human action over the existing review, selection and claim owner."""
        target = self._manual_us_context() if order.get("market", "TW") == "US" else self
        request_id = digest(["desk", selection])
        rules = StrategyRules(**order["protection"]) if order.get("protection") else None
        if rules:
            rules.validate()
        lineage = {"strategy_id": request_id, "revision": 1} if rules else {}
        if target.market == "US":
            instrument = self.session.us_instrument(order["symbol"])
            value = UsCommand(target.account_id, target.trade_date, request_id, request_id,
                order["symbol"], order["action"], order["quantity_shares"], order["price"],
                order.get("settlement_mode", "MUT"), target.environment, instrument["revision"], **lineage)
        else:
            value = Command(target.account_id, target.trade_date, request_id, request_id,
                order["symbol"], order["action"], order["quantity_shares"], order["price"],
                condition=order["condition"], lot=order["lot"],
                shares_per_unit=1000 if order["lot"] == "Common" else 1, **lineage)
        draft = Draft(value, "MCP", "MANUAL")
        previous = target._manual_us_review(target, request_id)
        if previous is not None and previous.execution_id is not None:
            require(draft_payload(previous.draft) == draft_payload(draft), "REVIEW_IDEMPOTENCY_CONFLICT")
            return target.review_status(previous.draft.review_id)
        preview = target.prepare_candidate(draft, {"selection": selection, "protection": asdict(rules) if rules else None})
        return target.confirm_review(preview["review_id"], expected_revision=preview["review_revision"],
            expected_digest=preview["snapshot"]["digest"], candidate_selection=selection)

    def desk_order(self, market, execution_id):
        target = self.us_runtime if market == "US" else self
        require(target is not None, "US_ACCOUNT_UNAVAILABLE")
        value = target.status(execution_id)
        with target._journal.connection(readonly=True) as con:
            command = target._command(con, execution_id)
        strategy = target.strategy_status(command.strategy_id) if command.strategy_id else None
        return {"market": market, "execution": value, "command": command_payload(command), "protection": strategy}

    @serialized
    def desk_cancel(self, market, execution_id):
        target = self._manual_us_context() if market == "US" else self
        value = self.desk_order(market, execution_id)
        order = value["execution"]
        require(order["broker_order_id"] is not None, "BROKER_ORDER_ID_UNAVAILABLE")
        target.cancel(execution_id, target._key(target.account_id, order["trade_date"], order["broker_order_id"]))
        return self.desk_order(market, execution_id)

    @serialized
    def desk_protection(self, market, execution_id, rules, request_id, expected_revision):
        target = self._manual_us_context() if market == "US" else self
        value = self.desk_order(market, execution_id)
        sid = value["execution"]["strategy_id"]
        require(sid is not None, "ORDER_HAS_NO_PROTECTION")
        target.revise_strategy(sid, StrategyRules(**rules),
            SourceSnapshot(request_id, target._now().isoformat(), {"execution_id": execution_id, "actor": "MCP_USER"}),
            request_id=request_id, expected_revision=expected_revision)
        return self.desk_order(market, execution_id)

    def start_managed(self, *, retry_base=5.0, retry_cap=300.0, heartbeat=60.0):
        """One TW lifecycle worker. Native composition holds its process lease.

        Account discovery may precede Journal opening, as in native prepare();
        no command is admitted until replay has verified the existing Journal.
        No persisted trading intent is dispatched by this worker.
        """
        require(self._parent is None, "SHARED_CONTEXT_LIFECYCLE_OWNED")
        require(not self._started and self._lifecycle_worker is None, "RUNTIME_ALREADY_STARTED")
        require(0 < retry_base <= retry_cap and heartbeat > 0, "INVALID_RECOVERY_POLICY")
        self._lease.acquire()
        self._managed = True
        self._desired, self._actual = "ONLINE", "STARTING"
        self._lifecycle_stop.clear()
        self._lifecycle_worker = Thread(target=self._connection_loop,
            args=(retry_base, retry_cap, heartbeat), name="execution-connection", daemon=True)
        self._lifecycle_worker.start()

    def _connection_loop(self, retry_base, retry_cap, heartbeat):
        due, healthy_since = 0.0, None
        while not self._lifecycle_stop.is_set():
            now = time.monotonic()
            recovering = self.session.needs_reconnect()
            if self._actual == "BLOCKED" or now < due:
                self._lifecycle_stop.wait(0.1)
                continue
            try:
                with self.operation("recover" if recovering else "heartbeat", blocking=False):
                    if self._lifecycle_stop.is_set():
                        break
                    previous_day = self.trade_date
                    self.session.refresh_market_dates()
                    self.trade_date = self.session.trade_date
                    if self.trade_date != previous_day:
                        with self._mutex:
                            self._prices.clear()
                            self._cash_inventory = None
                    if recovering:
                        self._actual = "RECOVERING" if self._started else "CONNECTING"
                        if self.session.bound:
                            self.session.close()  # Must finish before a second login.
                        self.session.trade_date = self.session.current_day()
                        self.session.start()
                        self.account_id, self.trade_date = self.session.account_id, self.session.trade_date
                        if not self._started:
                            self._open_journal()
                        else:
                            with self._mutex:
                                self._prices.clear()
                                self._cash_inventory = None
                            with self._transaction() as con:
                                self._append(con, "RECONNECT", None, {"resend": False})
                        self._watch_strategy_prices()
                    health = self.reconcile()
                    if health.get("failure_kind") == "TRANSPORT":
                        raise ConnectionError("BROKER_READ_TRANSPORT_FAILED")
                    if self._strategy_worker is None:
                        self._strategy_stop.clear()
                        self._strategy_worker = Thread(target=self._strategy_loop, name="execution-strategy", daemon=True)
                        self._strategy_worker.start()
                        self._wake_strategies()
                    if self._lifecycle_stop.is_set():
                        break
                    if self.session.needs_reconnect():
                        raise ConnectionError("SESSION_RECOVERY_REQUIRED")
                    self._actual = "ONLINE"
                    self._retry_at = None
                    self._last_connection_error = None
                    healthy_since = healthy_since or time.monotonic()
                    if time.monotonic() - healthy_since >= heartbeat:
                        self._retry_attempt = 0
                    due = time.monotonic() + heartbeat
            except ExecutionRejected as exc:
                if exc.code == "EXECUTOR_BUSY":
                    self._lifecycle_stop.wait(0.1)
                    continue
                self._actual, self._last_connection_error = "BLOCKED", exc.code
            except Exception as exc:
                self._last_connection_error = "CONNECTION_TRANSPORT_FAILED" if isinstance(exc, (TimeoutError, ConnectionError)) else "CONNECTION_FAILED_UNCLASSIFIED"
                if self.session.close_unverified or not isinstance(exc, (TimeoutError, ConnectionError)):
                    self._actual = "BLOCKED"
                else:
                    self._actual = "BACKOFF"
                    self._retry_attempt += 1
                    healthy_since = None
                    delay = min(retry_cap, retry_base * 2 ** min(self._retry_attempt - 1, 16))
                    delay = min(retry_cap, random.uniform(delay * 0.8, delay * 1.2))
                    due = time.monotonic() + delay
                    self._retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            # Observe disconnect/date rollover promptly, but never retry inside a
            # callback. A minimum delay also bounds repeated disconnect storms.
            while not self._lifecycle_stop.wait(0.1) and self._actual == "ONLINE" and time.monotonic() < due:
                if self.session.needs_reconnect():
                    self._actual = "RECOVERING"
                    due = time.monotonic() + retry_base
                    break
        self._actual = "STOPPING"
        try:
            with self.operation("logout"):
                self.session.close()
            self._actual = "OFFLINE"
        except Exception:
            self._actual, self._last_connection_error = "BLOCKED", "KGI_SESSION_CLOSE_UNVERIFIED"

    def _record_broker_read(self, status, sources=(), *, failure_kind=None):
        self._last_broker_read = {"status": status, "observed_at": datetime.now(timezone.utc).isoformat(),
            "session_generation": self.session.generation, "sources": [asdict(s) for s in sources],
            "failure_kind": failure_kind}

    def start(self):
        require(self._parent is None, "SHARED_CONTEXT_LIFECYCLE_OWNED")
        require(not self._started, "RUNTIME_ALREADY_STARTED")
        self._lease.acquire()
        try:
            self._open_journal()
            self._desired = "ONLINE"
            self.session.start()
            self._actual = "ONLINE"
            result = self.reconcile()
            self._watch_strategy_prices()
            if self._strategy_worker is None:
                self._strategy_stop.clear()
                self._strategy_worker = Thread(target=self._strategy_loop, name="execution-strategy", daemon=True)
                self._strategy_worker.start()
                self._wake_strategies()
            return result
        except BaseException:
            self.close()
            raise

    def _open_journal(self):
        self._journal = Journal(self.path, self.account_id, scope=
            {"market": "US", "environment": self.environment} if self.market == "US" else None)
        self.verify()
        self._started = True
        # Acquiring the OS lease proves the previous owner has exited. An
        # abandoned claim is uncertainty, never permission to dispatch again.
        with self._transaction() as con:
            for row in con.execute("SELECT * FROM orders").fetchall():
                state = state_from(json.loads(row["state"]))
                if state.state in {OrderStatus.PENDING, OrderStatus.CANCEL_PENDING, OrderStatus.RECONCILING}:
                    state = self._reduce(state, EventKind.TIMEOUT)
                    self._save(con, row["execution_id"], state)
                con.execute("UPDATE orders SET reconcile_required=1 WHERE execution_id=? AND submit_stage!='NOT_SENT'", (row["execution_id"],))
            self._append(con, "STARTUP", None, {"replay_send": False})

    def close(self):
        require(self._parent is None, "SHARED_CONTEXT_LIFECYCLE_OWNED")
        self.request_offline()
        if self._lifecycle_worker is not None:
            self._lifecycle_worker.join(timeout=5)
            require(not self._lifecycle_worker.is_alive(), "LIFECYCLE_BUSY_CLOSE_UNVERIFIED")
            self._lifecycle_worker = None
        self._strategy_stop.set()
        self._strategy_wake.set()
        if self._strategy_worker is not None:
            self._strategy_worker.join(timeout=5)
            require(not self._strategy_worker.is_alive(), "STRATEGY_WORKER_NOT_STOPPED")
            self._strategy_worker = None
        # An unconfirmed logout must not release ownership to a second session.
        self.session.close()
        if self.us_runtime is not None:
            self.us_runtime._started = False
            self.us_runtime._desired, self.us_runtime._actual = "OFFLINE", "OFFLINE"
            self.us_runtime._lease.release()
        self._started = False
        self._lease.release()
        self._actual = "OFFLINE"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def _transaction(self):
        require(self._started, "RUNTIME_NOT_STARTED")
        with self._mutex, self._journal.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise

    def _now(self):
        value = self._clock()
        instant(value)
        return value

    def _append(self, con, kind, execution_id, payload, event_key=None, *, occurred_at=None):
        now = occurred_at or self._now().isoformat()
        if event_key is None:
            sequence = con.execute("SELECT coalesce(max(seq),0)+1 FROM journal").fetchone()[0]
            event_key = f"local-{sequence}"
        con.execute("INSERT INTO journal(event_key,execution_id,kind,occurred_at,payload) VALUES (?,?,?,?,?)",
                    (event_key, execution_id, kind, now, encoded(payload)))

    def _reduce(self, state, kind, *, total=0, price=None):
        now = self._now()
        # Local processing order is not a claim about broker chronology.
        if state.events:
            now = max(now, state.events[-1].occurred_at)
        control = kind in {EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED}
        fact = OrderFact(f"local-{len(state.events)+1}", state.order_id, kind, now,
                         None if control else state.last_report_sequence + 1, total, price)
        return reduce_order(state, fact, now)[0]

    def _save(self, con, execution_id, state):
        previous = state_from(json.loads(self._row(con, execution_id)["state"]))
        require(state.events[:len(previous.events)] == previous.events, "NON_APPEND_REDUCTION")
        con.execute("UPDATE orders SET state=? WHERE execution_id=?", (state_payload(state), execution_id))
        self._append(con, "ORDER_REDUCED", execution_id,
                     {"events": json.loads(state_payload(state))["events"][len(previous.events):]})

    @staticmethod
    def _row(con, execution_id):
        row = con.execute("SELECT * FROM orders WHERE execution_id=?", (execution_id,)).fetchone()
        require(row is not None, "UNKNOWN_EXECUTION")
        return row

    @staticmethod
    def _command(con, execution_id):
        return command_from(json.loads(con.execute("SELECT payload FROM intents WHERE execution_id=?", (execution_id,)).fetchone()[0]))

    def _status(self, con, execution_id):
        row = self._row(con, execution_id)
        command = self._command(con, execution_id)
        state = state_from(json.loads(row["state"]))
        fills = [dict(f) for f in con.execute("SELECT fill_id,quantity,price,source_time FROM fills WHERE execution_id=? ORDER BY fill_id", (execution_id,))]
        result = {"execution_id": execution_id, "intent_id": command.intent_id,
                "request_id": command.request_id, "space_id": command.space_id,
                "strategy_id": command.strategy_id, "revision": command.revision,
                "broker_order_id": row["broker_id"], "trade_date": row["trade_date"],
                "state": state.state.value, "filled_shares": state.cumulative_filled,
                "quantity": command.quantity, "submit_claims": 1,
                "broker_attempts_max": 0 if row["submit_stage"] == "NOT_SENT" else 1,
                "submit_stage": row["submit_stage"], "cancel_stage": row["cancel_stage"],
                "reconcile_required": bool(row["reconcile_required"]), "fills": fills}
        if self.market == "US":
            aggregate = con.execute("SELECT payload FROM journal WHERE kind='US_ORDER_TOTAL_OBSERVED' AND execution_id=? ORDER BY seq DESC LIMIT 1", (execution_id,)).fetchone()
            result.update(market="US", environment=self.environment, settlement_mode=command.settlement_mode,
                          original_order_id=self._us_origin(con, execution_id), fill_history_complete=False,
                          confirmed_filled_shares=state.cumulative_filled,
                          filled_shares=state.cumulative_filled if aggregate else None,
                          fill_status="BROKER_CUMULATIVE" if aggregate else "UNQUALIFIED")
        return result

    def status(self, execution_id):
        require(self._journal is not None, "RUNTIME_NOT_STARTED")
        with self._journal.connection(readonly=True) as con:
            return self._status(con, execution_id)

    def submit(self, command: Command):
        """Retired client entry: new exposure requires the canonical confirm path."""
        require(False, "CONFIRMED_REVIEW_REQUIRED")

    @serialized
    def _submit_engine(self, command: Command, *, review_id=None):
        require(type(command) is (UsCommand if self.market == "US" else Command), "INVALID_COMMAND")
        command.validate()
        require((command.account_id, command.trade_date) == (self.account_id, self.trade_date), "COMMAND_SESSION_MISMATCH")
        if self.market == "US":
            self.session.admit(command)
        execution_id = command.execution_id
        with self._transaction() as con:
            reviews = self._reviews(con)
            strategy = self._strategies(con).get(command.strategy_id)
            require(strategy is None or strategy.entry == command, "STRATEGY_ENTRY_ALREADY_BOUND")
            if review_id is None:
                require(not any(r.draft.command.account_id == command.account_id and
                    (r.draft.command.request_id == command.request_id or
                     r.draft.command.intent_id == command.intent_id) for r in reviews.values()),
                    "CONFIRMED_REVIEW_REQUIRED")
            else:
                review = self._review(reviews, review_id)
                require(review.state in {"CONFIRMED", "EXECUTION"} and
                        command_payload(review.draft.command) == command_payload(command), "CONFIRMED_REVIEW_REQUIRED")
            claimed = self._claim_command(con, command, {"review_id": review_id} if review_id else {})
            if claimed and review_id is not None:
                self._review_append(con, "REVIEW_EXECUTION_CLAIMED", review_id, review.revision,
                                    {"digest": review.snapshot["digest"], "execution_id": execution_id})
                binding = self._candidate_binding(con, execution_id)
                if binding and binding["protection"] is not None:
                    self._strategy_append(con, "STRATEGY_CREATED", command.strategy_id, command.revision,
                        {"review_id": review_id, "review_digest": review.snapshot["digest"],
                         "rules": asdict(StrategyRules(**binding["protection"])), "consent_policy": CONSENT_POLICY,
                         "source_snapshot": source_payload(SourceSnapshot(binding["selection"]["pending_id"],
                             self._now().isoformat(), binding["selection"]))})
            if claimed:
                self._fault("before_claim_commit")
        if not claimed:
            return self.status(execution_id)
        if review_id is not None and binding and binding["protection"] is not None:
            self._watch_strategy_prices()
        return self._dispatch_claimed(command)

    def _claim_command(self, con, command, lineage):
        """Only called inside this owner's transaction, for review or consent exit."""
        command.validate()
        require((command.account_id, command.trade_date) == (self.account_id, self.trade_date),
                "COMMAND_SESSION_MISMATCH")
        execution_id = command.execution_id
        existing = con.execute("SELECT * FROM intents WHERE account_id=? AND (request_id=? OR intent_id=?)",
                               (command.account_id, command.request_id, command.intent_id)).fetchall()
        if existing:
            require(len(existing) == 1 and existing[0]["payload"] == encoded(command_payload(command)), "IDEMPOTENCY_CONFLICT")
            return False
        con.execute("INSERT INTO intents VALUES (?,?,?,?,?)", (execution_id, command.account_id,
                    command.request_id, command.intent_id, encoded(command_payload(command))))
        state = OrderProgress(execution_id, command.quantity, OrderStatus.PENDING, self._now())
        con.execute("INSERT INTO orders(execution_id,account_id,trade_date,state,submit_stage) VALUES (?,?,?,?,?)",
                    (execution_id, command.account_id, command.trade_date, state_payload(state), "CLAIMED"))
        self._append(con, "SUBMIT_CLAIMED", execution_id,
                     {"command": command_payload(command), "initial_state": json.loads(state_payload(state)), **lineage})
        return True

    def _dispatch_claimed(self, command, *, cash_guard=False):
        # The caller owns a newly committed claim. Never scan/replay claims here.
        execution_id = command.execution_id
        self._fault("after_claim")
        try:
            if cash_guard:
                returned = self.session.submit(command, before_send=lambda: self._check_cash_exit(command))
            else:
                returned = self.session.submit(command)  # deliberately outside SQLite/mutex
        except Exception:
            self._uncertain(execution_id, "SUBMIT_UNKNOWN")
            return self.status(execution_id)
        if returned.not_sent is not None:
            self._not_sent(command, returned.not_sent)
            return self.status(execution_id)
        self._fault("after_effect")
        broker_id = returned.order_id
        if self.market == "US":
            self._record_us_origin(execution_id, returned.original_id)
        if broker_id:
            self._bind(execution_id, self._key(command.account_id, command.trade_date, broker_id))
        if returned.rejected:
            self._rejected_return(execution_id)
        with self._transaction() as con:
            con.execute("UPDATE orders SET submit_stage='RETURNED' WHERE execution_id=?", (execution_id,))
            self._append(con, "SUBMIT_RETURNED", execution_id, {"broker_id": broker_id or None})
        self._fault("after_binding")
        self.query()  # one readback; Pending/timeout never causes another submit
        return self.status(execution_id)

    @staticmethod
    def _review_records(con):
        return [(r["kind"], r["occurred_at"], json.loads(r["payload"])) for r in con.execute(
            "SELECT kind,occurred_at,payload FROM journal WHERE kind LIKE 'REVIEW_%' ORDER BY seq")]

    def _reviews(self, con):
        return replay(self._review_records(con))

    @staticmethod
    def _review(reviews, review_id):
        from execution.validation import identifier
        identifier(review_id)
        require(review_id in reviews, "UNKNOWN_REVIEW")
        return reviews[review_id]

    def _review_append(self, con, kind, review_id, revision, extra):
        now = self._now().isoformat()
        payload = {"review_version": REVIEW_VERSION, "review_id": review_id,
                   "review_revision": revision, **extra}
        # The same pure replay validates writes and startup before session IO.
        reviews = replay([*self._review_records(con), (kind, now, payload)])
        execution_id = reviews[review_id].draft.command.execution_id
        self._append(con, kind, execution_id, payload, occurred_at=now)

    def _validate_draft(self, draft):
        require(self.session.date_matches(), "SESSION_DATE_EXPIRED")
        require(type(draft) is Draft, "INVALID_DRAFT")
        draft.validate()
        require(type(draft.command) is (UsCommand if self.market == "US" else Command), "COMMAND_MARKET_MISMATCH")
        require((draft.command.account_id, draft.command.trade_date) ==
                (self.account_id, self.trade_date), "COMMAND_SESSION_MISMATCH")
        if self.market == "US":
            self.session.admit(draft.command)

    @serialized
    def create_review(self, draft: Draft):
        self._validate_draft(draft)
        with self._transaction() as con:
            self._ensure_review(con, draft)
        return self.review_status(draft.review_id)

    def _ensure_review(self, con, draft):
        existing = self._reviews(con).get(draft.review_id)
        if existing is not None:
            require(existing.draft == draft, "REVIEW_IDEMPOTENCY_CONFLICT")
        else:
            command = draft.command
            require(not con.execute("SELECT 1 FROM intents WHERE account_id=? AND (request_id=? OR intent_id=?)",
                    (command.account_id, command.request_id, command.intent_id)).fetchone(), "IDENTITY_ALREADY_EXECUTED")
            self._review_append(con, "REVIEW_DRAFTED", draft.review_id, 1, {"draft": draft_payload(draft)})

    @staticmethod
    def _candidate_binding(con, execution_id):
        rows = con.execute("SELECT payload FROM journal WHERE kind='CANDIDATE_REVIEW_BOUND' AND execution_id=?",
                           (execution_id,)).fetchall()
        require(len(rows) <= 1, "CANDIDATE_BINDING_CONFLICT")
        return json.loads(rows[0][0]) if rows else None

    @serialized
    def prepare_candidate(self, draft, binding):
        self._validate_draft(draft)
        validate_binding(binding, draft)
        with self._transaction() as con:
            self._ensure_review(con, draft)
            previous = self._candidate_binding(con, draft.command.execution_id)
            if previous is None:
                require(self._reviews(con)[draft.review_id].state == "DRAFT", "CANDIDATE_BINDING_TOO_LATE")
                self._append(con, "CANDIDATE_REVIEW_BOUND", draft.command.execution_id, binding)
            else:
                require(previous == binding, "CANDIDATE_BINDING_CONFLICT")
        return self.preview_review(draft.review_id, expected_revision=1)

    def preview_review(self, review_id, *, expected_revision):
        from execution.validation import integer
        integer(expected_revision, positive=True)
        with self._transaction() as con:
            review = self._review(self._reviews(con), review_id)
            require(review.revision == expected_revision, "STALE_REVIEW_REVISION")
            require(review.state in {"DRAFT", "PREVIEW"}, "REVIEW_NOT_PREVIEWABLE")
            if review.state == "DRAFT":
                value = snapshot(review.draft, review.revision, self._now().isoformat())
                self._review_append(con, "REVIEW_PREVIEWED", review_id, review.revision, {"snapshot": value})
        return self.review_status(review_id)

    @serialized
    def revise_review(self, review_id, draft: Draft, *, expected_revision):
        from execution.validation import integer
        integer(expected_revision, positive=True)
        self._validate_draft(draft)
        with self._transaction() as con:
            review = self._review(self._reviews(con), review_id)
            require(self._candidate_binding(con, review.draft.command.execution_id) is None, "CANDIDATE_REVISE_AT_OWNER")
            require(review.revision == expected_revision, "STALE_REVIEW_REVISION")
            self._review_append(con, "REVIEW_REVISED", review_id, review.revision + 1, {"draft": draft_payload(draft)})
        return self.review_status(review_id)

    def reject_review(self, review_id, *, expected_revision, reason="USER_REJECTED"):
        from execution.validation import integer
        integer(expected_revision, positive=True)
        with self._transaction() as con:
            review = self._review(self._reviews(con), review_id)
            require(review.revision == expected_revision, "STALE_REVIEW_REVISION")
            self._review_append(con, "REVIEW_REJECTED", review_id, review.revision, {"reason": reason})
        return self.review_status(review_id)

    @serialized
    def confirm_review(self, review_id, *, expected_digest, expected_revision, candidate_selection=None):
        expected(expected_revision, expected_digest)
        with self._transaction() as con:
            review = self._review(self._reviews(con), review_id)
            require(review.revision == expected_revision, "STALE_REVIEW_REVISION")
            require(review.state in {"PREVIEW", "CONFIRMED", "EXECUTION"}, "REVIEW_NOT_CONFIRMABLE")
            require(review.snapshot is not None and review.snapshot["digest"] == expected_digest,
                    "REVIEW_DIGEST_MISMATCH")
            binding = self._candidate_binding(con, review.draft.command.execution_id)
            require((binding is None and candidate_selection is None) or
                    (binding is not None and binding["selection"] == candidate_selection), "CANDIDATE_SELECTION_REQUIRED")
            self._validate_draft(review.draft)
            strategy = self._strategies(con).get(review.draft.command.strategy_id)
            require(strategy is None or strategy.entry == review.draft.command, "STRATEGY_ENTRY_ALREADY_BOUND")
            if review.state == "PREVIEW":
                self._review_append(con, "REVIEW_CONFIRMED", review_id, review.revision, {"digest": expected_digest})
                self._fault("before_confirmation_commit")
        # No background replay. An explicit repeat confirm can continue only if
        # no submit claim exists; the engine atomically claims at most once.
        self._fault("after_confirmation")
        self._submit_engine(review.draft.command, review_id=review_id)
        return self.review_status(review_id)

    def _review_output(self, con, review_id, review):
        audit = [{"seq": r["seq"], "kind": r["kind"], "occurred_at": r["occurred_at"],
                  "payload": json.loads(r["payload"])} for r in con.execute(
            "SELECT * FROM journal WHERE execution_id=? AND kind LIKE 'REVIEW_%' ORDER BY seq",
            (review.draft.command.execution_id,))]
        return {"review_id": review_id, "review_revision": review.revision, "state": review.state,
                "created_at": review.created_at, "updated_at": review.updated_at,
                "draft": draft_payload(review.draft), "snapshot": review.snapshot,
                "confirmed_at": review.confirmed_at, "execution_id": review.execution_id,
                "execution": self.status(review.execution_id) if review.execution_id else None,
                "audit": audit,
                "execution_audit": [{"seq": r["seq"], "kind": r["kind"], "occurred_at": r["occurred_at"],
                                     "payload": json.loads(r["payload"])} for r in con.execute(
                    "SELECT * FROM journal WHERE execution_id=? AND kind NOT LIKE 'REVIEW_%' ORDER BY seq",
                    (review.draft.command.execution_id,))]}

    def review_status(self, review_id):
        require(self._started, "RUNTIME_NOT_STARTED")
        with self._journal.connection(readonly=True) as con:
            review = self._review(self._reviews(con), review_id)
            return self._review_output(con, review_id, review)

    def list_reviews(self):
        require(self._started, "RUNTIME_NOT_STARTED")
        with self._journal.connection(readonly=True) as con:
            return [self._review_output(con, key, value) for key, value in self._reviews(con).items()]

    @serialized
    def readback(self):
        """Read the same session and Journal without ingest, reconcile or effects.

        GET consumers must never wake the strategy pump or mutate the journal.
        Missing SDK sources remain partial alongside the evidence that exists.
        """
        require(self.market == "TW", "US_READBACK_PRESENTATION_NOT_IMPLEMENTED")
        from .read_projection import project
        require(self._started, "RUNTIME_NOT_STARTED")
        started = self._now().isoformat()
        try:
            batch = self.session.query(partial=True)
        except Exception as exc:
            batch = QueryBatch((), frozenset(), 0, sources=(SourceRead("KGI.Session", "UNAVAILABLE",
                reason=exc.code if isinstance(exc, ExecutionRejected) else "SDK_READ_FAILED"),))
        inventory, inventory_error = None, None
        try:
            inventory = self.session.cash_inventory(self._now, partial=True)
        except Exception as exc:
            inventory_error = exc.code if isinstance(exc, ExecutionRejected) else "SDK_READ_FAILED"
        received = self._now().isoformat()
        with self._journal.connection(readonly=True) as con:
            observations, diagnostics = [], []
            for index, row in enumerate(con.execute(
                    "SELECT seq,payload,occurred_at FROM journal WHERE kind='BROKER_OBSERVATION' ORDER BY seq")):
                try:
                    observation = observation_from(json.loads(row["payload"]))
                except (ValueError, TypeError, KeyError, AttributeError, ExecutionRejected):
                    # Historical unbound callbacks may lack a broker identity.
                    # Keep their immutable bytes; expose only a diagnostic, never
                    # invent an order key or let one row hide all valid reports.
                    diagnostics.append(ReportDiagnostic("Journal.BROKER_OBSERVATION", index,
                        "INVALID_JOURNAL_OBSERVATION", {"JournalSeq": str(row["seq"])}, None, None))
                    continue
                observations.append((observation, row["occurred_at"], False))
            if diagnostics:
                batch = replace(batch, diagnostics=(*batch.diagnostics, *diagnostics),
                    sources=(*batch.sources, SourceRead("Journal.BROKER_OBSERVATION", "PARTIAL",
                        len(observations), "INVALID_JOURNAL_OBSERVATION")))
            managed = {}
            for row in con.execute("SELECT * FROM orders WHERE broker_id IS NOT NULL"):
                command = self._command(con, row["execution_id"])
                managed[BrokerKey(row["account_id"], row["trade_date"], row["broker_id"])] = {
                    "execution_id": row["execution_id"], "space_id": command.space_id,
                    "identity": (command.symbol, command.action, command.condition, command.lot),
                    "shares_per_unit": command.shares_per_unit, "state": state_from(json.loads(row["state"])).state.value}
        observations.extend((o, received, True) for o in (*batch.observations, *batch.snapshots))
        result = project(trade_date=self.trade_date, generation=self.session.generation,
            queried_at=started, received_at=received, batch=batch, observations=observations,
            managed=managed, reviews=self.list_reviews(), inventory=inventory, inventory_error=inventory_error)
        transport_failed = any(s.reason == "SDK_TRANSPORT_FAILED" for s in batch.sources)
        if transport_failed and self._managed:
            self.session.disconnected.set()
        self._record_broker_read(result.quality, batch.sources, failure_kind="TRANSPORT" if transport_failed else None)
        return asdict(result)

    @staticmethod
    def _strategy_records(con):
        return [(r["kind"], r["occurred_at"], json.loads(r["payload"])) for r in con.execute(
            "SELECT kind,occurred_at,payload FROM journal WHERE kind LIKE 'STRATEGY_%' ORDER BY seq")]

    def _strategies(self, con):
        return replay_strategies(self._strategy_records(con), self._reviews(con))

    @staticmethod
    def _strategy(strategies, strategy_id):
        from execution.validation import identifier
        identifier(strategy_id)
        require(strategy_id in strategies, "UNKNOWN_STRATEGY")
        return strategies[strategy_id]

    def _strategy_append(self, con, kind, strategy_id, revision, extra):
        now = self._now().isoformat()
        payload = {"strategy_version": STRATEGY_VERSION, "strategy_id": strategy_id,
                   "strategy_revision": revision, **extra}
        strategies = replay_strategies([*self._strategy_records(con), (kind, now, payload)], self._reviews(con))
        self._append(con, kind, strategies[strategy_id].entry.execution_id, payload, occurred_at=now)

    def create_strategy(self, review_id, rules: StrategyRules, source: SourceSnapshot, *, expected_digest):
        require(type(rules) is StrategyRules, "INVALID_STRATEGY_RULES")
        rules.validate()
        extra = {"review_id": review_id, "review_digest": expected_digest, "rules": asdict(rules),
                 "source_snapshot": source_payload(source), "consent_policy": CONSENT_POLICY}
        with self._transaction() as con:
            review = self._review(self._reviews(con), review_id)
            require(review.state == "EXECUTION", "EXECUTED_STRATEGY_REVIEW_REQUIRED")
            command = review.draft.command
            require(command.trade_date == self.trade_date, "COMMAND_SESSION_MISMATCH")
            sid = command.strategy_id
            existing = self._strategies(con).get(sid)
            if existing is None:
                self._strategy_append(con, "STRATEGY_CREATED", sid, command.revision, extra)
            else:
                created = next(p for kind, _, p in self._strategy_records(con)
                               if kind == "STRATEGY_CREATED" and p["strategy_id"] == sid)
                require(all(created.get(k) == v for k, v in extra.items()), "STRATEGY_IDEMPOTENCY_CONFLICT")
        self._watch_strategy_prices()
        self._wake_strategies()
        return self.strategy_status(sid)

    def _strategy_request(self, con, sid, kind, revision, extra):
        from execution.validation import identifier, integer
        identifier(extra["request_id"])
        integer(revision, positive=True)
        strategy = self._strategy(self._strategies(con), sid)
        prior = strategy.requests.get(extra["request_id"])
        if kind == "STRATEGY_PRICE_OBSERVED":
            filled = prior[1].get("filled_quantity") if prior else self._status(con, strategy.entry.execution_id)["filled_shares"]
            require(filled is not None, "ENTRY_FILL_QUANTITY_UNAVAILABLE")
            extra = {**extra, "filled_quantity": filled}
        require(strategy.entry.account_id == self.account_id and strategy.entry.trade_date <= self.trade_date,
                "COMMAND_SESSION_MISMATCH")
        payload = {"strategy_version": STRATEGY_VERSION, "strategy_id": sid,
                   "strategy_revision": revision, **extra}
        payload = json.loads(encoded(payload))
        prior = strategy.requests.get(extra["request_id"])
        if prior is not None:
            require(prior == (kind, payload), "STRATEGY_IDEMPOTENCY_CONFLICT")
            return False
        if kind == "STRATEGY_EXIT_REQUESTED" and extra["target_position"] > 0:
            # Reductions can only lower actual, unreserved exposure. Future fills
            # remain subject to this target and the remaining entry is cancelled.
            view = self._strategy_quantities(con, strategy)
            require(extra["target_position"] < view["effective_position"] and
                    extra["target_position"] <= view["effective_position"] - view["reserved_exit_quantity"],
                    "NEW_EXPOSURE_REQUIRES_PREVIEW_CONFIRM")
        self._strategy_append(con, kind, sid, revision, extra)
        return True

    def revise_strategy(self, strategy_id, rules: StrategyRules, source: SourceSnapshot, *,
                        request_id, expected_revision):
        from execution.validation import integer
        integer(expected_revision, positive=True)
        require(type(rules) is StrategyRules, "INVALID_STRATEGY_RULES")
        rules.validate()
        with self._transaction() as con:
            self._strategy_request(con, strategy_id, "STRATEGY_REVISED", expected_revision + 1,
                                   {"request_id": request_id, "rules": asdict(rules),
                                    "source_snapshot": source_payload(source)})
        self._watch_strategy_prices()
        self._evaluate_latest_prices()
        self._wake_strategies()
        return self.strategy_status(strategy_id)

    def exit_strategy(self, strategy_id, source: SourceSnapshot, *, request_id, expected_revision,
                      target_position=0):
        require(self.strategy_effects, "STRATEGY_EFFECTS_DISABLED")
        from execution.validation import integer
        integer(target_position)
        with self._transaction() as con:
            appended = self._strategy_request(con, strategy_id, "STRATEGY_EXIT_REQUESTED", expected_revision,
                {"request_id": request_id, "target_position": target_position,
                 "reason": "REDUCE" if target_position else "MANUAL", "source_snapshot": source_payload(source)})
            if appended:
                self._fault("before_strategy_target_commit")
        self._fault("after_strategy_target_commit")
        self._watch_strategy_prices()
        self._evaluate_latest_prices()
        self._wake_strategies()
        return self.strategy_status(strategy_id)

    def observe_strategy_price(self, strategy_id, source: SourceSnapshot, *, request_id,
                               expected_revision, symbol, price):
        require(not self.native_prices, "NATIVE_PRICE_CALLBACK_REQUIRED")
        require(self.strategy_effects, "STRATEGY_EFFECTS_DISABLED")
        with self._transaction() as con:
            self._strategy_request(con, strategy_id, "STRATEGY_PRICE_OBSERVED", expected_revision,
                {"request_id": request_id, "symbol": symbol, "price": price,
                 "source_snapshot": source_payload(source)})
        self._wake_strategies()
        return self.strategy_status(strategy_id)

    def _strategy_quantities(self, con, strategy):
        return quantities(strategy, self._status(con, strategy.entry.execution_id),
                          [self._status(con, c.execution_id) for c in strategy.exits], self.trade_date)

    def _refresh_cash_inventory(self):
        try:
            self._cash_inventory = self.session.cash_inventory(self._now)
        except Exception as exc:
            # Do not retain a previously successful snapshot after query failure.
            self._cash_inventory = {"error": exc.code if isinstance(exc, ExecutionRejected)
                                    else "CASH_INVENTORY_UNAVAILABLE"}

    def cash_inventory_status(self):
        """Metadata only; status does not query the broker or expose holdings."""
        evidence = self._cash_inventory
        reason = "CASH_INVENTORY_NOT_QUERIED"
        if evidence:
            reason = evidence.get("error") or "SELLABLE_SEMANTICS_UNVERIFIED"
            if "queried_at" in evidence and (evidence["generation"] != self.session.generation or
                    not 0 <= (self._now() - datetime.fromisoformat(evidence["queried_at"])).total_seconds() <= 5):
                reason = "CASH_INVENTORY_STALE"
        return {"required": self.session.cash_inventory_required, "status": "UNVERIFIED",
                "reason": reason, "sellable_quantity": None, "protection_qualified": False,
                "query_status": "AVAILABLE" if evidence and "holdings" in evidence else
                                "UNAVAILABLE" if evidence else "NOT_QUERIED",
                "received_at": evidence.get("received_at") if evidence else None,
                "source_as_of": None, "report_complete": False,
                "quarantined_rows": len(evidence.get("diagnostics", ())) if evidence else 0,
                "source": "Account.InventorySum(B)+Account.OrderReport"}

    def _cash_exit_view(self, con, symbol, *, exclude_execution_id=None):
        view = self.cash_inventory_status()
        evidence = self._cash_inventory
        total, upper, reserved, open_sells = None, None, 0, None
        # Reuse all canonical sell claims across spaces/strategies and manual
        # commands. No separate allocation/position table, no inferred fills.
        reservations, known = {}, {}
        for row in con.execute("SELECT execution_id FROM orders"):
            if row[0] == exclude_execution_id:
                continue
            command = self._command(con, row[0])
            if (command.symbol, command.action, command.condition) != (symbol, "Sell", "CASH"):
                continue
            order = self._status(con, row[0])
            if order["submit_stage"] == "NOT_SENT":
                continue
            key = BrokerKey(self.account_id, command.trade_date, order["broker_order_id"]).identity if order["broker_order_id"] else command.execution_id
            known[key] = command
            # Strategy reservations remain occupied even after rejected/cancelled
            # outcomes, matching the existing immutable claim contract.
            child = con.execute("SELECT 1 FROM journal WHERE kind='SUBMIT_CLAIMED' AND execution_id=? AND json_extract(payload,'$.strategy_id') IS NOT NULL", (row[0],)).fetchone()
            if child or order["reconcile_required"] or order["state"] not in {s.value for s in TERMINAL}:
                reservations[key] = max(0, command.quantity - order["filled_shares"])
        reserved = sum(reservations.values())
        if evidence and view["reason"] == "SELLABLE_SEMANTICS_UNVERIFIED":
            total = evidence["holdings"].get(symbol)  # absent is unknown, never zero
            if any(d.account_matches is not False and (d.trade_date is None or d.trade_date >= self.trade_date)
                   and d.fields.get("StockID") in {None, "", symbol} for d in evidence["diagnostics"]):
                return {**view, "reason": "CASH_OPEN_SELL_AMBIGUOUS", "cash_total_upper_bound": total,
                        "reserved_quantity": reserved, "open_sell_upper_bound": None,
                        "remaining_cash_upper_bound": None, "executable_quantity": 0}
            latest = {}
            for report in evidence["orders"]:
                if report.symbol != symbol or (report.action, report.condition) != ("Sell", "CASH") or report.key.trade_date != self.trade_date:
                    continue
                old = latest.get(report.key.identity)
                if old is None or report.source_time > old.source_time:
                    latest[report.key.identity] = report
                elif report.source_time == old.source_time and (report.kind, report.remaining) != (old.kind, old.remaining):
                    return {**view, "reason": "CASH_OPEN_SELL_AMBIGUOUS", "cash_total_upper_bound": total,
                            "reserved_quantity": reserved, "open_sell_upper_bound": None,
                            "remaining_cash_upper_bound": None, "executable_quantity": 0}
            combined = dict(reservations)
            unknown_unit = False
            open_sells = 0
            for key, report in latest.items():
                if report.kind == "CANCELLED":
                    continue
                unit = known[key].shares_per_unit if key in known else 1 if report.lot == "Odd" else None
                if unit is None:
                    unknown_unit = True
                    continue
                amount = report.remaining * unit
                open_sells += amount
                combined[key] = max(combined.get(key, 0), amount)
            upper = max(0, total - sum(combined.values())) if total is not None and not unknown_unit else None
            if unknown_unit:
                open_sells = None
        # A conservative ceiling, not a certification of immediately sellable
        # stock or guaranteed protection. Broker rejection/fills remain truth.
        return {**view, "cash_total_upper_bound": total, "reserved_quantity": reserved,
                "open_sell_upper_bound": open_sells, "remaining_cash_upper_bound": upper,
                "executable_quantity": upper if upper is not None else 0}

    def _check_cash_exit(self, command):
        # Called immediately before create_order, serialized by the SDK owner.
        # Never resize/replay an immutable claim when the ceiling has changed.
        self._refresh_cash_inventory()
        with self._transaction() as con:
            view = self._cash_exit_view(con, command.symbol, exclude_execution_id=command.execution_id)
            allowed = view["executable_quantity"] >= command.quantity
            self._append(con, "CASH_EXIT_CAPACITY_CHECKED", command.execution_id,
                         {"trade_date": self.trade_date, "quantity": command.quantity,
                          "allowed": allowed, "capacity": view})
        return allowed

    def _not_sent(self, command, reason):
        """Only the adapter's pre-create_order outcome can release this claim."""
        with self._transaction() as con:
            row = self._row(con, command.execution_id)
            require(row["submit_stage"] == "CLAIMED" and row["broker_id"] is None,
                    "NOT_SENT_PROOF_CONFLICT")
            state = state_from(json.loads(row["state"]))
            require(state.cumulative_filled == 0, "NOT_SENT_PROOF_CONFLICT")
            self._save(con, command.execution_id, self._reduce(state, EventKind.REJECTED))
            strategy = self._strategy(self._strategies(con), command.strategy_id)
            self._append(con, "SUBMIT_NOT_SENT", command.execution_id,
                {"reason": reason, "sdk_attempted": False,
                 "resume_token": [strategy.revision, len(strategy.requests)]})
            con.execute("UPDATE orders SET submit_stage='NOT_SENT',reconcile_required=0 WHERE execution_id=?",
                        (command.execution_id,))

    def strategy_status(self, strategy_id):
        require(self._started, "RUNTIME_NOT_STARTED")
        with self._journal.connection(readonly=True) as con:
            con.execute("BEGIN")  # one read snapshot across strategy, orders and fills
            strategy = self._strategy(self._strategies(con), strategy_id)
            return {"strategy_id": strategy_id, "strategy_revision": strategy.revision,
                    "space_id": strategy.entry.space_id, "owner_id": strategy.owner_id, "source": strategy.source,
                    "review_id": strategy.review_id, "review_digest": strategy.review_digest,
                    "entry_execution_id": strategy.entry.execution_id, "rules": asdict(strategy.rules),
                    "source_snapshot": strategy.source_snapshot, "created_at": strategy.created_at,
                    "updated_at": strategy.updated_at, "exit_owner": strategy.exit_owner,
                    "exit_reason": strategy.exit_reason, "consent_policy": CONSENT_POLICY,
                    "exit_initiation": "OPERATOR" if strategy.exit_reason in {"MANUAL", "REDUCE"} else
                                       "AUTOMATIC_PRICE_TRIGGER" if strategy.exit_reason else "NONE",
                    "protection_mode": strategy.rules.protection_mode,
                    "broker_native_protection": "NOT_SUPPORTED", "strategy_error": self.strategy_error,
                    "strategy_effects": self.strategy_effects or strategy.rules.enabled,
                    "price_source_status": self.price_source_status(strategy.entry.symbol, strategy.entry.lot == "Odd"),
                    "price_input": "NATIVE_SESSION_CALLBACK" if self.native_prices else "EXPLICIT_SOURCE_OBSERVATIONS",
                    "session_date_matches": self.session.date_matches(),
                    "entry_trade_date": strategy.entry.trade_date, "exit_trade_date": self.trade_date,
                    "cash_inventory": self._cash_exit_view(con, strategy.entry.symbol),
                    **self._strategy_quantities(con, strategy),
                    "entry": self._status(con, strategy.entry.execution_id),
                    "exits": [self._status(con, c.execution_id) for c in strategy.exits],
                    "audit": [{"kind": k, "occurred_at": t, "payload": p}
                              for k, t, p in self._strategy_records(con) if p["strategy_id"] == strategy_id]}

    def _wake_strategies(self, *, query=False):
        if self._parent is not None:
            self._parent._wake_strategies(query=query)
            return
        with self._mutex:
            self._strategy_query_needed |= query
            self._strategy_idle.clear()
            self._strategy_wake.set()

    def _watch_strategy_prices(self):
        if not self.native_prices:
            return
        with self._mutex, self._journal.connection(readonly=True) as con:
            self._price_strategies = tuple(self._strategies(con).values())
            symbols = {(s.entry.symbol, s.entry.lot == "Odd") for s in self._price_strategies
                       if s.entry.account_id == self.account_id and s.entry.trade_date <= self.trade_date}
        for symbol, odd in symbols:
            try:
                self.session.watch_price(symbol, odd)
            except Exception:
                self._price_error = "NATIVE_PRICE_SOURCE_UNAVAILABLE"
        if self.us_runtime is not None:
            self.us_runtime._watch_strategy_prices()

    def price_source_status(self, symbol=None, odd_lot=None):
        if not self.native_prices:
            return {"status": "EXPLICIT_SOURCE_OBSERVATIONS", "native_qualified": False}
        values = ([self._prices[(symbol, odd_lot)]] if (symbol, odd_lot) in self._prices else []) if symbol else list(self._prices.values())
        fresh = [p for p in values if p.get("trade_progress")
                 and 0 <= (self._now() - datetime.fromisoformat(p["observed_at"])).total_seconds() <= 5]
        waiting = "WAITING_TRADE_PROGRESS" if values and not any(p.get("trade_progress") for p in values) else "STALE" if values else "WAITING_NATIVE_TRADE"
        return {"status": "FRESH" if fresh else self._price_error or waiting,
                "native_qualified": bool(fresh), "protection_effects_enabled": self.strategy_effects or any(s.rules.enabled for s in self._price_strategies if symbol is None or s.entry.symbol == symbol),
                "source": "KGI.USQuote.set_cb_all" if self.market == "US" else "KGI.Quote.set_cb_all", "max_age_seconds": 5}

    def _evaluate_latest_prices(self):
        if not self.native_prices:
            return
        with self._mutex, self._transaction() as con:
            for sid, strategy in self._strategies(con).items():
                if not (self.strategy_effects or strategy.rules.enabled):
                    continue
                evidence = self._prices.get((strategy.entry.symbol, strategy.entry.lot == "Odd"))
                if not evidence or not evidence.get("trade_progress") or not 0 <= (self._now() - datetime.fromisoformat(evidence["observed_at"])).total_seconds() <= 5:
                    continue
                filled = self._status(con, strategy.entry.execution_id)["filled_shares"]
                if not filled:
                    continue
                reason, target = trigger_target(strategy.rules, evidence["price"], filled, strategy.entry.shares_per_unit)
                if reason is None or strategy.target_position is not None and target >= strategy.target_position:
                    continue
                identity = "native-price-" + digest([self.session.generation, sid, strategy.revision, evidence["observed_at"], evidence["price"], filled])
                self._strategy_request(con, sid, "STRATEGY_PRICE_OBSERVED", strategy.revision,
                    {"request_id": identity, "symbol": strategy.entry.symbol, "price": evidence["price"],
                     "source_snapshot": source_payload(SourceSnapshot("KGI_NATIVE_TICK", evidence["observed_at"], evidence))})
            self._price_strategies = tuple(self._strategies(con).values())

    def _native_price(self, raw, generation):
        if generation != self.session.generation:
            return
        try:
            require(self.session.date_matches(), "SESSION_DATE_EXPIRED")
            evidence = price_observation(raw, self._now(), market=self.market)
            with self._mutex:
                key = (evidence["symbol"], evidence["odd_lot"])
                previous = self._prices.get(key)
                # subscribe_all includes depth updates. Cumulative trade volume
                # must advance before a retained close can be called a new trade.
                if previous and evidence["total_volume"] <= previous["total_volume"]:
                    return
                if previous and (previous["observed_at"] > evidence["observed_at"] or
                    (previous["observed_at"] == evidence["observed_at"] and previous["price"] == evidence["price"])):
                    return
                evidence["trade_progress"] = previous is not None
                self._prices[key] = evidence
                self._price_error = None
                if previous is None:
                    return
                candidates = [s for s in self._price_strategies
                    if (s.entry.symbol, s.entry.lot == "Odd") == key and s.entry.trade_date <= self.trade_date
                    and (self.strategy_effects or s.rules.enabled) and price_trigger(s.rules, evidence["price"]) is not None]
                if not candidates:
                    return
                with self._transaction() as con:
                    for sid, strategy in self._strategies(con).items():
                        if (strategy.entry.symbol, strategy.entry.lot == "Odd") != key or strategy.entry.trade_date > self.trade_date:
                            continue
                        if not (self.strategy_effects or strategy.rules.enabled):
                            continue
                        filled = self._status(con, strategy.entry.execution_id)["filled_shares"]
                        reason, target = trigger_target(strategy.rules, evidence["price"], filled or 0, strategy.entry.shares_per_unit)
                        if reason is None or not filled or (strategy.target_position is not None and target >= strategy.target_position):
                            continue
                        identity = "native-price-" + digest([generation, sid, strategy.revision,
                            evidence["observed_at"], evidence["price"]])
                        source = SourceSnapshot("KGI_NATIVE_TICK", evidence["observed_at"], evidence)
                        self._strategy_request(con, sid, "STRATEGY_PRICE_OBSERVED", strategy.revision,
                            {"request_id": identity, "symbol": key[0], "price": evidence["price"],
                             "source_snapshot": source_payload(source)})
                    projection = tuple(self._strategies(con).values())
                self._price_strategies = projection
            self._wake_strategies()
        except Exception:
            self._price_error = "NATIVE_PRICE_REJECTED"

    def _strategy_loop(self):
        """Runtime-owned effect pump. SDK callbacks only journal and wake it.

        In particular, never wait for the SDK lock from a broker callback that
        may itself be awaited by create_order/cancel_order on another thread.
        """
        while True:
            self._strategy_wake.wait()
            if self._strategy_stop.is_set():
                return
            with self._mutex:
                self._strategy_wake.clear()
                query, self._strategy_query_needed = self._strategy_query_needed, False
            try:
                with self._journal.connection(readonly=True) as con:
                    active = bool(self._strategies(con))
                if self.us_runtime is not None:
                    with self.us_runtime._journal.connection(readonly=True) as con:
                        active = active or bool(self.us_runtime._strategies(con))
                if active:
                    if query:
                        self.query()
                        if self.us_runtime is not None:
                            self.us_runtime.query()
                    self._coordinate_strategies()
                    if self.us_runtime is not None:
                        self.us_runtime._coordinate_strategies()
                self.strategy_error = None
            except Exception as exc:
                self.strategy_error = type(exc).__name__
                with self._transaction() as con:
                    self._append(con, "COORDINATION_FAILED", None, {"error_type": self.strategy_error})
            with self._mutex:
                if not self._strategy_wake.is_set():
                    self._strategy_idle.set()

    @serialized
    def _coordinate_strategies(self):
        if self._desired != "ONLINE":
            return
        commands, cancels = [], []
        if self.session.cash_inventory_required:
            with self._journal.connection(readonly=True) as con:
                needed = any(s.target_position is not None and
                    self._strategy_quantities(con, s)["available_exit_quantity"] > 0
                    for s in self._strategies(con).values())
            if needed:
                self._refresh_cash_inventory()
        with self._transaction() as con:
            for sid, strategy in self._strategies(con).items():
                if not (self.strategy_effects or strategy.rules.enabled):
                    continue
                if strategy.target_position is None or strategy.entry.trade_date > self.trade_date:
                    continue
                if strategy.exits:
                    stopped = con.execute("SELECT payload FROM journal WHERE kind='SUBMIT_NOT_SENT' AND execution_id=?",
                                          (strategy.exits[-1].execution_id,)).fetchone()
                    if stopped and json.loads(stopped[0])["resume_token"] == [strategy.revision, len(strategy.requests)]:
                        continue  # New operator revision/request required; never replay the failed intent.
                entry = self._status(con, strategy.entry.execution_id)
                if strategy.entry.trade_date == self.trade_date and entry["broker_order_id"] and entry["cancel_stage"] is None and entry["state"] not in {s.value for s in TERMINAL}:
                    cancels.append((strategy.entry.execution_id,
                        self._key(self.account_id, strategy.entry.trade_date, entry["broker_order_id"])))
                quantity = self._strategy_quantities(con, strategy)["available_exit_quantity"]
                if self.session.cash_inventory_required and not strategy.rules.enabled and strategy.entry.action == "Buy" and strategy.entry.condition == "CASH":
                    quantity = min(quantity, self._cash_exit_view(con, strategy.entry.symbol)["executable_quantity"])
                    quantity -= quantity % strategy.entry.shares_per_unit
                if quantity:
                    command = exit_command(strategy, quantity, self.trade_date)
                    require(self._claim_command(con, command, {"strategy_id": sid}), "STRATEGY_EXIT_ALREADY_CLAIMED")
                    self._strategy_append(con, "STRATEGY_EXIT_CLAIMED", sid, strategy.revision,
                        {"command": command_payload(command), "exit_owner": strategy.exit_owner,
                         "target_position": strategy.target_position})
                    self._fault("before_strategy_exit_claim_commit")
                    commands.append(command)
        # All quantities are reserved before any SDK effect; one pump dispatches
        # only its own new claims. Startup never retries abandoned claims.
        for execution_id, key in cancels:
            self.cancel(execution_id, key)
        for command in commands:
            with self._journal.connection(readonly=True) as con:
                per_order = self._strategy(self._strategies(con), command.strategy_id).rules.enabled
            self._dispatch_claimed(command, cash_guard=not per_order and self.session.cash_inventory_required and command.action == "Sell" and command.condition == "CASH")
        if cancels and not commands:
            self.query()

    def _verify_strategies(self, con):
        strategies = self._strategies(con)
        exit_claims = {}
        for sid, strategy in strategies.items():
            self._strategy_quantities(con, strategy)
            claims_so_far = []
            records = con.execute("SELECT seq,execution_id,payload FROM journal WHERE kind='STRATEGY_EXIT_CLAIMED' ORDER BY seq")
            for row in records:
                payload = json.loads(row["payload"])
                if payload["strategy_id"] != sid:
                    continue
                command = command_from(payload["command"])
                require(row["execution_id"] == strategy.entry.execution_id, "STRATEGY_JOURNAL_LINEAGE_MISMATCH")
                claim = con.execute("SELECT seq,payload FROM journal WHERE kind='SUBMIT_CLAIMED' AND execution_id=?",
                                    (command.execution_id,)).fetchone()
                require(claim is not None and claim["seq"] < row["seq"] and
                        json.loads(claim["payload"]).get("strategy_id") == sid and
                        self._command(con, command.execution_id) == command, "STRATEGY_ENGINE_CLAIM_MISMATCH")
                entered = 0
                for reduction in con.execute("SELECT payload FROM journal WHERE execution_id=? AND kind='ORDER_REDUCED' AND seq<?",
                                             (strategy.entry.execution_id, row["seq"])):
                    entered = max(entered, *(e["cumulative_filled"] for e in json.loads(reduction[0])["events"]), 0)
                claims_so_far.append(command)
                committed = sum(c.quantity for c in claims_so_far if not con.execute(
                    "SELECT 1 FROM journal WHERE kind='SUBMIT_NOT_SENT' AND execution_id=? AND seq<?",
                    (c.execution_id, row["seq"])).fetchone())
                require(committed <= entered - payload["target_position"], "STRATEGY_UNBACKED_EXIT_CLAIM")
                exit_claims[command.execution_id] = sid
        for row in con.execute("SELECT execution_id,payload FROM journal WHERE kind='SUBMIT_CLAIMED'"):
            sid = json.loads(row["payload"]).get("strategy_id")
            if sid is not None:
                require(exit_claims.get(row["execution_id"]) == sid, "STRATEGY_ENGINE_CLAIM_MISMATCH")
        for row in con.execute("SELECT seq,kind,execution_id,payload FROM journal WHERE kind LIKE 'STRATEGY_%'"):
            sid = json.loads(row["payload"])["strategy_id"]
            require(row["execution_id"] == strategies[sid].entry.execution_id, "STRATEGY_JOURNAL_LINEAGE_MISMATCH")
            if row["kind"] == "STRATEGY_CREATED":
                claim = con.execute("SELECT seq FROM journal WHERE kind='REVIEW_EXECUTION_CLAIMED' AND execution_id=?",
                                    (row["execution_id"],)).fetchone()
                require(claim is not None and claim[0] < row["seq"], "STRATEGY_PRECEDES_CONFIRMED_EXECUTION")

    def _verify_reviews(self, con):
        reviews = self._reviews(con)
        for row in con.execute("SELECT execution_id,payload FROM journal WHERE kind='SUBMIT_CLAIMED'"):
            claim = json.loads(row["payload"])
            review_id = claim.get("review_id")
            if review_id is not None:
                require(review_id in reviews and reviews[review_id].state == "EXECUTION" and
                        row["execution_id"] == reviews[review_id].execution_id and
                        claim["command"] == command_payload(reviews[review_id].draft.command),
                        "JOURNAL_REVIEW_CLAIM_MISMATCH")
        for review_id, review in reviews.items():
            command = review.draft.command
            # Old dated records remain inspectable; only confirm/new commands
            # must match the current session date.
            require(command.account_id == self.account_id, "JOURNAL_REVIEW_ACCOUNT_MISMATCH")
            rows = con.execute("SELECT * FROM intents WHERE account_id=? AND (request_id=? OR intent_id=?)",
                               (command.account_id, command.request_id, command.intent_id)).fetchall()
            if review.state == "EXECUTION":
                require(len(rows) == 1 and rows[0]["payload"] == encoded(command_payload(command)),
                        "JOURNAL_REVIEW_EXECUTION_MISMATCH")
                claim = con.execute("SELECT payload FROM journal WHERE kind='SUBMIT_CLAIMED' AND execution_id=?",
                                    (command.execution_id,)).fetchone()
                require(claim is not None and json.loads(claim[0]).get("review_id") == review_id,
                        "JOURNAL_REVIEW_CLAIM_MISMATCH")
            else:
                require(not rows, "JOURNAL_UNCONFIRMED_EXECUTION")
            for row in con.execute("SELECT execution_id,payload FROM journal WHERE kind LIKE 'REVIEW_%'"):
                payload = json.loads(row["payload"])
                if payload["review_id"] == review_id:
                    require(row["execution_id"] == command.execution_id, "JOURNAL_REVIEW_LINEAGE_MISMATCH")

    def _rejected_return(self, execution_id):
        with self._transaction() as con:
            state = state_from(json.loads(self._row(con, execution_id)["state"]))
            if state.state is OrderStatus.REJECTED:
                return
            if state.state is OrderStatus.UNKNOWN:
                state = self._reduce(state, EventKind.RECONCILE)
            self._save(con, execution_id, self._reduce(state, EventKind.REJECTED))
            self._append(con, "SUBMIT_REJECTED", execution_id, {"source": "Trade.operations.NewOrder.Failed"})

    def _uncertain(self, execution_id, reason):
        with self._transaction() as con:
            row = self._row(con, execution_id)
            state = state_from(json.loads(row["state"]))
            if state.state not in TERMINAL and state.state is not OrderStatus.UNKNOWN:
                self._save(con, execution_id, self._reduce(state, EventKind.TIMEOUT))
            con.execute("UPDATE orders SET reconcile_required=1 WHERE execution_id=?", (execution_id,))
            self._append(con, reason, execution_id, {"resend": False})

    def _bind(self, execution_id, key):
        key.validate()
        require(key == self._key(key.account_id, key.trade_date, key.order_id), "BROKER_MARKET_SCOPE_CONFLICT")
        with self._transaction() as con:
            row = self._row(con, execution_id)
            require((row["account_id"], row["trade_date"]) == (key.account_id, key.trade_date), "BROKER_SCOPE_CONFLICT")
            require(row["broker_id"] in {None, key.order_id}, "BROKER_ID_CONFLICT")
            con.execute("UPDATE orders SET broker_id=? WHERE execution_id=?", (key.order_id, execution_id))
            self._append(con, "BROKER_BOUND", execution_id, asdict(key))
        self._drain(key)

    @staticmethod
    def _us_origin(con, execution_id):
        rows = con.execute("SELECT payload FROM journal WHERE kind='US_ORIGIN_BOUND' AND execution_id=?",
                           (execution_id,)).fetchall()
        values = {json.loads(row[0])["original_id"] for row in rows}
        require(len(values) <= 1, "US_ORIGIN_ID_CONFLICT")
        return next(iter(values), None)

    def _record_us_origin(self, execution_id, original_id):
        if not original_id:
            return
        from execution.validation import identifier
        identifier(original_id)
        with self._transaction() as con:
            old = self._us_origin(con, execution_id)
            require(old in {None, original_id}, "US_ORIGIN_ID_CONFLICT")
            if old is None:
                self._append(con, "US_ORIGIN_BOUND", execution_id, {"original_id": original_id})

    def _callback(self, raw, generation):
        try:
            if generation != self.session.generation:
                return
            require(self.session.date_matches(), "SESSION_DATE_EXPIRED")
            observation = callback_observation(raw, self.account_id, self.trade_date)
            self._ingest(observation)
            self._wake_strategies(query=True)
        except Exception as exc:
            # Vendor exception text can contain credentials/account payloads.
            self.callback_error = type(exc).__name__
            with self._transaction() as con:
                con.execute("UPDATE orders SET reconcile_required=1 WHERE submit_stage!='NOT_SENT'")
                self._append(con, "CALLBACK_UNRESOLVED", None, {"error_type": self.callback_error})

    def _ingest(self, observation):
        require(observation.key == self._key(self.account_id, observation.key.trade_date,
                                             observation.key.order_id), "BROKER_MARKET_SCOPE_CONFLICT")
        with self._transaction() as con:
            con.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?)",
                        (observation.event_id, observation.key.identity, encoded(observation.payload())))
            if con.execute("SELECT changes()").fetchone()[0]:
                self._append(con, "BROKER_OBSERVATION", None, observation.payload(), "broker-" + observation.event_id)
        self._drain(observation.key)

    def _drain(self, key):
        with self._transaction() as con:
            row = con.execute("SELECT * FROM orders WHERE account_id=? AND trade_date=? AND broker_id=?",
                              (key.account_id, key.trade_date, key.order_id)).fetchone()
            if row is None:
                if key.order_id:
                    con.execute("INSERT OR IGNORE INTO external_orders VALUES (?,?,?)",
                                (key.identity, "external-" + key.identity, encoded(asdict(key))))
                return
            execution_id = row["execution_id"]
            observations = con.execute("SELECT payload FROM observations WHERE broker_key=? AND event_id NOT IN (SELECT event_id FROM applied)",
                                       (key.identity,)).fetchall()
        for value in observations:
            observation = observation_from(json.loads(value[0]))
            try:
                self._apply(execution_id, observation)
            except (ValueError, RuntimeError):
                self._uncertain(execution_id, "OBSERVATION_CONFLICT")

    def _apply(self, execution_id, observation):
        with self._transaction() as con:
            if con.execute("SELECT 1 FROM applied WHERE event_id=?", (observation.event_id,)).fetchone():
                return
            row = self._row(con, execution_id)
            command = self._command(con, execution_id)
            if self.market == "US":
                require(type(observation) is UsObservation and
                        observation.original_id == self._us_origin(con, execution_id), "US_ORIGIN_ID_CONFLICT")
                require(observation.settlement_mode in {None, command.settlement_mode}, "US_SETTLEMENT_CONFLICT")
            state = state_from(json.loads(row["state"]))
            require((observation.symbol, observation.action, observation.condition, observation.lot) ==
                    (command.symbol, command.action, command.condition, command.lot), "BROKER_IDENTITY_CONFLICT")
            kind = observation.kind
            if kind in {"ACCEPTED", "REJECTED"}:
                require(observation.quantity * command.shares_per_unit == command.quantity
                        and decimal(observation.price) == decimal(command.price), "BROKER_ORDER_CONFLICT")
            if kind == "DEAL":
                quantity = observation.quantity * command.shares_per_unit
                require(quantity > 0 and decimal(observation.price) > 0, "INVALID_FILL")
                prior = con.execute("SELECT * FROM fills WHERE broker_key=? AND fill_id=?",
                                    (observation.key.identity, observation.seqno)).fetchone()
                if prior:
                    require((prior["quantity"], decimal(prior["price"]), prior["source_time"]) ==
                            (quantity, decimal(observation.price), observation.source_time), "FILL_ID_CONFLICT")
                else:
                    con.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)", (observation.key.identity, observation.seqno,
                                execution_id, quantity, observation.price, observation.source_time))
                total = con.execute("SELECT coalesce(sum(quantity),0) FROM fills WHERE execution_id=?", (execution_id,)).fetchone()[0]
                require(total <= command.quantity, "OVERFILL")
                if total > state.cumulative_filled:
                    if state.state is OrderStatus.UNKNOWN:
                        state = self._reduce(state, EventKind.RECONCILE)
                    state = self._reduce(state, EventKind.FILLED if total == command.quantity else EventKind.PARTIAL_FILL,
                                         total=total, price=decimal(observation.price))
            elif kind == "CANCELLED":
                # Broker report is final for the remaining order; late deals still
                # pass through the same reducer and cannot be erased by cancellation.
                if state.state is OrderStatus.UNKNOWN:
                    state = self._reduce(state, EventKind.RECONCILE)
                if not state.cancel_requested and state.state not in TERMINAL:
                    state = self._reduce(state, EventKind.CANCEL_REQUESTED)
                if state.state not in {OrderStatus.FILLED, OrderStatus.REJECTED}:
                    state = self._reduce(state, EventKind.CANCELLED, total=state.cumulative_filled)
            elif kind == "ACCEPTED":
                # A late ACK never downgrades fills or terminal state.
                if state.state in {OrderStatus.PENDING, OrderStatus.UNKNOWN, OrderStatus.RECONCILING} and state.cumulative_filled == 0:
                    if state.state is OrderStatus.UNKNOWN:
                        state = self._reduce(state, EventKind.RECONCILE)
                    state = self._reduce(state, EventKind.ACCEPTED)
            elif kind == "REJECTED":
                if state.state is OrderStatus.UNKNOWN:
                    state = self._reduce(state, EventKind.RECONCILE)
                state = self._reduce(state, EventKind.REJECTED)
            elif kind == "CANCEL_ACK":
                if state.state not in TERMINAL and not state.cancel_requested:
                    state = self._reduce(state, EventKind.CANCEL_REQUESTED)
            elif kind == "UNCERTAIN":
                if state.state not in TERMINAL and state.state is not OrderStatus.UNKNOWN:
                    state = self._reduce(state, EventKind.TIMEOUT)
            elif kind != "PENDING":
                raise ValueError("UNSUPPORTED_OBSERVATION")
            self._save(con, execution_id, state)
            con.execute("INSERT INTO applied VALUES (?,?)", (observation.event_id, execution_id))
            con.execute("UPDATE orders SET reconcile_required=1 WHERE execution_id=?", (execution_id,))
            # Remains explicit until reconciliation proves fills vs remaining.
            self._append(con, "OBSERVATION_APPLIED", execution_id,
                         {"event_id": observation.event_id, "state": state.state.value})

    @serialized
    def query(self):
        if self.market == "US":
            self._drain_us_events()
        try:
            batch = self.session.query()
        except Exception as exc:
            failure = "TRANSPORT" if isinstance(exc, (TimeoutError, ConnectionError)) else "REPORT_OR_UNKNOWN"
            if failure == "TRANSPORT" and (self._managed or self._parent is not None and self._parent._managed):
                self.session.disconnected.set()
            self._record_broker_read("UNAVAILABLE", failure_kind=failure)
            with self._transaction() as con:
                con.execute("UPDATE orders SET reconcile_required=1 WHERE submit_stage!='NOT_SENT'")
                self._append(con, "QUERY_UNAVAILABLE", None, {"error_type": type(exc).__name__})
            return {"status": "UNAVAILABLE", "reconcile_required": True, "failure_kind": failure}
        with self._transaction() as con:
            for diagnostic in batch.diagnostics:
                # Retain quarantine evidence in the existing immutable journal;
                # it never enters observations, external orders or the reducer.
                self._append(con, "REPORT_ROW_QUARANTINED", None, asdict(diagnostic))
        for execution_id, returned in self.session.pending_returns().items():
            if self.market == "US":
                self._record_us_origin(execution_id, returned.original_id)
            if returned.order_id:
                with self._journal.connection(readonly=True) as con:
                    command = self._command(con, execution_id)
                self._bind(execution_id, self._key(self.account_id, command.trade_date, returned.order_id))
            if returned.rejected:
                self._rejected_return(execution_id)
        # Process chronology for status; fill identities dedupe across all sources.
        for observation in sorted(batch.observations, key=lambda o: (o.key.trade_date, o.source_time, o.kind == "DEAL")):
            self._ingest(observation)
        self._reconcile_snapshots(batch)
        if self.market == "US":
            self._apply_us_totals(batch.us_order_totals, batch.diagnostics)
        if self.session.cash_inventory_required:
            self._refresh_cash_inventory()
        with self._transaction() as con:
            self._append(con, "QUERY_COMPLETED", None,
                         {"observations": len(batch.observations), "invalid_trade_count": batch.invalid_trade_count,
                          "invalid_report_count": len(batch.diagnostics),
                          "fill_history_complete": batch.fill_history_complete})
        self._evaluate_latest_prices()
        self._wake_strategies()
        self._record_broker_read("PARTIAL" if batch.diagnostics else "AVAILABLE", batch.sources)
        return {"status": "PARTIAL" if batch.diagnostics else "AVAILABLE", "observations": len(batch.observations),
                "invalid_report_count": len(batch.diagnostics),
                "diagnostics": [asdict(d) for d in batch.diagnostics],
                "invalid_trade_count": batch.invalid_trade_count, "fill_history_complete": batch.fill_history_complete}

    def _apply_us_totals(self, totals, diagnostics=()):
        """Join broker aggregates by both durable IDs; no fabricated fill rows."""
        with self._transaction() as con:
            for evidence in totals:
                row = con.execute("SELECT * FROM orders WHERE account_id=? AND broker_id=?", (evidence["account_id"], evidence["broker_order_id"])).fetchall()
                for order in row:
                    eid = order["execution_id"]
                    command = self._command(con, eid)
                    if self._us_origin(con, eid) != evidence["original_order_id"]:
                        continue
                    if (command.symbol, command.action, command.quantity, decimal(command.price), command.settlement_mode) != (evidence["symbol"], evidence["action"], evidence["quantity"], decimal(evidence["price"]), evidence["settlement_mode"]):
                        continue
                    state = state_from(json.loads(order["state"]))
                    total = evidence["cumulative_filled"]
                    if total < state.cumulative_filled:
                        continue
                    reconcile = any(d.fields.get("OrderNo") == evidence["broker_order_id"] and d.account_matches is not False for d in diagnostics)
                    old = con.execute("SELECT payload FROM journal WHERE execution_id=? AND kind='US_ORDER_TOTAL_OBSERVED' ORDER BY seq DESC LIMIT 1", (eid,)).fetchone()
                    if old and json.loads(old[0])["evidence"] == evidence:
                        con.execute("UPDATE orders SET reconcile_required=? WHERE execution_id=?", (int(reconcile), eid))
                        continue
                    self._append(con, "US_ORDER_TOTAL_OBSERVED", eid, {"evidence": evidence, "observed_at": self._now().isoformat()})
                    if state.state is OrderStatus.UNKNOWN:
                        state = self._reduce(state, EventKind.RECONCILE)
                    if total > state.cumulative_filled:
                        state = self._reduce(state, EventKind.FILLED if total == command.quantity else EventKind.PARTIAL_FILL, total=total)
                    elif total == 0 and state.state in {OrderStatus.PENDING, OrderStatus.RECONCILING}:
                        state = self._reduce(state, EventKind.ACCEPTED)
                    if evidence["cancelled"] and state.state not in {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED}:
                        if not state.cancel_requested:
                            state = self._reduce(state, EventKind.CANCEL_REQUESTED)
                        state = self._reduce(state, EventKind.CANCELLED, total=total)
                    self._save(con, eid, state)
                    con.execute("UPDATE orders SET reconcile_required=? WHERE execution_id=?", (int(reconcile), eid))

    def _reconcile_snapshots(self, batch):
        """Corroborate current reports, SDK totals and durable fill identities.

        A missing row, missing fill id, differing totals or conflicting report is
        unresolved. This is evidence reconciliation, not a second order reducer.
        """
        with self._transaction() as con:
            con.execute("UPDATE orders SET reconcile_required=1 WHERE submit_stage!='NOT_SENT'")
            for snapshot in batch.snapshots:
                key = snapshot.key
                row = con.execute("SELECT * FROM orders WHERE account_id=? AND trade_date=? AND broker_id=?",
                                  (key.account_id, key.trade_date, key.order_id)).fetchone()
                if row is None:
                    continue
                execution_id = row["execution_id"]
                command = self._command(con, execution_id)
                state = state_from(json.loads(row["state"]))
                self._append(con, "RECONCILIATION_SNAPSHOT", execution_id, snapshot.payload())
                if any(d.may_affect(key) for d in batch.diagnostics):
                    continue
                reports = [o for o in batch.observations if o.key == key and o.source == "Account.OrderReport"]
                if not reports:
                    continue
                latest_time = max(o.source_time for o in reports)
                latest = [o for o in reports if o.source_time == latest_time]
                if len({(o.kind, o.remaining, o.quantity, o.price) for o in latest}) != 1:
                    continue
                report = latest[0]
                identity = (snapshot.symbol, snapshot.action, snapshot.condition, snapshot.lot)
                if identity != (command.symbol, command.action, command.condition, command.lot):
                    continue
                if snapshot.quantity * command.shares_per_unit != command.quantity or decimal(snapshot.price) != decimal(command.price):
                    continue
                total = con.execute("SELECT coalesce(sum(quantity),0) FROM fills WHERE execution_id=?", (execution_id,)).fetchone()[0]
                unapplied = con.execute("SELECT 1 FROM observations WHERE broker_key=? AND event_id NOT IN (SELECT event_id FROM applied) LIMIT 1", (key.identity,)).fetchone()
                if unapplied or total != snapshot.cumulative * command.shares_per_unit or total != state.cumulative_filled:
                    continue
                remaining = snapshot.remaining * command.shares_per_unit
                status = snapshot.broker_status
                kind = None
                if status == "Filled" and total == command.quantity and remaining == 0:
                    kind = EventKind.FILLED
                elif status in {"Cancelled", "PartFilled_Cancelled"} and remaining == 0 and report.kind == "CANCELLED" and latest_time == snapshot.source_time:
                    kind = EventKind.CANCELLED
                elif status in {"Submitted", "PartFilled"} and report.kind == "ACCEPTED" and remaining + total == command.quantity:
                    kind = EventKind.PARTIAL_FILL if total else EventKind.ACCEPTED
                if kind is None:
                    continue
                if state.state is OrderStatus.UNKNOWN:
                    state = self._reduce(state, EventKind.RECONCILE)
                    if kind is EventKind.CANCELLED and not state.cancel_requested:
                        state = self._reduce(state, EventKind.CANCEL_REQUESTED)
                    state = self._reduce(state, kind, total=total)
                    self._save(con, execution_id, state)
                # A stale snapshot must not resolve an outstanding cancel/fill race.
                expected = {EventKind.FILLED: {OrderStatus.FILLED},
                            EventKind.CANCELLED: {OrderStatus.CANCELLED, OrderStatus.FILLED},
                            EventKind.PARTIAL_FILL: {OrderStatus.PARTIALLY_FILLED},
                            EventKind.ACCEPTED: {OrderStatus.ACCEPTED}}[kind]
                if state.state in expected:
                    con.execute("UPDATE orders SET reconcile_required=0 WHERE execution_id=?", (execution_id,))
                    self._append(con, "CORROBORATED_SNAPSHOT", execution_id,
                                 {"source_time": snapshot.source_time, "fill_history_complete": False,
                                  "filled_shares": total, "broker_order_id": key.order_id})

    @serialized
    def reconcile(self):
        # Explicit broker read. Constructor/status never acquires broker evidence.
        result = self.query()
        if self.us_runtime is not None:
            self.us_runtime.reconcile()
        with self._transaction() as con:
            self._append(con, "RECONCILIATION", None, result)
        return result

    @serialized
    def reconnect(self):
        require(self._parent is None, "SHARED_CONTEXT_LIFECYCLE_OWNED")
        with self._mutex:
            self._prices.clear()
            self._cash_inventory = None
        self.session.reconnect(trade_date=self.session.current_day())
        self.trade_date = self.session.trade_date
        with self._transaction() as con:
            con.execute("UPDATE orders SET reconcile_required=1 WHERE submit_stage!='NOT_SENT'")
            self._append(con, "RECONNECT", None, {"resend": False})
        return self.reconcile()

    @serialized
    def cancel(self, execution_id, key: BrokerKey):
        key.validate()
        require(key == self._key(key.account_id, key.trade_date, key.order_id), "BROKER_MARKET_SCOPE_CONFLICT")
        with self._transaction() as con:
            row = self._row(con, execution_id)
            require((row["account_id"], row["trade_date"], row["broker_id"]) ==
                    (key.account_id, key.trade_date, key.order_id), "EXACT_CANCEL_IDENTITY_REQUIRED")
            require(key.account_id == self.account_id and (self.market == "US" or key.trade_date == self.trade_date),
                    "CANCEL_SESSION_MISMATCH")
            state = state_from(json.loads(row["state"]))
            command = self._command(con, execution_id)
            original_id = self._us_origin(con, execution_id) if self.market == "US" else None
            require(self.market != "US" or original_id is not None, "US_ORIGIN_ID_UNAVAILABLE")
            dispatch = row["cancel_stage"] is None and state.state not in TERMINAL
            if dispatch:
                state = self._reduce(state, EventKind.CANCEL_REQUESTED)
                self._save(con, execution_id, state)
                con.execute("UPDATE orders SET cancel_stage='CLAIMED',reconcile_required=1 WHERE execution_id=?", (execution_id,))
                self._append(con, "CANCEL_CLAIMED", execution_id, asdict(key))
        if dispatch:
            self._fault("after_cancel_claim")
            try:
                if self.market == "US":
                    self.session.cancel(key, command, original_id=original_id)
                else:
                    self.session.cancel(key, command)  # no confirmation, no account-wide query, exact ID only
            except Exception:
                self._uncertain(execution_id, "CANCEL_UNKNOWN")
            else:
                self._fault("after_cancel_effect")
                with self._transaction() as con:
                    con.execute("UPDATE orders SET cancel_stage='ACK_ONLY' WHERE execution_id=?", (execution_id,))
                    self._append(con, "CANCEL_ACK_ONLY", execution_id, asdict(key))
        return self.status(execution_id)

    def external_orders(self):
        with self._journal.connection(readonly=True) as con:
            # Rows first observed before an internal bind stay in the immutable
            # journal, but are no longer presented as unowned external orders.
            return [{"identity": row["identity"], "space_id": "USER_SPACE", "ownership": "EXTERNAL",
                     **json.loads(row["payload"])} for row in con.execute("SELECT * FROM external_orders")
                    if not con.execute("SELECT 1 FROM orders WHERE account_id=? AND trade_date=? AND broker_id=?",
                        tuple(json.loads(row["payload"])[k] for k in ("account_id", "trade_date", "order_id"))).fetchone()]

    def verify(self):
        """Read-only journal replay through the SAME reducer before session start."""
        with self._journal.connection(readonly=True) as con:
            con.execute("BEGIN")
            self._verify_reviews(con)
            self._verify_strategies(con)
            reviews = {r.draft.command.execution_id: r for r in self._reviews(con).values()}
            for row in con.execute("SELECT execution_id,payload FROM journal WHERE kind='CANDIDATE_REVIEW_BOUND'"):
                require(row["execution_id"] in reviews, "CANDIDATE_REVIEW_MISSING")
                validate_binding(self._candidate_binding(con, row["execution_id"]), reviews[row["execution_id"]].draft)
            intent_ids = {r[0] for r in con.execute("SELECT execution_id FROM intents")}
            order_ids = {r[0] for r in con.execute("SELECT execution_id FROM orders")}
            claim_ids = {r[0] for r in con.execute("SELECT execution_id FROM journal WHERE kind='SUBMIT_CLAIMED'")}
            require(intent_ids == order_ids == claim_ids, "JOURNAL_ORDER_SET_MISMATCH")
            for row in con.execute("SELECT * FROM orders"):
                execution_id = row["execution_id"]
                records = con.execute("SELECT kind,payload FROM journal WHERE execution_id=? ORDER BY seq", (execution_id,)).fetchall()
                claims = [json.loads(r["payload"]) for r in records if r["kind"] == "SUBMIT_CLAIMED"]
                require(len(claims) == 1, "JOURNAL_CLAIM_MISMATCH")
                command = self._command(con, execution_id)
                require(type(command) is (UsCommand if self.market == "US" else Command), "JOURNAL_MARKET_MISMATCH")
                require(self.market != "US" or command.environment == self.environment, "JOURNAL_ENVIRONMENT_MISMATCH")
                if self.market == "US":
                    self._us_origin(con, execution_id)
                require(claims[0]["command"] == command_payload(command), "JOURNAL_INTENT_MISMATCH")
                state = state_from(claims[0]["initial_state"])
                require(state == OrderProgress(execution_id, command.quantity, OrderStatus.PENDING, state.admitted_at), "JOURNAL_INITIAL_STATE_MISMATCH")
                broker_id = None
                submit_stage, cancel_stage = "CLAIMED", None
                for record in records:
                    payload = json.loads(record["payload"])
                    if record["kind"] == "ORDER_REDUCED":
                        for event in state_from({**json.loads(state_payload(state)), "events": payload["events"]}).events:
                            state = reduce_order(state, event, event.occurred_at)[0]
                    elif record["kind"] == "BROKER_BOUND":
                        require(submit_stage != "NOT_SENT", "NOT_SENT_PROOF_CONFLICT")
                        require(broker_id in {None, payload["order_id"]}, "JOURNAL_BROKER_CONFLICT")
                        require((payload["account_id"], payload["trade_date"]) == (command.account_id, command.trade_date), "JOURNAL_BROKER_SCOPE_CONFLICT")
                        broker_id = payload["order_id"]
                    elif record["kind"] == "SUBMIT_RETURNED":
                        require(submit_stage != "NOT_SENT", "NOT_SENT_PROOF_CONFLICT")
                        submit_stage = "RETURNED"
                    elif record["kind"] == "SUBMIT_NOT_SENT":
                        require(submit_stage == "CLAIMED" and broker_id is None and cancel_stage is None
                                and payload.get("sdk_attempted") is False
                                and payload.get("reason") in {"PRE_EFFECT_CHECK_FAILED", "CASH_EXIT_CAPACITY_CHANGED_NOT_SENT"}
                                and state.state is OrderStatus.REJECTED and state.cumulative_filled == 0,
                                "NOT_SENT_PROOF_CONFLICT")
                        submit_stage = "NOT_SENT"
                    elif record["kind"] == "CANCEL_CLAIMED":
                        cancel_stage = "CLAIMED"
                    elif record["kind"] == "CANCEL_ACK_ONLY":
                        cancel_stage = "ACK_ONLY"
                require(state_payload(state) == row["state"], "JOURNAL_PROJECTION_MISMATCH")
                require((broker_id, submit_stage, cancel_stage) == (row["broker_id"], row["submit_stage"], row["cancel_stage"]), "JOURNAL_COMMAND_MISMATCH")
                fills = con.execute("SELECT * FROM fills WHERE execution_id=?", (execution_id,)).fetchall()
                if self.market == "US":
                    aggregates = [json.loads(r["payload"])["evidence"] for r in records if r["kind"] == "US_ORDER_TOTAL_OBSERVED"]
                    require(not fills and max((a["cumulative_filled"] for a in aggregates), default=0) == state.cumulative_filled, "JOURNAL_FILL_MISMATCH")
                    require(all(a["account_id"] == command.account_id and a["broker_order_id"] == broker_id and a["original_order_id"] == self._us_origin(con, execution_id) and a["symbol"] == command.symbol and a["action"] == command.action and a["quantity"] == command.quantity and decimal(a["price"]) == decimal(command.price) and a["settlement_mode"] == command.settlement_mode for a in aggregates), "JOURNAL_FILL_EVIDENCE_MISMATCH")
                else:
                    require(sum(f["quantity"] for f in fills) == state.cumulative_filled, "JOURNAL_FILL_MISMATCH")
                for fill in fills:
                    observations = [observation_from(json.loads(o[0])) for o in con.execute(
                        "SELECT payload FROM observations WHERE broker_key=?", (fill["broker_key"],))]
                    require(any(o.kind == "DEAL" and o.seqno == fill["fill_id"]
                        and o.quantity * command.shares_per_unit == fill["quantity"]
                        and decimal(o.price) == decimal(fill["price"]) and o.source_time == fill["source_time"]
                        for o in observations), "JOURNAL_FILL_EVIDENCE_MISMATCH")
        return True
