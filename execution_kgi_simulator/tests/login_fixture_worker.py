"""Closed fake-only child; never imported by qualification or production.

FD suppression tests noisy native-shaped output, NOT native log confinement.
No real credentials, Settings import, kgisuperpy import or network is permitted.
"""

import io
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from execution_kgi_simulator.login_probe import exercise_fixture, read_private_frame, valid_generation
from execution_kgi_simulator.worker import readonly_guard

SCENARIOS = frozenset({'accept', 'reject', 'null', 'wrong_target', 'stale', 'mismatch',
    'error', 'timeout', 'hang', 'logout_error', 'logout_hang', 'late', 'cancel', 'noise',
    'preflight_denied', 'unknown', 'wrong_person', 'callback', 'logout_false'})


class FakeSDK:
    """Invented identity; order traps must never be accessed by the login port."""
    def __init__(self, scenario, generation):
        self.scenario, self.generation = scenario, generation
        self.person_id = None
        self.logins = self.readbacks = self.logouts = self.order_accesses = 0

    def _reply(self):
        return {'accepted': True, 'target': 'SIM', 'generation': self.generation,
                'person_id': self.person_id, 'broker': 'KGI', 'account': 'INVENTED_ACCOUNT',
                # Even SDK-provided write functions never cross the result boundary.
                'create_order': self.create_order, 'cancel_order': self.cancel_order,
                'raw': 'INVENTED_SECRET'}

    def create_order(self):
        self.order_accesses += 1
        raise AssertionError('FORBIDDEN_ORDER')

    cancel_order = create_order

    def login(self, person_id, password, *, simulation):
        assert simulation is True
        self.logins += 1
        self.person_id = person_id
        if self.scenario == 'noise':
            print(person_id, password, 'INVENTED_ACCOUNT')
            print(password, file=sys.stderr)
            os.write(1, password.encode())
            os.write(2, person_id.encode())
        if self.scenario == 'error':
            raise OSError(password)
        if self.scenario == 'timeout':
            raise TimeoutError(password)
        if self.scenario == 'hang':
            time.sleep(20)
        if self.scenario == 'late':
            time.sleep(.08)
        value = self._reply()
        if self.scenario == 'reject': value['accepted'] = False
        if self.scenario == 'unknown': value['accepted'] = None
        if self.scenario == 'wrong_target': value['target'] = 'PROD'
        if self.scenario == 'stale': value['generation'] = '0' * 32
        if self.scenario == 'null': value['account'] = None
        if self.scenario == 'wrong_person': value['person_id'] = 'INVENTED_OTHER'
        if self.scenario == 'callback':
            # Stray callback data is not authoritative readback and is ignored.
            value['callback'] = {'generation': '0' * 32, 'accepted': True, 'target': 'PROD'}
        return value

    def readback(self):
        self.readbacks += 1
        value = self._reply()
        if self.scenario == 'mismatch': value['account'] = 'INVENTED_OTHER_ACCOUNT'
        return value

    def logout(self):
        self.logouts += 1
        if self.scenario == 'logout_error': raise OSError('INVENTED_SECRET')
        if self.scenario == 'logout_hang': time.sleep(20)
        return self.scenario != 'logout_false'


class FakeLoginPort:
    __slots__ = ('__sdk',)

    def __init__(self, sdk):
        if type(sdk) is not FakeSDK:
            raise ValueError('FIXTURE_TYPE_REQUIRED')
        self.__sdk = sdk

    def login(self, person_id, password, *, simulation):
        assert simulation is True
        return self.__sdk.login(person_id, password, simulation=True)

    def readback(self):
        return self.__sdk.readback()

    def logout(self):
        return self.__sdk.logout()


def main():
    # Preserve only a private control output; discard both Python and OS FD noise
    # BEFORE constructing SDK-shaped objects. No disk capture or raw forwarding.
    control = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    with open(os.devnull, 'wb') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    sys.addaudithook(readonly_guard)
    result = {'status': 'BLOCKED', 'reasonCodes': ['INVALID_FIXTURE_INPUT'],
              'origin': 'LOCAL_MOCK', 'broker_calls': 0, 'orders_sent': 0}
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in SCENARIOS or not valid_generation(sys.argv[2]):
            raise ValueError
        scenario, generation = sys.argv[1:]
        credentials = read_private_frame(sys.stdin.buffer, generation)
        # Use the canonical module identity even when this file is __main__.
        from execution_kgi_simulator.tests.login_fixture_worker import FakeSDK as ClosedSDK, FakeLoginPort as ClosedPort
        sdk = ClosedSDK(scenario, generation)
        report = exercise_fixture(ClosedPort(sdk), credentials, generation=generation,
            test_preflight=scenario != 'preflight_denied',
            timeout_seconds=.04 if scenario == 'late' else 2,
            cancelled=lambda: scenario == 'cancel' and sdk.logins > 0)
        result = report.public()
        result['fixture_calls'] = {'login': sdk.logins, 'readback': sdk.readbacks,
                                   'logout': sdk.logouts, 'order': sdk.order_accesses}
    except Exception:
        pass  # Fixed diagnostic only. Deliberately no exception rendering.
    control.write(json.dumps(result) + '\n')
    control.flush()
    control.close()


if __name__ == '__main__':
    main()
