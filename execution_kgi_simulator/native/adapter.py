"""Real kgisuperpy 2.1.0 login-only adapter; unreachable until G1/G2 activation.

No SDK injection or production bridge singleton. No order/cancel/account binding.
SDK login has native side effects BEFORE returning; the gate must be kernel
enforced before import, not an after-the-fact simulation attribute inspection.
"""

import json

from execution_kgi_simulator.login_probe import Credentials
from execution_kgi_simulator.native.readiness import (
    require_verified_host, revalidate_reviewed_bytes,
)


def _readback_count(raw: str) -> int:
    """Read actual native GetAccounts JSON without retaining account identifiers."""
    if type(raw) is not str or len(raw) > 65536:
        raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
            value[key] = item
        return value
    rows = json.loads(raw, object_pairs_hook=unique)
    if type(rows) is not list or not 1 <= len(rows) <= 128:
        raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
    identities = set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
        for key in ('account', 'broker_id', 'account_flag'):
            item = row.get(key)
            if type(item) is not str or not 1 <= len(item) <= 128 or any(ord(c) < 32 for c in item):
                raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
        identity = (row['broker_id'], row['account'])
        if identity in identities:
            raise ValueError('NATIVE_ACCOUNT_READBACK_UNVERIFIED')
        identities.add(identity)
    return len(rows)


def _login_readback_logout(credentials: Credentials) -> dict:
    """Private one-attempt body for an attested SIM child, with no success claim.

    Must run with permanently suppressed native stdout/stderr and private control
    output supplied by a trusted host. SDK logout returns void; returned normally
    is not broker-confirmed logout. A future live protocol must close this gap.
    No retry after partial initialization or an unknown broker outcome.
    """
    require_verified_host()
    revalidate_reviewed_bytes()
    if type(credentials) is not Credentials:
        raise ValueError('PRIVATE_CREDENTIAL_TYPE_REQUIRED')
    api = None
    result = {'status': 'UNKNOWN', 'reasonCodes': ['NATIVE_LOGIN_UNVERIFIED'],
              'login_attempts': 0, 'account_readback': 'NOT_REQUESTED',
              'logout': 'NOT_REQUESTED', 'orders_sent': 0, 'cancel_requests': 0}
    try:
        import kgisuperpy as kgi

        require_verified_host()
        result['login_attempts'] = 1
        api = kgi.login(credentials.person_id, credentials.password, simulation=True)
        # Defense in depth only; cannot establish where Connect already went.
        if api.simulation is not True or api._ObjOrder.FIsLogon is not True:
            result['reasonCodes'] = ['NATIVE_LOGIN_OR_SIM_READBACK_UNVERIFIED']
        else:
            require_verified_host()
            _readback_count(api._ObjOrder.GetAccounts())
            result['account_readback'] = 'OBSERVED_NOT_ENTITLEMENT_PROOF'
            result['reasonCodes'] = ['NATIVE_LOGOUT_ACK_CONTRACT_UNVERIFIED']
    except Exception:
        result['reasonCodes'] = ['NATIVE_LOGIN_ONLY_FAILURE_REDACTED']
    finally:
        if api is not None:
            try:
                # _logout exists even when login fails before publishing logout.
                api._logout()
                result['logout'] = 'RETURNED_WITHOUT_BROKER_ACK'
            except Exception:
                result['logout'] = 'UNVERIFIED'
                result['reasonCodes'] = ['NATIVE_LOGOUT_UNVERIFIED']
            # SDK _logout preserves person_id/person_pwd; release those references.
            # No memory-zeroization or broker-finality assertion follows from this.
            try:
                api.person_id = None
                api.person_pwd = None
            except Exception:
                result['reasonCodes'] = ['NATIVE_REFERENCE_RELEASE_UNVERIFIED']
        credentials.clear()
    return result
