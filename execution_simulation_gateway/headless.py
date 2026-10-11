"""Unregistered manual command contract for a future MCP App consumer.

No HTTP route, listener, MCP tool, worker dispatch or real authentication.
Server-owned LOCAL_MOCK dependencies exercise the future interaction boundary;
their identity/evidence must never be promoted to REAL_SIM qualification.
"""

from dataclasses import dataclass, replace
from enum import Enum

from execution.contracts import Confirmation, ExecutionRejected
from execution_simulation import SimulationApplication
from .contracts import decode, draft_from_wire, exact_fields, wire
from .policy import SyntheticFixturePolicy
from .security import HttpRejected, SyntheticAuth


class Command(str, Enum):
    PREVIEW = 'PREVIEW'
    CONFIRM = 'CONFIRM'
    STATUS = 'STATUS'
    QUERY = 'QUERY'
    RECONCILE = 'RECONCILE'
    CANCEL = 'CANCEL'


class CommandStatus(str, Enum):
    OK = 'OK'
    DENIED = 'DENIED'
    BLOCKED = 'BLOCKED'


@dataclass(frozen=True)
class CommandReply:
    status: CommandStatus
    data: object = None
    reason_codes: tuple[str, ...] = ()
    schema: str = 'omi.execution.manual-command.v1'
    source: str = 'SYNTHETIC'
    execution_scope: str = 'LOCAL_MOCK'
    real_sim: str = 'BLOCKED'
    live_session: str = 'BLOCKED'
    mcp_app_consumer: str = 'NOT_CONNECTED'


class HeadlessCommands:
    """Transport-only delegation to the SAME M2A command/transaction owner.

    Credentials are issued by the existing local SyntheticAuth server fixture.
    A consumer cannot provide account, principal, Evidence, origin or capability.
    Confirmation only reserves/enqueues; it never calls or dispatches a broker.
    """

    def __init__(self, application, auth, ingress, *, clock):
        if (type(application) is not SimulationApplication or type(auth) is not SyntheticAuth
                or type(ingress) is not SyntheticFixturePolicy):
            raise ValueError('LOCAL_MOCK_DEPENDENCIES_REQUIRED')
        self._application, self._auth, self._ingress, self._clock = application, auth, ingress, clock

    def execute(self, command, body, *, headers):
        try:
            if type(command) is not Command:
                raise HttpRejected(422, 'MANUAL_COMMAND_NOT_ALLOWED')
            if type(body) is not bytes or len(body) > 8192:
                raise HttpRejected(422, 'BOUNDED_JSON_REQUIRED')
            if (type(headers) is not dict or len(headers) > 16
                    or any(type(k) is not str or type(v) is not str for k, v in headers.items())
                    or sum(len(k) + len(v) for k, v in headers.items()) > 8192):
                raise HttpRejected(422, 'BOUNDED_HEADERS_REQUIRED')
            payload = decode(body)
            with self._auth.authorize(headers, clock=self._clock,
                                      mutation=command is not Command.STATUS) as (session, now):
                app = self._application
                if command is Command.PREVIEW:
                    draft, evidence = draft_from_wire(payload, session, self._ingress, self._auth)
                    draft = replace(draft, client_request_id=app.manual_request_id(
                        session.principal, session.account, payload['client_request_id']))
                    # Receipt time must be supplied by the SERVER fixture ingress.
                    # M1 validates ordering/expiry; receipt cannot freshen old source time.
                    if any(f.ref.received_at is None for f in (
                            evidence.market, evidence.account, evidence.permission)):
                        raise HttpRejected(422, 'INGRESS_RECEIPT_TIME_REQUIRED')
                    p = app.preview(draft, evidence, now=now).value
                    data = dict(preview_id=p.preview_id, draft=wire(p.draft),
                                assessment=wire(p.assessment), evidence_digest=app.status(p.preview_id).value['evidence_digest'],
                                order_access=self._auth.order_capability(session, p.preview_id),
                                confirmation=dict(token=p.challenge.token, digest=p.challenge.digest,
                                                  expires_at=p.challenge.expires_at.isoformat()),
                                required_action='CONFIRM_LOCAL_MOCK:' + p.challenge.digest)
                else:
                    fields = {'preview_id', 'order_access'}
                    if command is Command.CONFIRM:
                        fields |= {'token', 'digest', 'manual_action'}
                    elif command is not Command.STATUS:
                        fields |= {'manual_action'}
                    exact_fields(payload, fields)
                    key, access = payload['preview_id'], payload['order_access']
                    if type(access) is not str:
                        raise HttpRejected(403, 'ORDER_ACCESS_DENIED')
                    self._auth.require_order(session, key, access)
                    if command is Command.CONFIRM:
                        if (type(payload['digest']) is not str or
                                payload['manual_action'] != 'CONFIRM_LOCAL_MOCK:' + payload['digest']):
                            raise HttpRejected(403, 'EXACT_MANUAL_CONFIRMATION_REQUIRED')
                        data = app.confirm(Confirmation(key, payload['token'], payload['digest'],
                                                        session.principal, True), now=now).value
                    elif command is Command.STATUS:
                        data = app.status(key).value
                    else:
                        if payload['manual_action'] != command.value + '_LOCAL_MOCK:' + key:
                            raise HttpRejected(403, 'EXACT_MANUAL_CONFIRMATION_REQUIRED')
                        if command is Command.QUERY:
                            data = app.query(key, now=now).value
                        elif command is Command.RECONCILE:
                            data = app.reconcile(key, now=now, user_confirmed=True).value
                        else:
                            data = app.cancel(key, now=now, user_confirmed=True).value
                return CommandReply(CommandStatus.OK, wire(data))
        except (HttpRejected, ExecutionRejected) as exc:
            return CommandReply(CommandStatus.DENIED, reason_codes=(exc.code,))

    @staticmethod
    def real_readiness():
        # No proof flags or operator-provided booleans can change this answer.
        return CommandReply(CommandStatus.BLOCKED, reason_codes=(
            'REAL_AUTH_INGRESS_NOT_IMPLEMENTED', 'TRUSTED_REAL_EVIDENCE_NOT_IMPLEMENTED',
            'DURABLE_REAL_SIM_LEDGER_NOT_QUALIFIED', 'OFFICIAL_TEST_WORKER_NOT_QUALIFIED'))
