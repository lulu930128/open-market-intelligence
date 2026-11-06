"""Headless command parser over ExecutionApplication; no runtime/session factory."""

import argparse
import json
from dataclasses import replace

from .contracts import BrokerKey
from .review import draft_from
from .strategy import SourceSnapshot, StrategyRules


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("INVALID_JSON_NUMBER")


def json_value(value):
    try:
        return json.loads(value, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except json.JSONDecodeError:
        raise ValueError("INVALID_JSON") from None


def _draft(value, selected_account=None):
    draft = draft_from(json_value(value))
    if selected_account is not None:
        if draft.command.account_id != "SELECTED":
            raise ValueError("SELECTED_ACCOUNT_ALIAS_REQUIRED")
        draft = replace(draft, command=replace(draft.command, account_id=selected_account))
    return draft


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes untrusted input in stderr.
        raise ValueError("INVALID_CLI_ARGUMENTS")


def parser():
    result = CommandParser(description="ExecutionApplication commands", add_help=False)
    routes = result.add_subparsers(dest="route", required=True)
    desk = routes.add_parser("desk-submit")
    desk.add_argument("--order-json", required=True)
    desk.add_argument("--selection-json", required=True)
    for name in ("desk-order", "desk-cancel", "desk-protection"):
        desk = routes.add_parser(name)
        desk.add_argument("--market", choices=("TW", "US"), required=True)
        desk.add_argument("--execution-id", required=True)
        if name == "desk-protection":
            desk.add_argument("--rules-json", required=True)
            desk.add_argument("--request-id", required=True)
            desk.add_argument("--expected-revision", type=int, required=True)
    routes.add_parser("draft").add_argument("--draft-json", required=True)
    candidate = routes.add_parser("candidate-prepare")
    candidate.add_argument("--draft-json", required=True)
    candidate.add_argument("--binding-json", required=True)
    for name in ("preview", "revise", "reject", "confirm"):
        route = routes.add_parser(name)
        route.add_argument("review_id")
        route.add_argument("--expected-revision", type=int, required=True)
        if name == "revise":
            route.add_argument("--draft-json", required=True)
        if name == "confirm":
            route.add_argument("--expected-digest", required=True)
            route.add_argument("--candidate-selection-json")
        if name == "reject":
            route.add_argument("--reason", default="USER_REJECTED")
    routes.add_parser("list")
    routes.add_parser("status").add_argument("review_id")
    routes.add_parser("query")
    route = routes.add_parser("cancel")
    for name in ("execution-id", "account-id", "trade-date", "broker-order-id"):
        route.add_argument("--" + name, required=True)
    for name in ("strategy-create", "strategy-revise", "strategy-exit", "strategy-price", "strategy-status"):
        route = routes.add_parser(name, add_help=False)
        route.add_argument("identity")
        if name == "strategy-status":
            continue
        route.add_argument("--source-json", required=True)
        if name in {"strategy-create", "strategy-revise"}:
            route.add_argument("--rules-json", required=True)
        if name == "strategy-create":
            route.add_argument("--expected-digest", required=True)
        else:
            route.add_argument("--request-id", required=True)
            route.add_argument("--expected-revision", type=int, required=True)
        if name == "strategy-exit":
            route.add_argument("--target-position", type=int, default=0)
        if name == "strategy-price":
            route.add_argument("--symbol", required=True)
            route.add_argument("--price", required=True)
    return result


def run(application, argv, *, selected_account=None):
    args = parser().parse_args(argv)
    if args.route == "desk-submit":
        return application.desk_submit(json_value(args.order_json), json_value(args.selection_json))
    if args.route in {"desk-order", "desk-cancel"}:
        return getattr(application, args.route.replace("-", "_"))(args.market, args.execution_id)
    if args.route == "desk-protection":
        return application.desk_protection(args.market, args.execution_id, json_value(args.rules_json), args.request_id, args.expected_revision)
    if args.route == "draft":
        return application.draft(_draft(args.draft_json, selected_account))
    if args.route == "candidate-prepare":
        return application.prepare_candidate(_draft(args.draft_json, selected_account), json_value(args.binding_json))
    if args.route == "list":
        return application.list()
    if args.route == "status":
        return application.status(args.review_id)
    if args.route == "query":
        return application.query()
    if args.route == "cancel":
        if selected_account is not None and args.account_id != "SELECTED":
            raise ValueError("SELECTED_ACCOUNT_ALIAS_REQUIRED")
        return application.cancel(args.execution_id, BrokerKey(selected_account or args.account_id, args.trade_date,
                                                              args.broker_order_id))
    if args.route.startswith("strategy-"):
        if args.route == "strategy-status":
            return application.strategy_status(args.identity)
        source = SourceSnapshot(**json_value(args.source_json))
        source.validate()
        if args.route in {"strategy-create", "strategy-revise"}:
            rules = StrategyRules(**json_value(args.rules_json))
            rules.validate()
        if args.route == "strategy-create":
            return application.create_strategy(args.identity, rules, source, expected_digest=args.expected_digest)
        kwargs = {"request_id": args.request_id, "expected_revision": args.expected_revision}
        if args.route == "strategy-revise":
            return application.revise_strategy(args.identity, rules, source, **kwargs)
        if args.route == "strategy-exit":
            return application.exit_strategy(args.identity, source, target_position=args.target_position, **kwargs)
        return application.observe_strategy_price(args.identity, source, symbol=args.symbol, price=args.price, **kwargs)
    kwargs = {"expected_revision": args.expected_revision}
    if args.route == "preview":
        return application.preview(args.review_id, **kwargs)
    if args.route == "revise":
        return application.revise(args.review_id, _draft(args.draft_json, selected_account), **kwargs)
    if args.route == "reject":
        return application.reject(args.review_id, reason=args.reason, **kwargs)
    if args.candidate_selection_json is not None:
        kwargs["candidate_selection"] = json_value(args.candidate_selection_json)
    return application.confirm(args.review_id, expected_digest=args.expected_digest, **kwargs)
