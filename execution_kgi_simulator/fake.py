"""Closed local SDK-shaped fixture, never evidence about a broker account."""

from enum import Enum
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class FixtureQuantityUnits:
    """Invented LOCAL_MOCK units, never sanctioned SDK/broker proof."""
    order: int
    query: int
    modified_quantity: int
    deal: int


class Action(Enum):
    Buy = 'B'
    Sell = 'S'


class TimeInForce(Enum):
    ROD = 0


class OrderCond(Enum):
    CASH = 0


class OddLot(Enum):
    Common = 0


class PriceType(Enum):
    MKT = '1'


class FakeOrder:
    def __init__(self, assert_outside_transaction):
        self.check = assert_outside_transaction
        self.calls = []
        self.callback = None
        self.scenario = 'Pending'
        self.query_scenario = 'Empty'
        self.cancel_scenario = 'Pending'

    def set_event(self, event):
        self.callback = event

    def create_order(self, action, symbol, qty, price=None, time_in_force=TimeInForce.ROD,
                     order_cond=OrderCond.CASH, odd_lot=False, name=''):
        self.check()
        self.calls.append('SEND')
        if self.scenario == 'Timeout':
            raise TimeoutError('fixture only')
        return SimpleNamespace(task='NewOrder', status='Pending', order_id=None)

    def get_trades(self, full=False):
        self.check()
        assert full is True
        self.calls.append('QUERY')
        if self.query_scenario == 'Timeout':
            raise TimeoutError('fixture only')
        return {}  # Absence never proves no order.

    def cancel_order(self, order_id):
        self.check()
        assert order_id == 'LOCAL-ORDER'
        self.calls.append('CANCEL')
        if self.cancel_scenario == 'Timeout':
            raise TimeoutError('fixture only')
        return SimpleNamespace(task='CancelOrder', status='Pending', order_id=order_id)


class FakeSDK:
    Action, TimeInForce, OrderCond, OddLot, PriceType = Action, TimeInForce, OrderCond, OddLot, PriceType

    def __init__(self, check=lambda: None):
        self.Order = FakeOrder(check)
        self.quantity_units = FixtureQuantityUnits(1000, 1000, 1000, 1000)
        self.logins = 0
        self.logouts = 0

    def login(self, person_id=None, person_pwd=None, simulation: bool = True):
        assert simulation is True
        assert person_id == 'fixture-person' and person_pwd == 'fixture-password'
        self.logins += 1
        return self

    def logout(self):
        self.logouts += 1
