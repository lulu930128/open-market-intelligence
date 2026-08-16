from __future__ import annotations

from collections import OrderedDict

from app.us_market.sec_fundamentals.contracts import CanonicalMetricSpec, MetricTag


def _us_gaap(*tags: str) -> tuple[MetricTag, ...]:
    return tuple(MetricTag(taxonomy="us-gaap", tag=tag) for tag in tags)


CANONICAL_METRICS: OrderedDict[str, CanonicalMetricSpec] = OrderedDict(
    (
        (
            "revenue",
            CanonicalMetricSpec(
                metric_code="revenue",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap(
                    "Revenues",
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "SalesRevenueNet",
                ),
                required=True,
            ),
        ),
        (
            "gross_profit",
            CanonicalMetricSpec(
                metric_code="gross_profit",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap("GrossProfit"),
                applicability="when_reported",
            ),
        ),
        (
            "operating_income",
            CanonicalMetricSpec(
                metric_code="operating_income",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap("OperatingIncomeLoss"),
            ),
        ),
        (
            "net_income",
            CanonicalMetricSpec(
                metric_code="net_income",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap("NetIncomeLoss", "ProfitLoss"),
                required=True,
            ),
        ),
        (
            "operating_cash_flow",
            CanonicalMetricSpec(
                metric_code="operating_cash_flow",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap("NetCashProvidedByUsedInOperatingActivities"),
            ),
        ),
        (
            "capex",
            CanonicalMetricSpec(
                metric_code="capex",
                statement_kind="duration",
                unit_kind="money",
                tags=_us_gaap("PaymentsToAcquirePropertyPlantAndEquipment"),
            ),
        ),
        (
            "assets",
            CanonicalMetricSpec(
                metric_code="assets",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap("Assets"),
            ),
        ),
        (
            "liabilities",
            CanonicalMetricSpec(
                metric_code="liabilities",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap("Liabilities"),
            ),
        ),
        (
            "equity",
            CanonicalMetricSpec(
                metric_code="equity",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap(
                    "StockholdersEquity",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                ),
            ),
        ),
        (
            "cash",
            CanonicalMetricSpec(
                metric_code="cash",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap(
                    "CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                ),
            ),
        ),
        (
            "debt_current",
            CanonicalMetricSpec(
                metric_code="debt_current",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap(
                    "DebtCurrent",
                    "ShortTermDebt",
                    "ShortTermBorrowings",
                    "CurrentPortionOfLongTermDebt",
                ),
            ),
        ),
        (
            "debt_noncurrent",
            CanonicalMetricSpec(
                metric_code="debt_noncurrent",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap(
                    "LongTermDebtAndCapitalLeaseObligations",
                    "LongTermDebtNoncurrent",
                    "LongTermDebt",
                ),
            ),
        ),
        (
            "debt_total",
            CanonicalMetricSpec(
                metric_code="debt_total",
                statement_kind="instant",
                unit_kind="money",
                tags=_us_gaap("DebtAndCapitalLeaseObligations"),
            ),
        ),
        (
            "eps_basic",
            CanonicalMetricSpec(
                metric_code="eps_basic",
                statement_kind="duration",
                unit_kind="per_share",
                tags=_us_gaap("EarningsPerShareBasic"),
            ),
        ),
        (
            "eps_diluted",
            CanonicalMetricSpec(
                metric_code="eps_diluted",
                statement_kind="duration",
                unit_kind="per_share",
                tags=_us_gaap("EarningsPerShareDiluted"),
            ),
        ),
        (
            "shares_outstanding",
            CanonicalMetricSpec(
                metric_code="shares_outstanding",
                statement_kind="instant",
                unit_kind="shares",
                tags=(MetricTag(taxonomy="dei", tag="EntityCommonStockSharesOutstanding"),),
            ),
        ),
    )
)


def get_metric_spec(metric_code: str) -> CanonicalMetricSpec:
    try:
        return CANONICAL_METRICS[metric_code]
    except KeyError as exc:
        raise KeyError(f"Unknown US SEC canonical metric: {metric_code}") from exc
