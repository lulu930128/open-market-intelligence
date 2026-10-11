"""Sole M2A command/transaction owner; imports the pure M1 rules."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Context, Decimal, localcontext
import hmac
import secrets

from execution.contracts import (
    AccountFacts, Challenge, Confirmation, CreditFacts, Draft, Evidence, EventKind, ExecutionRejected, OrderState, Preview,
    Side, SimulationEvent, State,
)
from execution.state_machine import transition
from execution.validation import assess, digest_of, identifier, instant, integer, money, require, validate_fill

from .codec import dumps, loads
from .mock import Fixture, SimulatedCrash, receipt
from .storage import connection
from . import fake_sdk
from . import settlement as ledger
from .settlement_contracts import FillLot, RestrictionEvidence


@dataclass(frozen=True)
class Envelope:
    value: object
    simulated: bool = field(default=True, init=False)
    broker_connected: bool = field(default=False, init=False)
    test_only: bool = field(default=True, init=False)
    origin: str = field(default="SYNTHETIC", init=False)


class SimulationApplication:
    """A factory-issued synthetic sandbox is mandatory; retention is storage-owned.

    Time and manual actions are explicit test inputs, not authentication or 2FA.
    Reservations remain immutable; schema v2 adds explicit settlement/release overlays.
    """

    def __init__(self, sandbox):
        self._sandbox = sandbox
        self.verify()

    @staticmethod
    def manual_request_id(principal, account, client_request_id):
        """Stable LOCAL_MOCK idempotency namespace, independent of auth restart.

        These identities must come from the server auth boundary. This digest is
        not an access token; preview/status still require independent auth.
        """
        for value in (principal, account, client_request_id):
            identifier(value)
        require(principal.startswith('synthetic-') and account.startswith('synthetic-'),
                'FIXTURE_IDENTITY_ONLY')
        return digest_of(('manual-local-mock-v1', principal, account, client_request_id))

    @staticmethod
    def _audit(db, now, operation, preview_id, value):
        previous = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous_hash = previous[0] if previous else "0" * 64
        payload = dumps({"value": value, "simulated": True, "broker_connected": False,
                         "test_only": True, "origin": "SYNTHETIC"})
        stamp = now.isoformat()
        digest = digest_of((stamp, operation, preview_id, payload, previous_hash))
        db.execute("INSERT INTO audit(occurred_at,operation,preview_id,payload,previous_hash,hash) "
                   "VALUES(?,?,?,?,?,?)", (stamp, operation, preview_id, payload, previous_hash, digest))

    @contextmanager
    def _command(self, now, operation, preview_id=None):
        instant(now)
        error = None
        with connection(self._sandbox) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._quota(db)
                self._verify(db)
                row = db.execute("SELECT value FROM metadata WHERE key='last_now'").fetchone()
                require(row is None or now >= loads(row[0]), "CLOCK_REGRESSION")
                db.execute("SAVEPOINT command")
                try:
                    yield db
                except ExecutionRejected as exc:
                    db.execute("ROLLBACK TO command")
                    if exc.code == 'LATE_FILL_AFTER_SETTLEMENT' or (
                            operation in {'SETTLE', 'ACCRUE'} and exc.code == 'RESERVATION_INTEGRITY'):
                        p = self._preview(db, preview_id)
                        projection = self._projection(db)
                        evidence = RestrictionEvidence('blocked-' + secrets.token_hex(16), p.draft.account_id,
                            'CONTRADICTORY_FINALITY' if exc.code == 'LATE_FILL_AFTER_SETTLEMENT'
                            else 'SETTLEMENT_INSOLVENT', now)
                        projection['restrictions'][p.draft.account_id] = evidence
                        self._ledger_write(db, evidence.event_id, 'RESTRICTION', preview_id, evidence, projection, now)
                    self._audit(db, now, operation + "_REJECTED", preview_id, {"code": exc.code})
                    error = exc
                db.execute("RELEASE command")
                if error is None:
                    self._audit(db, now, "COMMAND", preview_id, {"operation": operation})
                self._quota(db, reserve=0)
                db.execute("INSERT INTO metadata VALUES('last_now',?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (dumps(now),))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if error:
            raise error

    @staticmethod
    def _quota(db, reserve=12):
        # Reserve room for a whole command including failure evidence. At quota,
        # reject outside the savepoint without appending another rejected row.
        count, size = db.execute('SELECT count(*),coalesce(sum(length(payload)),0) FROM audit').fetchone()
        require(count + reserve <= ledger.MAX_AUDIT_ROWS and size <= ledger.MAX_AUDIT_BYTES,
                'SYNTHETIC_JOURNAL_QUOTA')
        require(db.execute('SELECT count(*) FROM previews').fetchone()[0] <= ledger.MAX_ORDERS,
                'SYNTHETIC_ORDER_QUOTA')

    @staticmethod
    def _projection(db):
        if db.execute('PRAGMA user_version').fetchone()[0] == 1:
            return ledger.empty_projection()
        return loads(db.execute('SELECT payload FROM settlement_projection WHERE id=1').fetchone()[0])

    @staticmethod
    def _v2(db):
        require(db.execute('PRAGMA user_version').fetchone()[0] == 2, 'SETTLEMENT_SCHEMA_REQUIRED')

    def _ledger_write(self, db, event_id, operation, key, value, projection, now):
        require(db.execute('SELECT 1 FROM settlement_events WHERE id=?', (event_id,)).fetchone() is None,
                'EVENT_ID_CONFLICT')
        db.execute('INSERT INTO settlement_events VALUES(?,?,?,?)', (event_id, operation, key, dumps(value)))
        db.execute('UPDATE settlement_projection SET payload=? WHERE id=1', (dumps(projection),))
        self._audit(db, now, operation, key, value)

    @staticmethod
    def _preview(db, preview_id):
        identifier(preview_id)
        row = db.execute("SELECT payload FROM previews WHERE id=?", (preview_id,)).fetchone()
        require(row is not None, "UNKNOWN_PREVIEW")
        return loads(row[0])

    @staticmethod
    def _order(db, preview_id):
        row = db.execute("SELECT payload FROM orders WHERE id=?", (preview_id,)).fetchone()
        require(row is not None, "CONFIRMATION_REQUIRED")
        return loads(row[0])

    def preview(self, draft, evidence, *, now, mock_broker=False):
        with self._command(now, "PREVIEW") as db:
            assessment = assess(draft, self._settled_evidence(draft, evidence, self._projection(db)), now)
            if mock_broker:
                require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
                fake_sdk.convert(draft, fake_sdk.FakeUnits(draft.lot,
                    1000 if draft.lot.value == 'BOARD' else 1))
            require(draft.account_id.startswith("synthetic-")
                    and evidence.permission.principal_id.startswith("synthetic-"), "FIXTURE_IDENTITY_ONLY")
            row = db.execute("SELECT payload FROM previews WHERE account_id=? AND request_id=?",
                             (draft.account_id, draft.client_request_id)).fetchone()
            if row:
                preview = loads(row[0])
                consumed = db.execute('SELECT payload FROM orders WHERE id=?', (preview.preview_id,)).fetchone()
                require(consumed is None or loads(consumed[0]).confirmed_at is not None,
                        'CHALLENGE_CONSUMED')
                require(digest_of(preview.draft) == digest_of(draft), "IDEMPOTENCY_CONFLICT")
                require(digest_of(preview.evidence) == digest_of(evidence), "EVIDENCE_CONFLICT")
                require(now < preview.challenge.expires_at, "PREVIEW_EXPIRED")
            else:
                require(db.execute('SELECT count(*) FROM previews').fetchone()[0] < ledger.MAX_ORDERS,
                        'SYNTHETIC_ORDER_QUOTA')
                assessment = replace(assessment, valid_until=min(assessment.valid_until, now + timedelta(seconds=60)))
                preview_id = "simulation-" + digest_of((draft.account_id, draft.client_request_id))
                digest = digest_of((preview_id, draft, evidence, assessment, now))
                challenge = Challenge(secrets.token_hex(32), digest, evidence.permission.principal_id,
                                      assessment.valid_until)
                preview = Preview(preview_id, draft, evidence, assessment, now, challenge)
                db.execute("INSERT INTO previews VALUES(?,?,?,?,?,?)", (
                    preview_id, draft.account_id, draft.client_request_id, digest_of(draft),
                    digest_of(evidence), dumps(preview)))
                self._audit(db, now, "PREVIEW", preview_id, preview)
                if mock_broker:
                    self._audit(db, now, 'FAKE_PREVIEW', preview_id, {'digest': digest})
        return Envelope(preview)

    @staticmethod
    def _remaining_resources(preview, prior, projection=None):
        """Project baselines, verified deltas and active holds; M1 owns admission.

        Schema v1 has an empty settlement projection and retains every hold.
        Schema v2 release overlays never rewrite the historic preview or hold.
        """
        evidence = preview.evidence
        account, permission = evidence.account, evidence.permission
        credit = account.credit
        same_account = [p for p in prior if p.draft.account_id == preview.draft.account_id]
        prior_v2 = [p for p in same_account if p.assessment.resources is not None]
        projection = projection if projection is not None else ledger.empty_projection()
        require(account.account_id not in projection['restrictions'], 'ACCOUNT_RESTRICTED')
        change = ledger.deltas(projection, preview.draft)
        # A legacy command cannot evade an established expanded account risk envelope.
        require(not prior_v2 or preview.assessment.resources is not None, 'RESOURCE_CONTRACT_DOWNGRADE')
        if preview.assessment.resources is None:
            return evidence
        for old in prior_v2:
            op = old.evidence.permission
            require((permission.ref, permission.principal_id, permission.maximum_intraday_risk,
                     permission.used_intraday_risk) ==
                    (op.ref, op.principal_id, op.maximum_intraday_risk, op.used_intraday_risk),
                    'RISK_BASELINE_CHANGED')
            oc = old.evidence.account.credit
            if oc is not None:
                require(credit is not None, 'CREDIT_BASELINE_CHANGED')
                require((credit.ref, credit.version, credit.currency, credit.available_credit,
                         credit.available_collateral) ==
                        (oc.ref, oc.version, oc.currency, oc.available_credit, oc.available_collateral),
                        'CREDIT_BASELINE_CHANGED')
                if old.draft.instrument == preview.draft.instrument:
                    require(credit == oc, 'CREDIT_BASELINE_CHANGED')
        with localcontext(Context(prec=64)):
            risk = sum((p.assessment.notional for p in same_account), Decimal(0))
            permission = replace(permission, used_intraday_risk=permission.used_intraday_risk + risk)
            if credit is not None:
                values = {}
                for field, resource in (('available_credit', 'credit'), ('available_collateral', 'collateral'),
                                        ('short_borrow_available', 'short_borrow'),
                                        ('lend_borrow_available', 'lend_borrow'),
                                        ('margin_position', 'margin_position'),
                                        ('short_position', 'short_position'), ('lend_position', 'lend_position')):
                    rows = prior_v2 if field in {'available_credit', 'available_collateral'} else [
                        p for p in prior_v2 if p.draft.instrument == preview.draft.instrument]
                    rows = [p for p in rows if p.preview_id not in projection['settlements']]
                    delta_key = {'available_credit': 'credit', 'available_collateral': 'collateral'}.get(field, field)
                    values[field] = getattr(credit, field) + change[delta_key] - sum(
                        (getattr(p.assessment.resources, resource) for p in rows), 0)
                    if type(values[field]) is Decimal:
                        values[field] = values[field].normalize()
                    require(values[field] >= 0, 'RESERVATION_INTEGRITY')
                credit = replace(credit, **values)
        return replace(evidence, account=replace(account, credit=credit), permission=permission)

    @staticmethod
    def _settled_evidence(draft, evidence, projection):
        # Keep immutable supplied baselines in Preview. Only the M1 assess input
        # incorporates verified deltas; replay reconstructs the identical view.
        require(type(draft) is Draft, 'INVALID_DRAFT')
        require(type(evidence) is Evidence, 'INVALID_EVIDENCE')
        if not projection['settlements']:
            return evidence
        with localcontext(Context(prec=64)):
            delta = ledger.deltas(projection, draft)
            account = evidence.account
            require(type(account) is AccountFacts, 'INVALID_ACCOUNT')
            money(account.available_cash)
            integer(account.sellable_quantity)
            credit = account.credit
            if credit is not None:
                require(type(credit) is CreditFacts, 'CREDIT_UNVERIFIED')
                values = {}
                for field in ('available_credit', 'available_collateral', 'short_borrow_available',
                              'lend_borrow_available', 'margin_position', 'short_position', 'lend_position'):
                    name = {'available_credit': 'credit', 'available_collateral': 'collateral'}.get(field, field)
                    (money if field in {'available_credit', 'available_collateral'} else integer)(getattr(credit, field))
                    value = getattr(credit, field) + delta[name]
                    values[field] = value.normalize() if type(value) is Decimal else value
                credit = replace(credit, **values)
            return replace(evidence, account=replace(account, credit=credit,
                available_cash=(account.available_cash + delta['cash']).normalize(),
                sellable_quantity=account.sellable_quantity + delta['sellable']))

    @staticmethod
    def _admission(preview, prior, projection):
        remaining = SimulationApplication._remaining_resources(preview, prior, projection)
        a = preview.evidence.account
        active = [p for p in prior if p.draft.account_id == a.account_id
                  and p.preview_id not in projection['settlements']]
        with localcontext(Context(prec=64)):
            delta = ledger.deltas(projection, preview.draft)
            cash = (a.available_cash + delta['cash'] - sum((p.assessment.required_cash for p in active), Decimal(0))).normalize()
        sellable = a.sellable_quantity + delta['sellable'] - sum(
            SimulationApplication._reservation(p, p.assessment)['quantity'] for p in active
            if p.draft.instrument == preview.draft.instrument)
        require(cash >= 0 and sellable >= 0, 'RESERVATION_INTEGRITY')
        return replace(remaining, account=replace(remaining.account, available_cash=cash, sellable_quantity=sellable))

    @staticmethod
    def _reservation(preview, assessment):
        return {"cash": assessment.required_cash,
                "quantity": (assessment.resources.sellable if assessment.resources is not None else
                             preview.draft.quantity if preview.draft.side is Side.SELL else 0),
                "instrument": digest_of(preview.draft.instrument), "account_id": preview.draft.account_id}

    @staticmethod
    def _reserve(db, preview, now):
        draft, evidence = preview.draft, preview.evidence
        account = evidence.account
        assessment = assess(draft, SimulationApplication._settled_evidence(
            draft, evidence, SimulationApplication._projection(db)), now)
        cash_binding = digest_of((account.ref, account.currency, account.available_cash))
        position_binding = digest_of((account.ref, account.instrument, account.sellable_quantity))
        instrument = digest_of(draft.instrument)
        budget = db.execute("SELECT binding FROM budgets WHERE account_id=?", (draft.account_id,)).fetchone()
        require(budget is None or budget[0] == cash_binding, "BUDGET_BASELINE_CHANGED")
        position = db.execute("SELECT binding FROM positions WHERE account_id=? AND instrument=?",
                              (draft.account_id, instrument)).fetchone()
        require(position is None or position[0] == position_binding, "POSITION_BASELINE_CHANGED")
        prior = [loads(r[0]) for r in db.execute(
            'SELECT p.payload FROM previews p JOIN confirmations c ON p.id=c.id')]
        remaining = SimulationApplication._admission(preview, prior, SimulationApplication._projection(db))
        assess(draft, remaining, now)
        if budget is None:
            db.execute("INSERT INTO budgets VALUES(?,?,?)", (draft.account_id, cash_binding, str(account.available_cash)))
        if position is None:
            db.execute("INSERT INTO positions VALUES(?,?,?,?)", (
                draft.account_id, instrument, position_binding, account.sellable_quantity))
        reservation = SimulationApplication._reservation(preview, assessment)
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?)", (
            preview.preview_id, draft.account_id, instrument, str(reservation['cash']), reservation['quantity']))
        return reservation

    def confirm(self, confirmation, *, now, crash_at=None):
        require(type(confirmation) is Confirmation, "INVALID_CONFIRMATION")
        with self._command(now, "CONFIRM", confirmation.preview_id) as db:
            preview = self._preview(db, confirmation.preview_id)
            c = preview.challenge
            require(confirmation.user_confirmed is True, "EXPLICIT_CONFIRMATION_REQUIRED")
            require(type(confirmation.token) is str and confirmation.token.isascii()
                    and hmac.compare_digest(c.token, confirmation.token), "CHALLENGE_MISMATCH")
            require(confirmation.digest == c.digest, "PAYLOAD_DIGEST_MISMATCH")
            require(confirmation.principal_id == c.principal_id, "PRINCIPAL_MISMATCH")
            require(digest_of((preview.preview_id, preview.draft, preview.evidence, preview.assessment,
                               preview.created_at)) == c.digest, "PREVIEW_TAMPERED")
            prior = db.execute("SELECT payload FROM confirmations WHERE id=?", (preview.preview_id,)).fetchone()
            if prior:
                require(loads(prior[0]) == confirmation, "CHALLENGE_CONSUMED")
                self._audit(db, now, "CONFIRM_REPLAY", preview.preview_id, {"reason": "IDEMPOTENT_RECEIPT"})
            else:
                if db.execute("SELECT 1 FROM audit WHERE operation='FAKE_PREVIEW' AND preview_id=?",
                              (preview.preview_id,)).fetchone():
                    require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
                require(db.execute('SELECT 1 FROM orders WHERE id=?', (preview.preview_id,)).fetchone() is None,
                        'CHALLENGE_CONSUMED')
                require(now < c.expires_at, "PREVIEW_EXPIRED")
                reserved = self._reserve(db, preview, now)
                db.execute("INSERT INTO confirmations VALUES(?,?)", (preview.preview_id, dumps(confirmation)))
                order = OrderState(preview.preview_id, preview.draft.quantity, State.SIMULATED_PENDING, now)
                db.execute("INSERT INTO orders VALUES(?,?)", (preview.preview_id, dumps(order)))
                self._crash(crash_at, "before_outbox")
                self._enqueue(db, preview.preview_id, "SEND", now)
                self._audit(db, now, "CONFIRM", preview.preview_id, {"order": order, "reservation": reserved})
                self._crash(crash_at, "before_commit")
        self._crash(crash_at, "after_commit")
        return self.status(confirmation.preview_id)

    @staticmethod
    def _crash(actual, boundary):
        if actual == boundary:
            raise SimulatedCrash(boundary)

    def _enqueue(self, db, preview_id, kind, now):
        command_id = digest_of((preview_id, kind))
        db.execute("INSERT INTO outbox VALUES(?,?,?)", (command_id, preview_id, kind))
        self._stage(db, command_id, "READY", now)
        self._audit(db, now, "OUTBOX", preview_id, {"command_id": command_id, "kind": kind})

    def _stage(self, db, command_id, stage, now):
        db.execute("INSERT INTO outbox_events(command_id,stage,occurred_at) VALUES(?,?,?)",
                   (command_id, stage, now.isoformat()))
        self._audit(db, now, "OUTBOX_STAGE", None, {"command_id": command_id, "stage": stage})

    @staticmethod
    def _latest(db, command_id):
        return db.execute("SELECT stage FROM outbox_events WHERE command_id=? ORDER BY seq DESC LIMIT 1",
                          (command_id,)).fetchone()[0]

    def _event(self, db, event, now):
        preview = self._preview(db, event.preview_id)
        row = db.execute('SELECT payload FROM orders WHERE id=?', (event.preview_id,)).fetchone()
        order = loads(row[0]) if row else OrderState(event.preview_id, preview.draft.quantity, State.PREVIEWED, None)
        if event.preview_id in self._projection(db)['settlements']:
            require(event in order.events, 'LATE_FILL_AFTER_SETTLEMENT')
        require(event.occurred_at >= preview.created_at, 'INVALID_EVENT_TIME')
        validate_fill(preview.draft, preview.evidence, event)
        updated, reason = transition(order, event, now)
        db.execute("INSERT INTO orders VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                   (event.preview_id, dumps(updated)))
        self._audit(db, now, "EVENT", event.preview_id, {"event": event, "reason": reason})

    def callback(self, event, *, now):
        require(type(event) is SimulationEvent, "INVALID_EVENT")
        with self._command(now, "CALLBACK", event.preview_id) as db:
            # A fixture report is possible only once a mock effect was durably recorded.
            effect = db.execute("SELECT 1 FROM mock_effects m JOIN outbox o ON o.id=m.command_id "
                                "WHERE o.preview_id=? AND o.kind='SEND'", (event.preview_id,)).fetchone()
            require(effect is not None, "MOCK_SEND_REQUIRED")
            require(event.kind not in {EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED},
                    "USE_EXPLICIT_COMMAND")
            self._event(db, event, now)
        return self.status(event.preview_id)

    def simulate_fill(self, preview_id, *, cumulative_filled, now):
        """Explicit deterministic fixture fill, never a promise of price or instant execution."""
        integer(cumulative_filled, positive=True)
        with self._command(now, 'SIMULATE_FILL', preview_id) as db:
            p = self._preview(db, preview_id)
            order = self._order(db, preview_id)
            require(p.assessment.resources is not None, 'EXPANDED_CONTRACT_REQUIRED')
            require(db.execute("SELECT 1 FROM mock_effects m JOIN outbox o ON o.id=m.command_id "
                               "WHERE o.preview_id=? AND o.kind='SEND'", (preview_id,)).fetchone() is not None,
                    'MOCK_SEND_REQUIRED')
            resources = p.assessment.resources
            price = resources.price_ceiling if p.draft.side is Side.BUY else resources.price_floor
            event_id = 'fill-' + digest_of((preview_id, cumulative_filled))
            event = next((old for old in order.events if old.event_id == event_id), None)
            if event is None:
                event = SimulationEvent(event_id, preview_id,
                                        EventKind.FILLED if cumulative_filled == order.quantity else EventKind.PARTIAL_FILL,
                                        now, order.last_report_sequence + 1, cumulative_filled, price)
            self._event(db, event, now)
        return self.status(preview_id)

    def record_fill(self, lot, *, now, crash_at=None):
        """Record one explicit delta lot and its M1 report in the same transaction."""
        require(type(lot) is FillLot, 'INVALID_FILL_LOT')
        identifier(lot.event_id)
        with self._command(now, 'RECORD_FILL', lot.preview_id) as db:
            self._v2(db)
            p, before = self._preview(db, lot.preview_id), self._order(db, lot.preview_id)
            projection = self._projection(db)
            prior = projection['lots'].get(lot.event_id)
            if prior is not None:
                if prior != lot and prior.preview_id == lot.preview_id and prior.preview_id in projection['settlements']:
                    require(False, 'LATE_FILL_AFTER_SETTLEMENT')
                require(prior == lot, 'EVENT_ID_CONFLICT')
            else:
                require(lot.preview_id not in projection['settlements'], 'LATE_FILL_AFTER_SETTLEMENT')
                require(db.execute("SELECT 1 FROM mock_effects m JOIN outbox o ON o.id=m.command_id "
                                   "WHERE o.preview_id=? AND o.kind='SEND'", (lot.preview_id,)).fetchone() is not None,
                        'MOCK_SEND_REQUIRED')
                integer(lot.shares, positive=True)
                cumulative = before.cumulative_filled + lot.shares
                event = SimulationEvent('lot-' + digest_of(lot.event_id), lot.preview_id,
                    EventKind.FILLED if cumulative == before.quantity else EventKind.PARTIAL_FILL,
                    lot.occurred_at, before.last_report_sequence + 1, cumulative, lot.executed_price)
                self._event(db, event, now)
                ledger.add_lot(projection, lot, p, before, self._order(db, lot.preview_id), now)
                self._ledger_write(db, lot.event_id, 'FILL_LOT', lot.preview_id,
                                   dict(lot=lot, event=event, before=before), projection, now)
                self._crash(crash_at, 'before_commit')
        self._crash(crash_at, 'after_commit')
        return self.snapshot(lot.preview_id)

    @staticmethod
    def _solvent(previews, projection, account_id):
        for b in projection['balances'].values():
            require(all(b[name] >= 0 for name in ('restricted_proceeds', 'financing_principal', 'borrowed_shares')),
                    'RESERVATION_INTEGRITY')
        for loan in projection['loans'].values():
            require(all(loan[name] >= 0 for name in ('shares', 'principal', 'collateral', 'proceeds', 'borrow_basis')),
                    'RESERVATION_INTEGRITY')
        for p in previews:
            if p.draft.account_id == account_id:
                SimulationApplication._admission(p, previews, projection)

    def settle(self, preview_id, receipt, *, fees, interest, now, crash_at=None):
        from .settlement_contracts import SettlementReceipt
        ledger.unverified(type(receipt) is SettlementReceipt, 'FINALITY_UNVERIFIED')
        with self._command(now, 'SETTLE', preview_id) as db:
            self._v2(db)
            p, order = self._preview(db, preview_id), self._order(db, preview_id)
            projection = self._projection(db)
            old = projection['settlements'].get(preview_id)
            if old is not None:
                require((old['receipt'], old['fees'], old['interest']) == (receipt, fees, interest),
                        'SETTLEMENT_CONFLICT')
            else:
                value = dict(receipt=receipt, fees=fees, interest=interest)
                ledger.settle_projection(projection, p, order, receipt, fees, interest, now)
                previews = [loads(r[0]) for r in db.execute(
                    'SELECT p.payload FROM previews p JOIN confirmations c ON p.id=c.id')]
                self._solvent(previews, projection, p.draft.account_id)
                db.execute('INSERT INTO releases VALUES(?,?)', (preview_id, receipt.event_id))
                self._ledger_write(db, receipt.event_id, 'SETTLEMENT', preview_id, value, projection, now)
                self._crash(crash_at, 'before_commit')
        self._crash(crash_at, 'after_commit')
        return self.snapshot(preview_id)

    def accrue(self, tick, *, now, crash_at=None):
        from .settlement_contracts import AccrualTick
        require(type(tick) is AccrualTick, 'INVALID_ACCRUAL')
        with self._command(now, 'ACCRUE', tick.opening_preview_id) as db:
            self._v2(db)
            p = self._preview(db, tick.opening_preview_id)
            projection = self._projection(db)
            old = projection['accruals'].get(tick.event_id)
            if old is not None:
                require(old['tick'] == tick, 'EVENT_ID_CONFLICT')
            else:
                ledger.accrue_projection(projection, tick, p, now)
                previews = [loads(r[0]) for r in db.execute(
                    'SELECT p.payload FROM previews p JOIN confirmations c ON p.id=c.id')]
                self._solvent(previews, projection, p.draft.account_id)
                self._ledger_write(db, tick.event_id, 'ACCRUAL', p.preview_id, tick, projection, now)
                self._crash(crash_at, 'before_commit')
        self._crash(crash_at, 'after_commit')
        return self.snapshot(tick.opening_preview_id)

    def restrict(self, preview_id, evidence, *, now):
        require(type(evidence) is RestrictionEvidence, 'INVALID_RESTRICTION')
        identifier(evidence.event_id)
        instant(evidence.occurred_at)
        with self._command(now, 'RESTRICT', preview_id) as db:
            self._v2(db)
            p = self._preview(db, preview_id)
            require(evidence.account_id == p.draft.account_id and evidence.occurred_at <= now
                    and evidence.reason in {'MAINTENANCE_UNVERIFIED', 'MARGIN_CALL', 'BORROW_RECALL'},
                    'INVALID_RESTRICTION')
            projection = self._projection(db)
            old = projection['restrictions'].get(evidence.account_id)
            if old is not None:
                require(old == evidence, 'RESTRICTION_CONFLICT')
            else:
                projection['restrictions'][evidence.account_id] = evidence
                self._ledger_write(db, evidence.event_id, 'RESTRICTION', preview_id, evidence, projection, now)
        return self.snapshot(preview_id)

    def snapshot(self, preview_id):
        """Read only, closed-world settlement view; never exposes private challenges."""
        with connection(self._sandbox, readonly=True) as db:
            db.execute('BEGIN')
            self._verify(db)
            p = self._preview(db, preview_id)
            projection = self._projection(db)
            settled = projection['settlements'].get(preview_id)
            row = db.execute('SELECT payload FROM orders WHERE id=?', (preview_id,)).fetchone()
            order = loads(row[0]) if row else None
            lots = ledger.order_lots(projection, preview_id)
            lifecycle = ('SETTLED' if settled else 'TRADE_FILL' if lots else
                         'BROKER_MOCK_ACCEPT' if order and any(e.kind is EventKind.ACCEPTED for e in order.events)
                         else 'ORDER_CONFIRM' if order and order.confirmed_at else 'PREVIEW')
            return Envelope(dict(stage='SETTLED' if settled else 'UNSETTLED',
                lifecycle=lifecycle,
                cost_evidence='VERIFIED_SYNTHETIC' if settled else 'UNVERIFIED',
                fills=ledger.order_lots(projection, preview_id),
                account_deltas=tuple(b for b in projection['balances'].values()
                                     if b['account_id'] == p.draft.account_id),
                restricted=p.draft.account_id in projection['restrictions'],
                reservation_released=settled is not None))

    def dispatch(self, preview_id, *, now, fixture=Fixture.ACCEPT, kind="SEND", crash_at=None):
        require(kind in {"SEND", "CANCEL"}, "INVALID_COMMAND")
        require(type(fixture) is Fixture, 'INVALID_MOCK_FIXTURE')
        sdk = fixture.value.startswith('SDK_')
        command_id = digest_of((preview_id, kind))
        claimed = False
        with self._command(now, "DISPATCH", preview_id) as db:
            self._order(db, preview_id)
            row = db.execute("SELECT id FROM outbox WHERE id=?", (command_id,)).fetchone()
            require(row is not None, "NO_OUTBOX_COMMAND")
            if self._latest(db, command_id) == "READY":
                order = self._order(db, preview_id)
                require(order.state is (State.SIMULATED_PENDING if kind == 'SEND' else State.CANCEL_PENDING),
                        "DISPATCH_STATE_BLOCKED")
                p = self._preview(db, preview_id)
                if kind == 'SEND':
                    require(p.draft.account_id not in self._projection(db)['restrictions'], 'ACCOUNT_RESTRICTED')
                if kind == 'SEND' and p.draft.contract_version == 2:
                    assess(p.draft, self._settled_evidence(p.draft, p.evidence, self._projection(db)), now)
                # Validate fixture before irreversible claim, with no effect.
                if sdk:
                    require((kind == 'CANCEL') == (fixture is Fixture.SDK_CANCEL), 'INVALID_MOCK_FIXTURE')
                    fake_sdk.convert(p.draft, fake_sdk.FakeUnits(p.draft.lot,
                        1000 if p.draft.lot.value == 'BOARD' else 1))
                    if kind == 'SEND':
                        require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
                        require(now < p.challenge.expires_at, 'PREVIEW_EXPIRED')
                    else:
                        require(self._verified_fake_id(db, preview_id) is not None, 'BROKER_ORDER_ID_UNVERIFIED')
                else:
                    receipt(command_id, preview_id, kind, fixture, now, 1, 0)
                self._crash(crash_at, "before_claim")
                self._stage(db, command_id, "CLAIMED", now)
                self._audit(db, now, "DISPATCH_CLAIM", preview_id, {"command_id": command_id})
                claimed = True
        if not claimed:
            return self.status(preview_id)
        self._crash(crash_at, "after_claim")
        effect_created = False
        with self._command(now, "MOCK_EFFECT", preview_id) as db:
            # Fencing: recovery can close an abandoned claim before a delayed worker resumes.
            if self._latest(db, command_id) == "CLAIMED":
                if kind == 'SEND':
                    p = self._preview(db, preview_id)
                    require(p.draft.account_id not in self._projection(db)['restrictions'], 'ACCOUNT_RESTRICTED')
                    if sdk:
                        require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
                        require(now < p.challenge.expires_at, 'PREVIEW_EXPIRED')
                        assess(p.draft, self._settled_evidence(p.draft, p.evidence, self._projection(db)), now)
                order = self._order(db, preview_id)
                if sdk:
                    p = self._preview(db, preview_id)
                    proof = fake_sdk.invoke(p.draft, fixture.value, command_id, preview_id=preview_id,
                        now=now, sequence=order.last_report_sequence + 1, filled=order.cumulative_filled)
                    report = proof['report']
                    self._audit(db, now, 'FAKE_SDK', preview_id, proof)
                else:
                    report = receipt(command_id, preview_id, kind, fixture, now,
                                     order.last_report_sequence + 1, order.cumulative_filled)
                db.execute("INSERT INTO mock_effects VALUES(?,?,?)", (command_id, fixture.value, dumps(report)))
                self._audit(db, now, "MOCK_EFFECT", preview_id,
                            {"command_id": command_id, "fixture": fixture.value, "receipt": report})
                effect_created = True
        if not effect_created:
            return self.status(preview_id)
        self._crash(crash_at, "after_effect")
        with self._command(now, "DISPATCH_RESULT", preview_id) as db:
            if self._latest(db, command_id) == "CLAIMED":
                if fixture in {Fixture.TIMEOUT, Fixture.QUERY_UNAVAILABLE, Fixture.QUERY_ERROR,
                               Fixture.SDK_TIMEOUT, Fixture.SDK_AMBIGUOUS}:
                    self._timeout(db, preview_id, now, "timeout-" + command_id)
                    self._stage(db, command_id, "UNKNOWN", now)
                else:
                    if report is not None:
                        self._event(db, report, now)
                    self._stage(db, command_id, "COMPLETED", now)
        return self.status(preview_id)

    def _timeout(self, db, preview_id, now, event_id):
        order = self._order(db, preview_id)
        if order.state not in {State.UNKNOWN, State.SIMULATED_FILLED, State.SIMULATED_CANCELLED, State.SIMULATED_REJECTED}:
            self._event(db, SimulationEvent(event_id, preview_id, EventKind.TIMEOUT, now), now)

    def rehearsal_claim(self, preview_id, *, kind, generation, digest, request_id, now):
        """Persist a LOCAL MOCK transport claim. Never authorizes a real SDK.

        Same admission, reservation, confirmation, journal and reducer as M2A.
        The caller must finish this command BEFORE invoking its closed fake.
        An abandoned claim is never reclaimed, including after process death.
        """
        require(kind in {'SEND', 'QUERY', 'CANCEL'}, 'INVALID_COMMAND')
        identifier(generation)
        identifier(request_id)
        claim = None
        with self._command(now, 'REHEARSAL_CLAIM_COMMAND', preview_id) as db:
            fences = db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_FENCE'").fetchall()
            require(not any(loads(row[0])['value']['generation'] == generation for row in fences),
                    'WORKER_GENERATION_FENCED')
            p = self._preview(db, preview_id)
            order = self._order(db, preview_id)
            require(p.draft.account_id.startswith('synthetic-'), 'FIXTURE_IDENTITY_ONLY')
            require(digest == p.challenge.digest, 'PAYLOAD_DIGEST_MISMATCH')
            if kind == 'SEND':
                require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
            kind_key = kind if kind == 'SEND' else 'REHEARSAL_' + kind + ':' + request_id
            command_id = digest_of((preview_id, kind_key))
            row = db.execute('SELECT id FROM outbox WHERE id=?', (command_id,)).fetchone()
            if row is None:
                require(kind != 'SEND', 'NO_OUTBOX_COMMAND')
                self._enqueue(db, preview_id, kind_key, now)
            if self._latest(db, command_id) == 'READY':
                if kind == 'SEND':
                    require(order.state is State.SIMULATED_PENDING, 'DISPATCH_STATE_BLOCKED')
                    require(now < p.challenge.expires_at, 'PREVIEW_EXPIRED')
                    require(p.draft.account_id not in self._projection(db)['restrictions'], 'ACCOUNT_RESTRICTED')
                    assess(p.draft, self._settled_evidence(p.draft, p.evidence, self._projection(db)), now)
                    last = db.execute("SELECT occurred_at FROM audit WHERE operation='REHEARSAL_CLAIM' "
                                      "ORDER BY seq DESC LIMIT 1").fetchone()
                    require(last is None or (now - datetime.fromisoformat(last[0])).total_seconds() > 1,
                            'ORDER_INTERVAL_NOT_GREATER_THAN_ONE_SECOND')
                else:
                    require(db.execute("SELECT 1 FROM audit WHERE operation='REHEARSAL_CLAIM' "
                                       'AND preview_id=?', (preview_id,)).fetchone() is not None,
                            'REHEARSAL_SEND_REQUIRED')
                    if kind == 'CANCEL':
                        require(order.state in {State.SIMULATED_ACCEPTED, State.SIMULATED_PARTIALLY_FILLED},
                                'BROKER_ORDER_ID_UNVERIFIED')
                        require(not order.cancel_requested, 'CANCEL_ALREADY_REQUESTED')
                        self._event(db, SimulationEvent('rehearsal-cancel-' + command_id, preview_id,
                                    EventKind.CANCEL_REQUESTED, now), now)
                    elif order.state is State.UNKNOWN:
                        self._event(db, SimulationEvent('rehearsal-query-' + command_id, preview_id,
                                    EventKind.RECONCILE, now), now)
                self._stage(db, command_id, 'CLAIMED', now)
                claim = {'command_id': command_id, 'preview_id': preview_id, 'kind': kind,
                         'generation': generation, 'digest': digest}
                self._audit(db, now, 'REHEARSAL_CLAIM', preview_id, claim)
        return Envelope(claim)

    @staticmethod
    def _rehearsal_claim_row(db, claim):
        require(type(claim) is dict and set(claim) == {
            'command_id', 'preview_id', 'kind', 'generation', 'digest'}, 'INVALID_REHEARSAL_CLAIM')
        rows = db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_CLAIM' AND preview_id=?",
                          (claim['preview_id'],)).fetchall()
        require(any(loads(row[0])['value'] == claim for row in rows), 'WORKER_GENERATION_FENCED')
        fences = db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_FENCE'").fetchall()
        require(not any(loads(row[0])['value']['generation'] == claim['generation'] for row in fences),
                'WORKER_GENERATION_FENCED')

    def rehearsal_fence(self, generation, *, now):
        """Explicitly revoke a dead fixture worker; never resume or retry its effects."""
        identifier(generation)
        with self._command(now, 'REHEARSAL_FENCE_COMMAND') as db:
            self._audit(db, now, 'REHEARSAL_FENCE', None, {'generation': generation})
            rows = db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_CLAIM'").fetchall()
            for row in rows:
                claim = loads(row[0])['value']
                if claim['generation'] == generation and self._latest(db, claim['command_id']) == 'CLAIMED':
                    self._stage(db, claim['command_id'], 'UNKNOWN', now)
                    self._timeout(db, claim['preview_id'], now, 'fenced-' + claim['command_id'])

    def rehearsal_check_effect(self, claim, *, now):
        """Last LOCAL_MOCK check outside the claim transaction, before fixture IO.

        This cannot revoke an already executing external effect. It does not
        constitute native process confinement or a REAL_SIM send authorization.
        """
        instant(now)
        with connection(self._sandbox, readonly=True) as db:
            db.execute('BEGIN')
            self._verify(db)
            self._rehearsal_claim_row(db, claim)
            require(self._latest(db, claim['command_id']) == 'CLAIMED', 'WORKER_GENERATION_FENCED')
            last = db.execute("SELECT value FROM metadata WHERE key='last_now'").fetchone()
            require(last is None or now >= loads(last[0]), 'CLOCK_REGRESSION')
            if claim['kind'] == 'SEND':
                require(self._mock_send_enabled(db), 'KILL_SWITCH_ACTIVE')
                p = self._preview(db, claim['preview_id'])
                require(now < p.challenge.expires_at, 'PREVIEW_EXPIRED')
                require(self._order(db, p.preview_id).state is State.SIMULATED_PENDING,
                        'DISPATCH_STATE_BLOCKED')
                require(p.draft.account_id not in self._projection(db)['restrictions'], 'ACCOUNT_RESTRICTED')
                assess(p.draft, self._settled_evidence(p.draft, p.evidence, self._projection(db)), now)
        return Envelope({'checked': True, 'scope': 'LOCAL_MOCK'})

    def rehearsal_result(self, claim, *, outcome, now):
        """A transport return can prove only pending/unknown, never acceptance."""
        require(outcome in {'PENDING', 'UNKNOWN'}, 'INVALID_TRANSPORT_RESULT')
        with self._command(now, 'REHEARSAL_RESULT_COMMAND', claim['preview_id']) as db:
            self._rehearsal_claim_row(db, claim)
            require(self._latest(db, claim['command_id']) == 'CLAIMED', 'WORKER_GENERATION_FENCED')
            self._audit(db, now, 'REHEARSAL_RESULT', claim['preview_id'],
                        {'claim': claim, 'outcome': outcome})
            self._stage(db, claim['command_id'], 'UNKNOWN' if outcome == 'UNKNOWN' else 'COMPLETED', now)
            if outcome == 'UNKNOWN':
                self._timeout(db, claim['preview_id'], now, 'rehearsal-timeout-' + claim['command_id'])
        return self.status(claim['preview_id'])

    @staticmethod
    def _rehearsal_report_kind(proof, *, legacy=False):
        claim, task, status = proof['claim'], proof['task'], proof['status']
        require(claim['kind'] in ({'SEND', 'QUERY'} if task == 'NewOrder' else {'CANCEL', 'QUERY'}),
                'OBSERVATION_COMMAND_MISMATCH')
        if (task, status) == ('CancelOrder', 'Success'):
            # Historical journals retain their original reducer event. New writes
            # always carry ACK_ONLY and can never use this compatibility branch.
            if legacy and 'semantics' not in proof:
                return EventKind.CANCELLED
            require(proof.get('semantics') == 'ACK_ONLY', 'UNPROVEN_BROKER_OBSERVATION')
            return None
        if (task, status) == ('OrderStatus', 'Cancelled'):
            expected = {'origin': 'SYNTHETIC', 'scope': 'LOCAL_MOCK',
                        'command_id': claim['command_id'], 'preview_id': claim['preview_id'],
                        'generation': claim['generation'], 'order_id': 'LOCAL-ORDER',
                        'status': 'Cancelled', 'complete': True}
            require(dumps(proof.get('finality_fixture')) == dumps(expected),
                    'FINALITY_FIXTURE_UNVERIFIED')
            return EventKind.CANCELLED
        mapping = {('NewOrder', 'Success'): EventKind.ACCEPTED,
                   ('NewOrder', 'Failed'): EventKind.REJECTED}
        require((task, status) in mapping, 'UNPROVEN_BROKER_OBSERVATION')
        return mapping[(task, status)]

    def rehearsal_report(self, claim, *, generation, task, status, order_id, now,
                         finality_fixture=None):
        """Explicit correlated LOCAL MOCK observation, no raw SDK payload storage.

        LOCAL-ORDER is a fixture identifier, never an actual broker order ID.
        A real callback cannot enter this protocol or become synthetic evidence.
        """
        require(generation == claim['generation'], 'WORKER_GENERATION_FENCED')
        require(order_id == 'LOCAL-ORDER', 'BROKER_ORDER_ID_UNVERIFIED')
        proof = {'claim': claim, 'task': task, 'status': status, 'order_id': order_id}
        if (task, status) == ('CancelOrder', 'Success'):
            proof['semantics'] = 'ACK_ONLY'
        if finality_fixture is not None:
            require((task, status) == ('OrderStatus', 'Cancelled'), 'FINALITY_FIXTURE_UNVERIFIED')
            proof['finality_fixture'] = finality_fixture
        event_kind = self._rehearsal_report_kind(proof)
        with self._command(now, 'REHEARSAL_REPORT_COMMAND', claim['preview_id']) as db:
            self._rehearsal_claim_row(db, claim)
            require(self._latest(db, claim['command_id']) == 'COMPLETED', 'WORKER_GENERATION_FENCED')
            order = self._order(db, claim['preview_id'])
            require(self._preview(db, claim['preview_id']).draft.account_id.startswith('synthetic-'),
                    'FIXTURE_IDENTITY_ONLY')
            event_id = 'rehearsal-' + digest_of(proof)
            previous = db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_REPORT' "
                                  'AND preview_id=?', (claim['preview_id'],)).fetchall()
            if not any(loads(row[0])['value'] == proof for row in previous):
                self._audit(db, now, 'REHEARSAL_REPORT', claim['preview_id'], proof)
                if event_kind is not None:
                    event = SimulationEvent(event_id, claim['preview_id'], event_kind, now,
                                            order.last_report_sequence + 1, order.cumulative_filled)
                    self._event(db, event, now)
        return self.status(claim['preview_id'])

    def recover(self, preview_id, *, now):
        """Explicitly fence abandoned claims. Never retries send, even without a mock receipt."""
        with self._command(now, "RECOVER", preview_id) as db:
            self._order(db, preview_id)
            for row in db.execute("SELECT id FROM outbox WHERE preview_id=?", (preview_id,)).fetchall():
                if self._latest(db, row[0]) == "CLAIMED":
                    self._stage(db, row[0], "UNKNOWN", now)
                    self._timeout(db, preview_id, now, "recovery-" + row[0])
                    self._audit(db, now, "RECOVERY", preview_id, {"command_id": row[0], "retry": False})
        return self.status(preview_id)

    def timeout(self, preview_id, *, now):
        with self._command(now, "TIMEOUT", preview_id) as db:
            self._timeout(db, preview_id, now, "manual-timeout-" + secrets.token_hex(16))
        return self.status(preview_id)

    def cancel(self, preview_id, *, now, user_confirmed):
        with self._command(now, "CANCEL", preview_id) as db:
            require(user_confirmed is True, "EXPLICIT_CONFIRMATION_REQUIRED")
            preview = self._preview(db, preview_id)
            row = db.execute('SELECT payload FROM orders WHERE id=?', (preview_id,)).fetchone()
            order = loads(row[0]) if row else OrderState(preview_id, preview.draft.quantity, State.PREVIEWED, None)
            sent = db.execute("SELECT 1 FROM mock_effects m JOIN outbox o ON m.command_id=o.id "
                              "WHERE o.preview_id=? AND o.kind='SEND'", (preview_id,)).fetchone()
            require(sent is not None or order.state in {State.PREVIEWED, State.UNKNOWN, State.RECONCILING}
                    or order.cancel_requested, "MOCK_SEND_REQUIRED")
            prior = db.execute("SELECT 1 FROM outbox WHERE preview_id=? AND kind='CANCEL'", (preview_id,)).fetchone()
            if not order.cancel_requested:
                self._event(db, SimulationEvent("cancel-" + preview_id, preview_id,
                                                EventKind.CANCEL_REQUESTED, now), now)
            # UNKNOWN remains intent-only, including timeout before any mock effect.
            # A later explicit cancel after reconciliation can enqueue the first CANCEL.
            order = self._order(db, preview_id)
            if prior is None and sent is not None and order.state is State.CANCEL_PENDING:
                self._enqueue(db, preview_id, "CANCEL", now)
        return self.status(preview_id)

    def _query(self, db, preview_id, now):
        row = db.execute("SELECT m.command_id,m.fixture,m.receipt FROM mock_effects m JOIN outbox o ON o.id=m.command_id "
                         "WHERE o.preview_id=? ORDER BY CASE o.kind WHEN 'CANCEL' THEN 0 ELSE 1 END LIMIT 1",
                         (preview_id,)).fetchone()
        outcome = "AVAILABLE"
        report = loads(row['receipt']) if row else None
        if row and row['fixture'].startswith('SDK_'):
            p, order = self._preview(db, preview_id), self._order(db, preview_id)
            proof = fake_sdk.invoke(p.draft, row['fixture'], row['command_id'], preview_id=preview_id,
                now=now, sequence=order.last_report_sequence + 1, filled=order.cumulative_filled, query=True)
            self._audit(db, now, 'FAKE_QUERY', preview_id, proof)
            report = proof['report']
        if not row or report is None:
            outcome = "ERROR" if row and row['fixture'] == Fixture.QUERY_ERROR.value else "UNAVAILABLE"
        self._audit(db, now, "MOCK_QUERY", preview_id, {"outcome": outcome, "report": report})
        return {"outcome": outcome, "report": report}

    def query(self, preview_id, *, now):
        """Explicit mock-query command; unlike status, intentionally appends audit."""
        with self._command(now, "QUERY", preview_id) as db:
            self._order(db, preview_id)
            result = self._query(db, preview_id, now)
        return Envelope(result)

    def reconcile(self, preview_id, *, now, user_confirmed):
        with self._command(now, "RECONCILE", preview_id) as db:
            require(user_confirmed is True, "EXPLICIT_CONFIRMATION_REQUIRED")
            # Manual reconciliation fences interrupted fake dispatch before reading
            # its durable observation. It never reclaims or resends the command.
            if db.execute("SELECT 1 FROM audit WHERE operation='FAKE_PREVIEW' AND preview_id=?",
                          (preview_id,)).fetchone():
                for row in db.execute('SELECT id FROM outbox WHERE preview_id=?', (preview_id,)).fetchall():
                    if self._latest(db, row[0]) == 'CLAIMED':
                        self._stage(db, row[0], 'UNKNOWN', now)
                        self._timeout(db, preview_id, now, 'manual-fence-' + row[0])
            order = self._order(db, preview_id)
            fake = self._fake_proof(db, preview_id) is not None
            require(order.state in {State.UNKNOWN, State.RECONCILING} or (fake and order.state in {
                State.SIMULATED_PENDING, State.CANCEL_PENDING}), "INVALID_TRANSITION")
            if order.state is State.UNKNOWN:
                self._event(db, SimulationEvent("reconcile-" + secrets.token_hex(16), preview_id,
                                                EventKind.RECONCILE, now), now)
            result = self._query(db, preview_id, now)
            if result['report'] is not None:
                self._event(db, result['report'], now)
        return self.status(preview_id)

    @staticmethod
    def _mock_send_enabled(db):
        row = db.execute("SELECT payload FROM audit WHERE operation='MOCK_KILL_SWITCH' ORDER BY seq DESC LIMIT 1").fetchone()
        return row is not None and loads(row[0])['value']['enabled'] is True

    def set_mock_send_enabled(self, enabled, *, now, user_confirmed):
        require(type(enabled) is bool and user_confirmed is True, 'EXPLICIT_CONFIRMATION_REQUIRED')
        with self._command(now, 'MOCK_CONTROL') as db:
            self._audit(db, now, 'MOCK_KILL_SWITCH', None, {'enabled': enabled})

    @staticmethod
    def _fake_proof(db, preview_id):
        row = db.execute("SELECT payload FROM audit WHERE preview_id=? AND operation IN ('FAKE_SDK','FAKE_QUERY') "
                         "ORDER BY seq DESC LIMIT 1", (preview_id,)).fetchone()
        return loads(row[0])['value'] if row else None

    @staticmethod
    def _verified_fake_id(db, preview_id):
        p = SimulationApplication._preview(db, preview_id)
        for row in db.execute("SELECT payload FROM audit WHERE preview_id=? AND operation IN ('FAKE_SDK','FAKE_QUERY') "
                              "ORDER BY seq DESC", (preview_id,)):
            proof = loads(row[0])['value']
            report, raw = proof['report'], proof['observation']
            if report is not None and report.kind in {EventKind.ACCEPTED, EventKind.CANCELLED}:
                require(raw['binding'] == digest_of(p.draft), 'BROKER_IDENTITY_MISMATCH')
                return raw['order_id']
        return None

    def mock_broker_status(self, preview_id):
        """Pure read projection; broker acceptance is never inferred from app receipt."""
        value = self.status(preview_id).value
        with connection(self._sandbox, readonly=True) as db:
            db.execute('BEGIN')
            self._verify(db)
            proof = self._fake_proof(db, preview_id)
            p = self._preview(db, preview_id)
            order_id = self._verified_fake_id(db, preview_id)
            raw = proof['observation'] if proof else None
        state = value['order'].state
        status = {'PREVIEWED': 'READY', 'SIMULATED_PENDING': 'PENDING',
                  'SIMULATED_ACCEPTED': 'BROKER_ACCEPTED', 'SIMULATED_REJECTED': 'BROKER_REJECTED',
                  'SIMULATED_CANCELLED': 'CANCELLED', 'SIMULATED_FILLED': 'FILLED',
                  'SIMULATED_PARTIALLY_FILLED': 'PARTIALLY_FILLED'}.get(state.value, state.value)
        if status == 'BROKER_ACCEPTED' and order_id is None:
            status = 'UNKNOWN'
        commands = value['commands']
        if any(c['stage'] == 'CLAIMED' for c in commands):
            status = 'UNKNOWN'  # Abandoned or in-flight claim cannot imply success.
        reasons = []
        if status in {'UNKNOWN', 'RECONCILING'}:
            reasons.append('CLAIM_OUTCOME_UNKNOWN' if any(c['stage'] == 'CLAIMED' for c in commands)
                           else 'QUERY_NO_MATCH_NOT_PROOF_OF_ABSENCE' if proof and proof['source'] == 'query' and raw is None
                           else 'TRANSPORT_OUTCOME_UNKNOWN')
        return Envelope({'status': status, 'order_id': order_id,
            'order_id_verified': order_id is not None, 'filled_shares': value['order'].cumulative_filled,
            'errcode': raw.get('errcode') if raw else None, 'msg': raw.get('msg') if raw else None,
            'immediate_status': 'Pending' if proof and proof['immediate'] else None,
            'commands': commands, 'source': proof['source'] if proof else None,
            'symbol': p.draft.instrument.symbol,
            'reasonCodes': reasons,
            'simulated': True, 'reservations_retained': True})

    def status(self, preview_id):
        with connection(self._sandbox, readonly=True) as db:
            db.execute("BEGIN")
            preview = self._preview(db, preview_id)
            self._verify(db)
            row = db.execute("SELECT payload FROM orders WHERE id=?", (preview_id,)).fetchone()
            order = loads(row[0]) if row else OrderState(preview_id, preview.draft.quantity, State.PREVIEWED, None)
            commands = tuple({"kind": r['kind'], "stage": self._latest(db, r['id']),
                              "mock_effects": db.execute("SELECT count(*) FROM mock_effects WHERE command_id=?",
                                                         (r['id'],)).fetchone()[0]}
                             for r in db.execute("SELECT id,kind FROM outbox WHERE preview_id=? ORDER BY kind", (preview_id,)))
            # Raw event identifiers are caller-controlled; status is an allowlisted projection.
            return Envelope({"order": replace(order, events=()), "commands": commands,
                             "simulation_attempts": 0 if order.confirmed_at is None else 1,
                             "digest": preview.challenge.digest,
                             "draft_digest": digest_of(preview.draft), "evidence_digest": digest_of(preview.evidence)})

    def audit(self):
        with connection(self._sandbox, readonly=True) as db:
            db.execute('BEGIN')
            self._verify(db)
            # Never return internal payloads, confirmations, challenge or caller identifiers.
            return Envelope(tuple(dict(row) for row in db.execute(
                "SELECT seq,occurred_at,operation,hash AS digest FROM audit ORDER BY seq")))

    def verify(self):
        """Read-only hash-chain and reducer replay, compared with materialized orders."""
        with connection(self._sandbox, readonly=True) as db:
            db.execute("BEGIN")
            return self._verify(db)

    @staticmethod
    def _verify(db):
        try:
            return SimulationApplication._replay(db)
        except ExecutionRejected:
            raise
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise ExecutionRejected('CORRUPT_LEDGER_PAYLOAD') from None

    @staticmethod
    def _replay(db):
        previous = "0" * 64
        orders, previews, reservations, commands = {}, {}, {}, {}
        stages, effects = [], {}
        budgets, positions, last_now = {}, {}, None
        fake_effects = {}
        rehearsal_claims, rehearsal_results, rehearsal_reports = {}, {}, {}
        rehearsal_fences = set()
        confirmed_previews = []
        projection = ledger.empty_projection()
        ledger_events, before_events = {}, {}
        schema = db.execute('PRAGMA user_version').fetchone()[0]
        root = loads(db.execute('SELECT payload FROM settlement_root WHERE id=1').fetchone()[0]) if schema == 2 else None
        if root:
            require(set(root) == {'version', 'codec_version', 'policy_version', 'seq', 'head', 'sandbox_binding'}
                    and all(type(root[name]) is int for name in ('version', 'codec_version', 'seq'))
                    and root['seq'] >= 0
                    and root['version'] == 2 and root['codec_version'] == 1
                    and root['policy_version'] == 'synthetic-settlement-v2', 'SETTLEMENT_ROOT_MISMATCH')
            anchor = db.execute('SELECT hash FROM audit WHERE seq=?', (root['seq'],)).fetchone()
            require(root['head'] == (anchor[0] if anchor else '0' * 64)
                    and (anchor is not None or root['seq'] == 0), 'SETTLEMENT_ROOT_MISMATCH')
        for row in db.execute("SELECT * FROM audit ORDER BY seq"):
            stamp = datetime.fromisoformat(row['occurred_at'])
            instant(stamp)
            require(last_now is None or stamp >= last_now, 'AUDIT_TIME_REGRESSION')
            last_now = stamp
            require(row['previous_hash'] == previous, "AUDIT_CHAIN_BROKEN")
            previous = digest_of((row['occurred_at'], row['operation'], row['preview_id'], row['payload'], previous))
            require(previous == row['hash'], "AUDIT_CHAIN_BROKEN")
            wrapper = loads(row['payload'])
            require(wrapper['simulated'] is True and wrapper['broker_connected'] is False
                    and wrapper['test_only'] is True and wrapper['origin'] == 'SYNTHETIC', "AUDIT_ORIGIN_MISMATCH")
            value, key = wrapper['value'], row['preview_id']
            if row['operation'] == "PREVIEW":
                require(type(value) is Preview, "CORRUPT_LEDGER_PAYLOAD")
                expected = assess(value.draft, SimulationApplication._settled_evidence(
                    value.draft, value.evidence, projection), value.created_at)
                expected = replace(expected, valid_until=min(expected.valid_until, value.created_at + timedelta(seconds=60)))
                require(value.assessment == expected and value.challenge.expires_at == expected.valid_until
                        and value.challenge.principal_id == value.evidence.permission.principal_id,
                        'ASSESSMENT_PROJECTION_MISMATCH')
                require(value.challenge.digest == digest_of((value.preview_id, value.draft, value.evidence,
                                                             value.assessment, value.created_at)), "PREVIEW_TAMPERED")
                previews[key] = value
            elif row['operation'] == "CONFIRM":
                p = previews[key]
                require(key not in orders, 'CHALLENGE_CONSUMED')
                expected = OrderState(key, p.draft.quantity, State.SIMULATED_PENDING,
                                      datetime.fromisoformat(row['occurred_at']))
                require(value['order'] == expected, "CONFIRMATION_PROJECTION_MISMATCH")
                orders[key] = expected
                reservations[key] = value['reservation']
                a = p.evidence.account
                assessment = assess(p.draft, SimulationApplication._settled_evidence(p.draft, p.evidence, projection), stamp)
                require(reservations[key] == SimulationApplication._reservation(p, assessment),
                        'RESERVATION_PROJECTION_MISMATCH')
                remaining = SimulationApplication._admission(p, confirmed_previews, projection)
                assess(p.draft, remaining, stamp)
                confirmed_previews.append(p)
                binding = digest_of((a.ref, a.currency, a.available_cash))
                budget = (binding, a.available_cash)
                require(a.account_id not in budgets or budgets[a.account_id] == budget, 'BUDGET_BASELINE_CHANGED')
                budgets[a.account_id] = budget
                position_key = (a.account_id, digest_of(a.instrument))
                position = (digest_of((a.ref, a.instrument, a.sellable_quantity)), a.sellable_quantity)
                require(position_key not in positions or positions[position_key] == position, 'POSITION_BASELINE_CHANGED')
                positions[position_key] = position
            elif row['operation'] == "OUTBOX":
                commands[value['command_id']] = (key, value['kind'])
            elif row['operation'] == "OUTBOX_STAGE":
                stages.append((value['command_id'], value['stage'], row['occurred_at']))
            elif row['operation'] == "MOCK_EFFECT":
                effects[value['command_id']] = (value['fixture'], value['receipt'])
            elif row['operation'] == 'REHEARSAL_CLAIM':
                command_id = value['command_id']
                require(command_id not in rehearsal_claims and command_id in commands
                        and commands[command_id][0] == key and value['preview_id'] == key
                        and value['digest'] == previews[key].challenge.digest
                        and value['kind'] in {'SEND', 'QUERY', 'CANCEL'}
                        and value['generation'] not in rehearsal_fences
                        and stages[-1][:2] == (command_id, 'CLAIMED'), 'REHEARSAL_CLAIM_MISMATCH')
                identifier(value['generation'])
                rehearsal_claims[command_id] = value
            elif row['operation'] == 'REHEARSAL_FENCE':
                identifier(value['generation'])
                rehearsal_fences.add(value['generation'])
            elif row['operation'] == 'REHEARSAL_RESULT':
                command_id = value['claim']['command_id']
                require(rehearsal_claims.get(command_id) == value['claim']
                        and command_id not in rehearsal_results
                        and value['claim']['generation'] not in rehearsal_fences
                        and value['outcome'] in {'PENDING', 'UNKNOWN'}, 'REHEARSAL_RESULT_MISMATCH')
                rehearsal_results[command_id] = value['outcome']
            elif row['operation'] == 'REHEARSAL_REPORT':
                command_id = value['claim']['command_id']
                require(rehearsal_claims.get(command_id) == value['claim']
                        and rehearsal_results.get(command_id) == 'PENDING'
                        and value['claim']['generation'] not in rehearsal_fences
                        and value['order_id'] == 'LOCAL-ORDER'
                        and previews[key].draft.account_id.startswith('synthetic-'),
                        'REHEARSAL_REPORT_MISMATCH')
                report_kind = SimulationApplication._rehearsal_report_kind(value, legacy=True)
                rehearsal_reports['rehearsal-' + digest_of(value)] = (key, report_kind)
            elif row['operation'] in {'FAKE_SDK', 'FAKE_QUERY'}:
                order = orders[key]
                fake_sdk.validate_proof(previews[key].draft, value,
                    preview_id=key, now=stamp, sequence=order.last_report_sequence + 1,
                    filled=order.cumulative_filled, query=row['operation'] == 'FAKE_QUERY')
                if row['operation'] == 'FAKE_SDK':
                    require(value['command_id'] not in fake_effects, 'DUPLICATE_FAKE_EFFECT')
                    fake_effects[value['command_id']] = (value['scenario'], value['report'])
            elif row['operation'] == "EVENT":
                p = previews[key]
                event = value['event']
                if event.event_id.startswith('rehearsal-') and event.kind not in {
                        EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED}:
                    report = rehearsal_reports.get(event.event_id)
                    require(report is not None and report[0] == key, 'REHEARSAL_REPORT_MISMATCH')
                    expected_kind = report[1]
                    require(event.kind is expected_kind, 'REHEARSAL_REPORT_MISMATCH')
                if key not in orders:
                    orders[key] = OrderState(key, p.draft.quantity, State.PREVIEWED, None)
                if key in projection['settlements']:
                    require(value['event'] in orders[key].events, 'LATE_FILL_AFTER_SETTLEMENT')
                before_events[key] = orders[key]
                require(value['event'].occurred_at >= p.created_at, 'INVALID_EVENT_TIME')
                validate_fill(p.draft, p.evidence, value['event'])
                orders[key], reason = transition(orders[key], value['event'], datetime.fromisoformat(row['occurred_at']))
                require(reason == value['reason'], "AUDIT_REPLAY_MISMATCH")
            elif row['operation'] in {'FILL_LOT', 'SETTLEMENT', 'ACCRUAL', 'RESTRICTION'}:
                require(schema == 2 and row['seq'] > root['seq'], 'SETTLEMENT_SCHEMA_REQUIRED')
                p = previews[key]
                if row['operation'] == 'FILL_LOT':
                    require(value['before'] == before_events[key]
                            and orders[key].events[-1] == value['event'], 'FILL_LOT_DELTA_MISMATCH')
                    ledger.add_lot(projection, value['lot'], p, before_events[key], orders[key], stamp)
                    event_id = value['lot'].event_id
                elif row['operation'] == 'SETTLEMENT':
                    ledger.settle_projection(projection, p, orders[key], value['receipt'],
                                             value['fees'], value['interest'], stamp)
                    SimulationApplication._solvent(confirmed_previews, projection, p.draft.account_id)
                    event_id = value['receipt'].event_id
                elif row['operation'] == 'ACCRUAL':
                    ledger.accrue_projection(projection, value, p, stamp)
                    SimulationApplication._solvent(confirmed_previews, projection, p.draft.account_id)
                    event_id = value.event_id
                else:
                    require(type(value) is RestrictionEvidence and value.account_id == p.draft.account_id
                            and value.occurred_at <= stamp and value.reason in {
                                'MAINTENANCE_UNVERIFIED', 'MARGIN_CALL', 'BORROW_RECALL',
                                'CONTRADICTORY_FINALITY', 'SETTLEMENT_INSOLVENT'},
                            'INVALID_RESTRICTION')
                    projection['restrictions'][value.account_id] = value
                    event_id = value.event_id
                require(event_id not in ledger_events, 'EVENT_ID_CONFLICT')
                ledger_events[event_id] = (row['operation'], key, value)
        require(orders == {r['id']: loads(r['payload']) for r in db.execute("SELECT * FROM orders")},
                "ORDER_PROJECTION_MISMATCH")
        require(previews == {r['id']: loads(r['payload']) for r in db.execute("SELECT * FROM previews")},
                "PREVIEW_PROJECTION_MISMATCH")
        for row in db.execute('SELECT * FROM previews'):
            p = previews[row['id']]
            require((row['account_id'], row['request_id'], row['draft_digest'], row['evidence_digest']) ==
                    (p.draft.account_id, p.draft.client_request_id, digest_of(p.draft), digest_of(p.evidence)),
                    'PREVIEW_PROJECTION_MISMATCH')
        actual = {r['id']: {"cash": Decimal(r['cash']), "quantity": r['quantity'],
                            "instrument": r['instrument'], "account_id": r['account_id']}
                  for r in db.execute("SELECT * FROM reservations")}
        require(reservations == actual, "RESERVATION_PROJECTION_MISMATCH")
        require(budgets == {r['account_id']: (r['binding'], Decimal(r['cash']))
                           for r in db.execute('SELECT * FROM budgets')}, 'BUDGET_PROJECTION_MISMATCH')
        require(positions == {(r['account_id'], r['instrument']): (r['binding'], r['quantity'])
                             for r in db.execute('SELECT * FROM positions')}, 'POSITION_PROJECTION_MISMATCH')
        clock = db.execute("SELECT value FROM metadata WHERE key='last_now'").fetchone()
        require((loads(clock[0]) if clock else None) == last_now, 'CLOCK_PROJECTION_MISMATCH')
        require(commands == {r['id']: (r['preview_id'], r['kind']) for r in db.execute("SELECT * FROM outbox")},
                "OUTBOX_PROJECTION_MISMATCH")
        require(stages == [tuple(r) for r in db.execute(
            "SELECT command_id,stage,occurred_at FROM outbox_events ORDER BY seq")], "OUTBOX_STAGE_MISMATCH")
        require(effects == {r['command_id']: (r['fixture'], loads(r['receipt']))
                            for r in db.execute("SELECT * FROM mock_effects")}, "MOCK_EFFECT_MISMATCH")
        require(fake_effects == {k: v for k, v in effects.items() if v[0].startswith('SDK_')},
                'FAKE_PROOF_MISMATCH')
        confirmations = {r['id']: loads(r['payload']) for r in db.execute("SELECT * FROM confirmations")}
        require(set(confirmations) == {key for key, order in orders.items() if order.confirmed_at is not None},
                "CONFIRMATION_PROJECTION_MISMATCH")
        for key, c in confirmations.items():
            p = previews[key]
            require(c == Confirmation(key, p.challenge.token, p.challenge.digest,
                                      p.challenge.principal_id, True), "CONFIRMATION_PROJECTION_MISMATCH")
        if schema == 2:
            require(projection == SimulationApplication._projection(db), 'SETTLEMENT_PROJECTION_MISMATCH')
            require(ledger_events == {r['id']: (r['operation'], r['preview_id'], loads(r['payload']))
                    for r in db.execute('SELECT * FROM settlement_events')}, 'SETTLEMENT_EVENTS_MISMATCH')
            require({k: x['receipt'].event_id for k, x in projection['settlements'].items()} ==
                    {r['preview_id']: r['receipt_id'] for r in db.execute('SELECT * FROM releases')},
                    'RELEASE_PROJECTION_MISMATCH')
        return Envelope({"verified": True, "orders": len(orders), "audit_head": previous})
