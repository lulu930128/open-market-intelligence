"""Canonical client surface. Confirmation is workflow selection, not auth/2FA."""

from execution.validation import require
from .contracts import BrokerKey
from .us_contracts import UsBrokerKey
from .review import Draft
from .strategy import SourceSnapshot, StrategyRules


class ExecutionApplication:
    """Thin application facade over the one ExecutionRuntime transaction owner.

    Clients receive this surface, not the internal engine/session. There is no
    raw submit route. Constructor and local reads perform no broker IO.
    """

    def __init__(self, runtime):
        self._runtime = runtime

    def draft(self, draft: Draft):
        return self._runtime.create_review(draft)

    def desk_submit(self, order, selection):
        return self._runtime.desk_submit(order, selection)

    def desk_order(self, market, execution_id):
        return self._runtime.desk_order(market, execution_id)

    def desk_cancel(self, market, execution_id):
        return self._runtime.desk_cancel(market, execution_id)

    def desk_protection(self, market, execution_id, rules, request_id, expected_revision):
        return self._runtime.desk_protection(market, execution_id, rules, request_id, expected_revision)

    def preview(self, review_id, *, expected_revision):
        return self._runtime.preview_review(review_id, expected_revision=expected_revision)

    def revise(self, review_id, draft: Draft, *, expected_revision):
        return self._runtime.revise_review(review_id, draft, expected_revision=expected_revision)

    def reject(self, review_id, *, expected_revision, reason="USER_REJECTED"):
        return self._runtime.reject_review(review_id, expected_revision=expected_revision, reason=reason)

    def prepare_candidate(self, draft, binding):
        return self._runtime.prepare_candidate(draft, binding)

    def confirm(self, review_id, *, expected_digest, expected_revision, candidate_selection=None):
        return self._runtime.confirm_review(review_id, expected_digest=expected_digest,
                                            expected_revision=expected_revision, candidate_selection=candidate_selection)

    def list(self):
        return self._runtime.list_reviews()

    def status(self, review_id):
        return self._runtime.review_status(review_id)

    def query(self):
        return self._runtime.query()

    def readback(self):
        return self._runtime.readback()

    def manual_us_order(self, **parameters):
        return self._runtime.manual_us_order(**parameters)

    def manual_us_status(self, request_id=None):
        return self._runtime.manual_us_status(request_id)

    def manual_us_cancel(self, request_id):
        return self._runtime.manual_us_cancel(request_id)

    def cancel(self, execution_id, key: BrokerKey):
        require(type(key) in {BrokerKey, UsBrokerKey}, "INVALID_BROKER_KEY")
        return self._runtime.cancel(execution_id, key)

    def create_strategy(self, review_id, rules: StrategyRules, source: SourceSnapshot, *, expected_digest):
        return self._runtime.create_strategy(review_id, rules, source, expected_digest=expected_digest)

    def strategy_status(self, strategy_id):
        return self._runtime.strategy_status(strategy_id)

    def revise_strategy(self, strategy_id, rules: StrategyRules, source: SourceSnapshot, *,
                        request_id, expected_revision):
        return self._runtime.revise_strategy(strategy_id, rules, source, request_id=request_id,
                                             expected_revision=expected_revision)

    def exit_strategy(self, strategy_id, source: SourceSnapshot, *, request_id, expected_revision,
                      target_position=0):
        return self._runtime.exit_strategy(strategy_id, source, request_id=request_id,
                                           expected_revision=expected_revision, target_position=target_position)

    def observe_strategy_price(self, strategy_id, source: SourceSnapshot, *, request_id,
                               expected_revision, symbol, price):
        return self._runtime.observe_strategy_price(strategy_id, source, request_id=request_id,
            expected_revision=expected_revision, symbol=symbol, price=price)
