import re

from app.db.models import RawFetchResult
from app.parsers.twse_common import (
    coalesce_int,
    diff_nullable,
    first_value,
    list_row_to_dict,
    load_json_payload,
    normalize_text,
    parse_int,
    payload_trade_date,
    sum_nullable,
)


def _is_stock_like_id(stock_id: str | None) -> bool:
    return bool(stock_id and re.search(r"[0-9A-Za-z]", stock_id))


def parse_twse_institutional_trade_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payload = load_json_payload(raw_result.raw_text, "TWSE T86")
    fields = payload.get("fields") or payload.get("Field") or []
    data = payload.get("data") or payload.get("Data") or []

    if not isinstance(data, list):
        raise ValueError("TWSE T86 data field should be a list.")

    trade_date = payload_trade_date(payload, raw_result)
    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in data:
        if isinstance(row, list):
            row_dict = list_row_to_dict(fields, row)
        elif isinstance(row, dict):
            row_dict = row
        else:
            skipped_count += 1
            continue

        stock_id = first_value(row_dict, ["證券代號", "股票代號", "stock_id", "Code", "code"])

        if not _is_stock_like_id(stock_id):
            skipped_count += 1
            continue

        stock_name = first_value(row_dict, ["證券名稱", "股票名稱", "stock_name", "Name", "name"])

        foreign_investor_buy = parse_int(
            first_value(
                row_dict,
                [
                    "外陸資買進股數(不含外資自營商)",
                    "外資及陸資買進股數(不含外資自營商)",
                ],
            )
        )
        foreign_investor_sell = parse_int(
            first_value(
                row_dict,
                [
                    "外陸資賣出股數(不含外資自營商)",
                    "外資及陸資賣出股數(不含外資自營商)",
                ],
            )
        )
        foreign_investor_net = coalesce_int(
            parse_int(
                first_value(
                    row_dict,
                    [
                        "外陸資買賣超股數(不含外資自營商)",
                        "外資及陸資買賣超股數(不含外資自營商)",
                    ],
                )
            ),
            diff_nullable(foreign_investor_buy, foreign_investor_sell),
        )

        foreign_dealer_buy = parse_int(first_value(row_dict, ["外資自營商買進股數"]))
        foreign_dealer_sell = parse_int(first_value(row_dict, ["外資自營商賣出股數"]))
        foreign_dealer_net = coalesce_int(
            parse_int(first_value(row_dict, ["外資自營商買賣超股數"])),
            diff_nullable(foreign_dealer_buy, foreign_dealer_sell),
        )

        investment_trust_buy = parse_int(first_value(row_dict, ["投信買進股數"]))
        investment_trust_sell = parse_int(first_value(row_dict, ["投信賣出股數"]))
        investment_trust_net = coalesce_int(
            parse_int(first_value(row_dict, ["投信買賣超股數"])),
            diff_nullable(investment_trust_buy, investment_trust_sell),
        )

        dealer_self_buy = parse_int(first_value(row_dict, ["自營商買進股數(自行買賣)"]))
        dealer_self_sell = parse_int(first_value(row_dict, ["自營商賣出股數(自行買賣)"]))
        dealer_self_net = coalesce_int(
            parse_int(first_value(row_dict, ["自營商買賣超股數(自行買賣)"])),
            diff_nullable(dealer_self_buy, dealer_self_sell),
        )

        dealer_hedge_buy = parse_int(first_value(row_dict, ["自營商買進股數(避險)"]))
        dealer_hedge_sell = parse_int(first_value(row_dict, ["自營商賣出股數(避險)"]))
        dealer_hedge_net = coalesce_int(
            parse_int(first_value(row_dict, ["自營商買賣超股數(避險)"])),
            diff_nullable(dealer_hedge_buy, dealer_hedge_sell),
        )

        dealer_buy = sum_nullable(dealer_self_buy, dealer_hedge_buy)
        dealer_sell = sum_nullable(dealer_self_sell, dealer_hedge_sell)
        dealer_net = coalesce_int(
            parse_int(first_value(row_dict, ["自營商買賣超股數"])),
            sum_nullable(dealer_self_net, dealer_hedge_net),
        )

        total_institutional_net = coalesce_int(
            parse_int(first_value(row_dict, ["三大法人買賣超股數"])),
            sum_nullable(foreign_investor_net, investment_trust_net, dealer_net),
        )

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "trade_date": trade_date,
                "stock_id": stock_id.strip(),
                "stock_name": normalize_text(stock_name),
                "foreign_investor_buy": foreign_investor_buy,
                "foreign_investor_sell": foreign_investor_sell,
                "foreign_investor_net": foreign_investor_net,
                "foreign_dealer_buy": foreign_dealer_buy,
                "foreign_dealer_sell": foreign_dealer_sell,
                "foreign_dealer_net": foreign_dealer_net,
                "investment_trust_buy": investment_trust_buy,
                "investment_trust_sell": investment_trust_sell,
                "investment_trust_net": investment_trust_net,
                "dealer_self_buy": dealer_self_buy,
                "dealer_self_sell": dealer_self_sell,
                "dealer_self_net": dealer_self_net,
                "dealer_hedge_buy": dealer_hedge_buy,
                "dealer_hedge_sell": dealer_hedge_sell,
                "dealer_hedge_net": dealer_hedge_net,
                "dealer_buy": dealer_buy,
                "dealer_sell": dealer_sell,
                "dealer_net": dealer_net,
                "total_institutional_net": total_institutional_net,
            }
        )

    return parsed_rows, skipped_count
