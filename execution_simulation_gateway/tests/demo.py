"""DIL-safe in-process demo. No listener, provider, real account or trade."""

import asyncio
import json

from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation_gateway import SyntheticAuth, build_test_app
from execution_simulation_gateway.gateway import PREFIX
from .http_driver import request
from .support import ORIGIN, confirm_body, draft, headers, policy_for


async def demonstrate():
    identities = [('synthetic-demo-a', 'synthetic-account-a'), ('synthetic-demo-b', 'synthetic-account-b')]
    auth = SyntheticAuth(origins={ORIGIN})
    policy = policy_for(*identities)
    with temporary_sandbox() as sandbox:
        app = build_test_app(sandbox, auth, policy, clock=lambda: NOW)
        runner = SimulationApplication(sandbox)

        async def user_path(identity):
            credentials = auth.issue(*identity, now=NOW)
            code, result = await request(app, 'POST', PREFIX + '/preview', headers=headers(credentials), body=draft())
            assert code == 200, result['errorCodes']
            preview = result['data']
            for _ in range(2):
                code, result = await request(app, 'POST', PREFIX + '/confirm', headers=headers(credentials, preview),
                                              body=confirm_body(preview))
                assert code == 200, result['errorCodes']
            runner.dispatch(preview['preview_id'], now=NOW)
            reopened = build_test_app(sandbox, auth, policy, clock=lambda: NOW)
            code, result = await request(reopened, 'GET', PREFIX + '/orders/' + preview['preview_id'],
                                          headers=headers(credentials, preview))
            assert code == 200 and result['status'] == 'SIMULATED_ACCEPTED'
            return {'status': result['status'], 'mock_effects': result['data']['commands'][0]['mock_effects'],
                    'simulated': True, 'broker_connected': False, 'test_only': True}

        return await asyncio.gather(*(user_path(identity) for identity in identities))


if __name__ == '__main__':
    print(json.dumps(asyncio.run(demonstrate()), indent=2))
