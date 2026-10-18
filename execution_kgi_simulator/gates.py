"""Fail-closed qualification, not account auth and not a trading calendar owner."""

from datetime import datetime, time, timedelta, timezone
from execution_kgi_simulator.login_probe import credential_owner_reference


TAIPEI = timezone(timedelta(hours=8))
SIM_NAMES = ('KGI_SIM_PERSON_ID', 'KGI_SIM_PASSWORD', 'KGI_SIM_ACCOUNT')
# Legacy presence keys are accepted only for old diagnostics, never required.
# Settings remains the single credential owner; SIM entitlement is independent.
PROBE_GAPS = (
    'SIM_ENTITLEMENT_UNVERIFIED', 'SIM_AUTH_UNVERIFIED',
    'BROKER_ENV_UNKNOWN', 'NATIVE_ENDPOINT_ATTESTATION_MISSING',
    'API_ENTITLEMENT_UNVERIFIED', 'CA_VALIDITY_UNVERIFIED', 'TAIWAN_IP_UNVERIFIED',
    'SESSION_COEXISTENCE_UNVERIFIED', 'NATIVE_LOG_REDACTION_UNVERIFIED',
    'NATIVE_EGRESS_CONFINEMENT_UNVERIFIED', 'NATIVE_FILESYSTEM_CONFINEMENT_UNVERIFIED',
    'SDK_ABI_UNVERIFIED', 'REVIEWED_PROBE_INGRESS_NOT_IMPLEMENTED',
)
ORDER_GAPS = ('QTY_UNIT_UNPROVEN', 'CREDIT_UNSUPPORTED', 'ODD_LOT_UNSUPPORTED',
              'CASH_SELLING_UNSUPPORTED', 'TRUSTED_ACCOUNT_AND_MARKET_INGRESS_MISSING',
              'EXACT_ORDER_CONFIRMATION_MISSING', 'BROKER_CORRELATION_UNVERIFIED',
              'BROKER_QUERY_COMPLETENESS_UNVERIFIED', 'DURABLE_REAL_SIM_LEDGER_MISSING',
              'REAL_SEND_NOT_IMPLEMENTED')


def service_window(now: datetime, *, business_dates=frozenset(), covered_dates=frozenset()):
    """Use supplied authoritative dates, never turn weekdays into business days.

    Before 05:00 belongs to the previous service date; 05:00 is exclusive.
    CLI supplies no calendar until a reviewed, read-only calendar binding exists.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        return 'CLOCK_UNVERIFIED'
    local = now.astimezone(TAIPEI)
    clock = local.time().replace(tzinfo=None)
    if time(5) <= clock < time(8, 30):
        return 'CLOSED_SESSION'
    service_date = local.date() - (timedelta(days=1) if clock < time(5) else timedelta())
    if service_date.weekday() >= 5:
        return 'CLOSED_SESSION'
    if service_date not in covered_dates:
        return 'BUSINESS_CALENDAR_UNVERIFIED'
    return 'OPEN' if service_date in business_dates else 'CLOSED_SESSION'


def preflight(sdk, presence, now, *, mode='Preflight'):
    credential_ref = credential_owner_reference()
    session = service_window(now)
    reasons = list(sdk.get('reasonCodes', ()))
    reasons.extend(PROBE_GAPS)
    if session != 'OPEN':
        reasons.append(session)
    return {'schema': 'omi.kgi-sim.preflight.v1', 'mode': mode, 'status': 'BLOCKED',
            'target': 'REAL_SIMULATOR', 'observed_at': now.astimezone(TAIPEI).isoformat(),
            'service_window': session, 'sdk': sdk,
            'dedicated_secret_presence': {name: presence.get(name) is True for name in SIM_NAMES},
            'dedicated_secret_presence_semantics': 'LEGACY_DIAGNOSTIC_NOT_REQUIRED',
            'credential_owner': credential_ref.owner,
            'credential_fields': list(credential_ref.fields),
            'credential_values_read': False,
            'probe': {'status': 'BLOCKED', 'reasonCodes': reasons},
            'order': {'status': 'BLOCKED', 'reasonCodes': reasons + list(ORDER_GAPS)},
            'sdk_imported': False, 'login_attempts': 0, 'broker_calls': 0,
            'orders_sent': 0, 'scheduled_orders': 0,
            'gates': {'SOURCE': 'OFFLINE_VALIDATION_REQUIRED', 'LOCAL_MOCK': 'NOT_RUN',
                      'REAL_SIMULATOR': 'BLOCKED', 'REAL_PRODUCTION': 'FORBIDDEN',
                      'LIVE_SESSION': 'BLOCKED', 'MCP_APP_CONSUMER': 'NOT_CONNECTED',
                      'FRONTEND': 'NOT_CONNECTED'}}
