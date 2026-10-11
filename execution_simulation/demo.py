"""Reproducible no-listener integration smoke; every database is temporary."""

from dataclasses import replace
from decimal import Decimal

from execution.contracts import EventKind, ExecutionRejected, Side, SimulationEvent, State
from execution.tests.fixtures import NOW, confirmation, fixture

from .application import SimulationApplication
from .fixtures import symbol_fixture
from .mock import Fixture, SimulatedCrash
from .storage import temporary_sandbox


def run():
    rows = []
    for scenario in ('2330-full', 'reject', 'cancel-late-fill', 'timeout-reconcile',
                     'unavailable', 'query-error', 'cancel-pending', 'duplicate-out-of-order',
                     'crash-after-claim', 'crash-after-effect', 'cash-reserve', 'sellable-reserve'):
        with temporary_sandbox() as box:
            app = SimulationApplication(box)
            draft, evidence = symbol_fixture() if scenario == '2330-full' else fixture(
                side=Side.SELL if scenario == 'sellable-reserve' else Side.BUY)
            if scenario in {'cash-reserve', 'sellable-reserve'}:
                evidence = replace(evidence, account=replace(evidence.account,
                                   available_cash=Decimal('30000'), sellable_quantity=1000))
            p = app.preview(draft, evidence, now=NOW).value
            assert app.status(p.preview_id).value['order'].state is State.PREVIEWED
            app.confirm(confirmation(p), now=NOW)
            history = ['PREVIEWED', 'SIMULATED_PENDING']

            def remember():
                history.append(app.status(p.preview_id).value['order'].state.value)

            def event(kind, sequence, filled=0):
                report = SimulationEvent('demo-' + str(sequence), p.preview_id, kind, NOW, sequence, filled)
                app.callback(report, now=NOW)
                remember()
                return report

            outcome = 'PASS'
            if scenario.startswith('crash-'):
                try:
                    app.dispatch(p.preview_id, now=NOW,
                                 crash_at='after_claim' if scenario.endswith('claim') else 'after_effect')
                except SimulatedCrash:
                    pass
                app = SimulationApplication(box)
                app.recover(p.preview_id, now=NOW)
                remember()
                assert history[-1] == 'UNKNOWN'
                app.dispatch(p.preview_id, now=NOW)
                app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
                remember()
                assert history[-1] == ('RECONCILING' if scenario.endswith('claim') else 'SIMULATED_ACCEPTED')
            else:
                selected = {'reject': Fixture.REJECT, 'timeout-reconcile': Fixture.TIMEOUT,
                            'unavailable': Fixture.QUERY_UNAVAILABLE, 'query-error': Fixture.QUERY_ERROR}
                app.dispatch(p.preview_id, now=NOW, fixture=selected.get(scenario, Fixture.ACCEPT))
                remember()
                if scenario == '2330-full':
                    event(EventKind.PARTIAL_FILL, 2, 400)
                    event(EventKind.FILLED, 3, 1000)
                    assert history[-1] == 'SIMULATED_FILLED'
                elif scenario in {'timeout-reconcile', 'unavailable', 'query-error'}:
                    assert history[-1] == 'UNKNOWN'
                    app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
                    remember()
                    assert history[-1] == ('SIMULATED_ACCEPTED' if scenario == 'timeout-reconcile' else 'RECONCILING')
                elif scenario in {'cancel-late-fill', 'cancel-pending'}:
                    app.cancel(p.preview_id, now=NOW, user_confirmed=True)
                    remember()
                    app.dispatch(p.preview_id, now=NOW, kind='CANCEL',
                                 fixture=Fixture.CANCEL if scenario == 'cancel-late-fill' else Fixture.CANCEL_PENDING)
                    remember()
                    if scenario == 'cancel-late-fill':
                        event(EventKind.PARTIAL_FILL, 3, 400)
                        event(EventKind.FILLED, 4, 1000)
                    else:
                        assert history[-1] == 'CANCEL_PENDING'
                elif scenario == 'duplicate-out-of-order':
                    report = event(EventKind.PARTIAL_FILL, 3, 400)
                    app.callback(report, now=NOW)
                    event(EventKind.ACCEPTED, 2)
                    assert app.status(p.preview_id).value['order'].cumulative_filled == 400
                elif scenario.endswith('reserve'):
                    other = app.preview(replace(draft, client_request_id='second'), evidence, now=NOW).value
                    try:
                        app.confirm(confirmation(other), now=NOW)
                        raise AssertionError('Overreservation accepted')
                    except ExecutionRejected as exc:
                        expected = 'INSUFFICIENT_CASH' if scenario == 'cash-reserve' else 'INSUFFICIENT_SELLABLE'
                        assert exc.code == expected
                        outcome += ' / ' + exc.code
                elif scenario == 'reject':
                    assert history[-1] == 'SIMULATED_REJECTED'
            before = box.database.read_bytes()
            app = SimulationApplication(box)
            app.audit()
            assert app.verify().value['verified']
            assert before == box.database.read_bytes()
            app.confirm(confirmation(p), now=NOW)
            app.dispatch(p.preview_id, now=NOW)
            send = next(c for c in app.status(p.preview_id).value['commands'] if c['kind'] == 'SEND')
            assert send['mock_effects'] <= 1
            rows.append((scenario, ' → '.join(history), str(send['mock_effects']), outcome))
    return rows


def main():
    print('# M2A 實際模擬 smoke')
    print('\nsimulated=true; broker_connected=false; test_only=true; origin=SYNTHETIC\n')
    print('所有價格、額度、session、permission 均虛構；2330 僅為 UI 形狀測試代碼。\n')
    print('| 案例 | 實測狀態 | mock send 數 | 驗證 |')
    print('| --- | --- | ---: | --- |')
    for row in run():
        print('| ' + ' | '.join(row) + ' |')
    print('\n每例皆驗證 SQLite 重新開啟、audit 重放、讀取無寫入及確認／dispatch 去重。')
    print('此表沒有任何真 broker request；未部署，M2B 與 M3 BLOCKED。')


if __name__ == '__main__':
    main()
