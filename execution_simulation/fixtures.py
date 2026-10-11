"""UI-shaped symbol with entirely invented M1 values; no market/account access."""

from dataclasses import replace

from execution.tests.fixtures import fixture


def symbol_fixture(symbol='2330', **kwargs):
    draft, evidence = fixture(**kwargs)
    instrument = replace(draft.instrument, symbol=symbol)
    return replace(draft, instrument=instrument), replace(
        evidence, market=replace(evidence.market, instrument=instrument),
        account=replace(evidence.account, instrument=instrument),
        permission=replace(evidence.permission, instrument=instrument),
    )
