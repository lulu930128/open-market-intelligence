from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USSecCompanyFact, USStockMaster
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)
from app.routers.us_market import router as us_market_router
from app.us_market.fundamentals_store import upsert_us_sec_fact_records
from app.us_market.providers.sec_policy import SecRequestPolicy
from app.us_market.sec_fundamentals import (
    CanonicalFact,
    DerivedValue,
    PeriodResolution,
    SecFact,
    derive_discrete_quarters,
    derive_pair_metric,
    derive_ttm,
    evaluate_sec_filing_freshness,
    get_metric_spec,
    resolve_period,
    resolve_unit,
    select_canonical_fact,
    select_canonical_history,
)
from app.us_market.sec_fundamentals.submissions import (
    SEC_SUBMISSIONS_CACHE,
    SecSubmissionsCache,
    parse_sec_submissions,
)
from app.us_market.schemas import (
    USSecFinancialContractRead,
    USSecFundamentalSummaryRead,
)
from app.us_market.service import (
    get_us_sec_financial_contract,
    get_us_sec_fundamental_summary,
    refresh_us_sec_companyfacts,
)
from app.us_market.sources import parse_sec_companyfacts


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "us_sec"
    / "aapl_companyfacts_periods_minimal.json"
)
SOURCE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
SUBMISSIONS_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "us_sec" / "aapl_submissions_minimal.json"
)
SUBMISSIONS_SOURCE_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
REVENUE_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _load_companyfacts_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fact(**overrides) -> SecFact:
    values = {
        "fact_id": "fact-1",
        "cik": "0000723125",
        "taxonomy": "us-gaap",
        "tag": REVENUE_TAG,
        "unit": "USD",
        "value_text": "100",
        "fiscal_year": 2026,
        "fiscal_period": "Q2",
        "form": "10-Q",
        "filed_date": date(2026, 4, 1),
        "period_start_date": date(2025, 11, 28),
        "period_end_date": date(2026, 2, 26),
        "accession_number": "0000723125-26-000001",
    }
    values.update(overrides)
    return SecFact(**values)


def _canonical_fact(
    *,
    metric_code: str,
    fiscal_year: int,
    fiscal_quarter: int,
    scope: str,
    value: str,
    period_end: date,
    fact_id: str,
    unit: str = "USD",
) -> CanonicalFact:
    return CanonicalFact(
        metric_code=metric_code,
        source_fact=_fact(
            fact_id=fact_id,
            fiscal_year=fiscal_year,
            fiscal_period="FY" if fiscal_quarter == 4 else f"Q{fiscal_quarter}",
            form="10-K" if fiscal_quarter == 4 else "10-Q",
            period_end_date=period_end,
            value_text=value,
            unit=unit,
        ),
        value=Decimal(value),
        period=PeriodResolution(
            statement_kind="duration",
            scope=scope,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_start=None,
            period_end=period_end,
            duration_days={
                "ytd_3m": 91,
                "discrete_3m": 91,
                "ytd_6m": 182,
                "ytd_9m": 273,
                "annual_12m": 364,
            }[scope],
            status="ready",
            issue_codes=(),
        ),
        unit=resolve_unit(unit),
        revision_kind="as_reported",
    )


def _derived_value(
    *,
    metric_code: str,
    value: str,
    fact_id: str,
    period_end: date = date(2026, 3, 28),
    unit: str = "USD",
    fiscal_year: int = 2026,
    fiscal_quarter: int = 2,
) -> DerivedValue:
    return DerivedValue(
        metric_code=metric_code,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_end=period_end,
        value=Decimal(value),
        unit=unit,
        status="ready",
        derivation="direct",
        formula=None,
        input_fact_ids=(fact_id,),
        issue_codes=(),
    )


class USSecFundamentalEngineStage0Tests(unittest.TestCase):
    def setUp(self) -> None:
        SEC_SUBMISSIONS_CACHE.clear()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        SEC_SUBMISSIONS_CACHE.clear()
        self.db.close()
        self.engine.dispose()

    def _fixture_records(self):
        return parse_sec_companyfacts(
            _load_companyfacts_fixture(),
            symbol="AAPL",
            source_url=SOURCE_URL,
        )

    def test_parser_preserves_discrete_and_ytd_facts_with_same_period_end(self) -> None:
        records = [
            record
            for record in self._fixture_records()
            if record.tag == REVENUE_TAG
            and record.period_end_date == date(2026, 3, 28)
        ]

        self.assertEqual(len(records), 2)
        self.assertEqual(
            {record.period_start_date for record in records},
            {date(2025, 9, 28), date(2025, 12, 28)},
        )
        self.assertEqual(
            {record.value_text for record in records},
            {"254940000000", "111184000000"},
        )
        self.assertEqual(len({record.fact_key for record in records}), 2)

    def test_raw_store_preserves_later_filing_comparative_accession(self) -> None:
        result = upsert_us_sec_fact_records(self.db, self._fixture_records())

        revisions = (
            self.db.query(USSecCompanyFact)
            .filter(USSecCompanyFact.symbol == "AAPL")
            .filter(USSecCompanyFact.tag == REVENUE_TAG)
            .filter(USSecCompanyFact.period_start_date == date(2024, 12, 29))
            .filter(USSecCompanyFact.period_end_date == date(2025, 3, 29))
            .order_by(USSecCompanyFact.filed_date.asc())
            .all()
        )

        self.assertEqual(result, {"inserted_count": 4, "updated_count": 0})
        self.assertEqual(len(revisions), 2)
        self.assertEqual(
            [revision.accession_number for revision in revisions],
            ["0000320193-25-000057", "0000320193-26-000013"],
        )
        self.assertEqual(len({revision.fact_key for revision in revisions}), 2)

    def test_legacy_fundamental_summary_response_shape_remains_compatible(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc. - Common Stock",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000320193",
                sec_company_name="Apple Inc.",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_us_sec_fact_records(self.db, self._fixture_records())

        summary = get_us_sec_fundamental_summary(self.db, symbol="aapl")
        validated = USSecFundamentalSummaryRead.model_validate(summary).model_dump()

        self.assertEqual(
            set(validated),
            {"symbol", "cik", "entity_name", "metric_count", "metrics"},
        )
        self.assertEqual(validated["symbol"], "AAPL")
        self.assertEqual(validated["cik"], "0000320193")
        self.assertEqual(validated["metric_count"], 1)
        self.assertEqual(
            set(validated["metrics"][0]),
            {
                "metric",
                "tag",
                "label",
                "unit",
                "value_numeric",
                "value_text",
                "fiscal_year",
                "fiscal_period",
                "form",
                "filed_date",
                "period_start_date",
                "period_end_date",
                "accession_number",
                "source_url",
            },
        )

    def test_versioned_financial_contract_is_additive_and_read_only(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc. - Common Stock",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000320193",
                sec_company_name="Apple Inc.",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_us_sec_fact_records(self.db, self._fixture_records())

        with (
            patch("app.us_market.service.fetch_sec_companyfacts_payload") as facts_fetch,
            patch("app.us_market.service.fetch_sec_submissions_payload") as submissions_fetch,
        ):
            contract = get_us_sec_financial_contract(
                self.db,
                symbol="aapl",
                periods=4,
            )

        parsed = USSecFinancialContractRead.model_validate(contract)
        self.assertEqual(parsed.contract_version, "omi.financial.v1")
        self.assertEqual(parsed.target["market"], "US")
        self.assertEqual(parsed.target["cik"], "0000320193")
        self.assertIn("revenue", parsed.normalized["metrics"])
        self.assertIn("revenue", parsed.derived["quarterly"])
        self.assertFalse(parsed.quality.decision_usable)
        facts_fetch.assert_not_called()
        submissions_fetch.assert_not_called()

    def test_as_reported_as_of_is_explicitly_blocked_without_history_store(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000320193",
                is_active=True,
            )
        )
        self.db.commit()

        contract = get_us_sec_financial_contract(
            self.db,
            symbol="AAPL",
            mode="as_reported_as_of",
            periods=4,
        )

        self.assertEqual(contract["normalized"]["status"], "blocked")
        self.assertIn(
            "as_reported_history_not_available",
            contract["quality"]["issues"],
        )

    def test_refresh_skips_companyfacts_when_latest_accession_already_matches(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000320193",
                sec_company_name="Apple Inc.",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_us_sec_fact_records(self.db, self._fixture_records())

        with (
            patch(
                "app.us_market.service.fetch_sec_submissions_payload",
                return_value=(
                    json.loads(SUBMISSIONS_FIXTURE_PATH.read_text(encoding="utf-8")),
                    SUBMISSIONS_SOURCE_URL,
                ),
            ),
            patch("app.us_market.service.fetch_sec_companyfacts_payload") as facts_fetch,
            patch(
                "app.us_market.service.settings.us_sec_user_agent",
                "OMI test contact@example.com",
            ),
        ):
            result = refresh_us_sec_companyfacts(self.db, symbol="AAPL")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fetched_count"], 0)
        self.assertEqual(
            result["latest_local_accession_number"],
            result["latest_remote_accession_number"],
        )
        self.assertEqual(result["freshness"]["basis"], "submissions_accession")
        self.assertFalse(result["submissions_cache_persisted"])
        facts_fetch.assert_not_called()

    def test_financials_route_has_versioned_response_model(self) -> None:
        route = next(
            route
            for route in us_market_router.routes
            if getattr(route, "path", None) == "/sec/{symbol}/financials"
        )

        self.assertEqual(route.methods, {"GET"})
        self.assertIs(route.response_model, USSecFinancialContractRead)


class USSecFundamentalPeriodResolutionTests(unittest.TestCase):
    def test_real_fixture_distinguishes_discrete_quarter_from_ytd(self) -> None:
        facts = [
            SecFact.from_raw(record)
            for record in parse_sec_companyfacts(
                _load_companyfacts_fixture(),
                symbol="AAPL",
                source_url=SOURCE_URL,
            )
            if record.period_end_date == date(2026, 3, 28)
        ]

        resolutions = {
            fact.period_start_date: resolve_period(fact, statement_kind="duration")
            for fact in facts
        }

        self.assertEqual(resolutions[date(2025, 12, 28)].scope, "discrete_3m")
        self.assertEqual(resolutions[date(2025, 12, 28)].duration_days, 91)
        self.assertEqual(resolutions[date(2025, 9, 28)].scope, "ytd_6m")
        self.assertEqual(resolutions[date(2025, 9, 28)].duration_days, 182)

    def test_non_calendar_fiscal_quarter_uses_fp_not_calendar_month(self) -> None:
        resolution = resolve_period(_fact(), statement_kind="duration")

        self.assertEqual(resolution.status, "ready")
        self.assertEqual(resolution.scope, "discrete_3m")
        self.assertEqual(resolution.fiscal_quarter, 2)
        self.assertEqual(resolution.duration_days, 91)

    def test_53_week_annual_and_instant_periods_are_supported(self) -> None:
        annual = resolve_period(
            _fact(
                fiscal_period="FY",
                form="10-K",
                period_start_date=date(2024, 9, 1),
                period_end_date=date(2025, 8, 30),
            ),
            statement_kind="duration",
        )
        instant = resolve_period(
            _fact(
                tag="Assets",
                fiscal_period="FY",
                form="10-K",
                period_start_date=None,
                period_end_date=date(2025, 8, 28),
            ),
            statement_kind="instant",
        )

        self.assertEqual(annual.scope, "annual_12m")
        self.assertEqual(annual.duration_days, 364)
        self.assertEqual(annual.status, "ready")
        self.assertEqual(instant.scope, "instant")
        self.assertEqual(instant.status, "ready")

    def test_q3_ytd_period_is_identified_by_duration(self) -> None:
        resolution = resolve_period(
            _fact(
                fiscal_period="Q3",
                period_start_date=date(2025, 8, 29),
                period_end_date=date(2026, 5, 28),
            ),
            statement_kind="duration",
        )

        self.assertEqual(resolution.status, "ready")
        self.assertEqual(resolution.scope, "ytd_9m")
        self.assertEqual(resolution.fiscal_quarter, 3)

    def test_ambiguous_duration_is_blocked(self) -> None:
        resolution = resolve_period(
            _fact(period_end_date=date(2026, 4, 6)),
            statement_kind="duration",
        )

        self.assertEqual(resolution.status, "blocked")
        self.assertEqual(resolution.scope, "ambiguous")
        self.assertIn("ambiguous_duration", resolution.issue_codes)

    def test_fiscal_period_duration_mismatch_is_blocked(self) -> None:
        resolution = resolve_period(
            _fact(
                fiscal_period="Q1",
                period_start_date=date(2025, 8, 29),
                period_end_date=date(2026, 2, 26),
            ),
            statement_kind="duration",
        )

        self.assertEqual(resolution.status, "blocked")
        self.assertIn("fiscal_period_duration_mismatch", resolution.issue_codes)


class USSecFundamentalUnitResolutionTests(unittest.TestCase):
    def test_companyfacts_units_are_normalized_without_float_conversion(self) -> None:
        money = resolve_unit("USD")
        per_share = resolve_unit("USD/shares")

        self.assertEqual((money.kind, money.currency), ("money", "USD"))
        self.assertEqual(
            (per_share.kind, per_share.normalized_unit, per_share.currency),
            ("per_share", "USD/shares", "USD"),
        )

    def test_unknown_unit_is_explicitly_blocked(self) -> None:
        resolution = resolve_unit("USD-per-shares")

        self.assertEqual(resolution.status, "blocked")
        self.assertEqual(resolution.issue_codes, ("unsupported_unit",))


class USSecFundamentalCandidateSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = [
            SecFact.from_raw(record)
            for record in parse_sec_companyfacts(
                _load_companyfacts_fixture(),
                symbol="AAPL",
                source_url=SOURCE_URL,
            )
        ]
        cls.revenue_spec = get_metric_spec("revenue")

    def test_duration_selection_requires_scope_when_latest_end_is_ambiguous(self) -> None:
        selection = select_canonical_fact(self.facts, spec=self.revenue_spec)

        self.assertEqual(selection.status, "blocked")
        self.assertIsNone(selection.selected)
        self.assertIn("ambiguous_period_scope", selection.issue_codes)

    def test_discrete_and_ytd_selection_are_deterministic(self) -> None:
        discrete = select_canonical_fact(
            self.facts,
            spec=self.revenue_spec,
            period_end=date(2026, 3, 28),
            period_scope="discrete_3m",
        )
        ytd = select_canonical_fact(
            self.facts,
            spec=self.revenue_spec,
            period_end=date(2026, 3, 28),
            period_scope="ytd_6m",
        )

        self.assertEqual(discrete.status, "ready")
        self.assertEqual(discrete.selected.value, 111184000000)
        self.assertEqual(ytd.status, "ready")
        self.assertEqual(ytd.selected.value, 254940000000)

    def test_later_comparative_filing_is_not_mislabeled_as_amendment(self) -> None:
        selection = select_canonical_fact(
            self.facts,
            spec=self.revenue_spec,
            period_end=date(2025, 3, 29),
            period_scope="discrete_3m",
        )

        self.assertEqual(selection.status, "ready")
        self.assertEqual(
            selection.selected.source_fact.accession_number,
            "0000320193-26-000013",
        )
        self.assertEqual(selection.selected.revision_kind, "later_filing")
        self.assertEqual(selection.selected.period.fiscal_year, 2025)
        self.assertEqual(selection.selected.source_fact.fiscal_year, 2026)

    def test_form_amendment_is_selected_as_formal_amendment(self) -> None:
        original = _fact(fiscal_period="Q1", fact_id="original")
        amendment = replace(
            original,
            fact_id="amendment",
            form="10-Q/A",
            filed_date=date(2026, 4, 10),
            accession_number="0000723125-26-000002",
            value_text="101",
        )

        selection = select_canonical_fact(
            [original, amendment],
            spec=self.revenue_spec,
            period_scope="ytd_3m",
        )

        self.assertEqual(selection.status, "ready")
        self.assertEqual(selection.selected.value, 101)
        self.assertEqual(selection.selected.revision_kind, "amendment")

    def test_mixed_currency_without_expected_currency_is_disputed(self) -> None:
        usd = _fact(fiscal_period="Q1", fact_id="usd")
        eur = replace(usd, fact_id="eur", unit="EUR")

        selection = select_canonical_fact(
            [usd, eur],
            spec=self.revenue_spec,
            period_scope="ytd_3m",
            expected_currency=None,
        )

        self.assertEqual(selection.status, "disputed")
        self.assertIsNone(selection.selected)
        self.assertIn("mixed_currencies", selection.issue_codes)

    def test_old_out_of_scope_failure_does_not_degrade_latest_period(self) -> None:
        current = _fact(fiscal_period="Q1", fact_id="current")
        old_unsupported = replace(
            current,
            fact_id="old-unsupported",
            form="8-K",
            period_start_date=date(2024, 8, 30),
            period_end_date=date(2024, 11, 28),
        )

        selection = select_canonical_fact(
            [old_unsupported, current],
            spec=self.revenue_spec,
            period_scope="ytd_3m",
        )

        self.assertEqual(selection.status, "ready")
        self.assertEqual(selection.selected.source_fact.fact_id, "current")
        self.assertNotIn("unsupported_form", selection.issue_codes)

    def test_history_selects_each_economic_period_and_scope(self) -> None:
        history = select_canonical_history(
            self.facts,
            spec=self.revenue_spec,
        )

        self.assertEqual(len(history), 3)
        self.assertEqual(
            [item.selected.period.scope for item in history],
            ["discrete_3m", "discrete_3m", "ytd_6m"],
        )
        self.assertEqual(history[0].selected.period.fiscal_year, 2025)


class USSecFundamentalDerivedEngineTests(unittest.TestCase):
    def _fiscal_2025_facts(self) -> list[CanonicalFact]:
        return [
            _canonical_fact(
                metric_code="revenue",
                fiscal_year=2025,
                fiscal_quarter=1,
                scope="ytd_3m",
                value="100",
                period_end=date(2024, 11, 30),
                fact_id="revenue-2025-q1-ytd",
            ),
            _canonical_fact(
                metric_code="revenue",
                fiscal_year=2025,
                fiscal_quarter=2,
                scope="ytd_6m",
                value="220",
                period_end=date(2025, 2, 28),
                fact_id="revenue-2025-q2-ytd",
            ),
            _canonical_fact(
                metric_code="revenue",
                fiscal_year=2025,
                fiscal_quarter=3,
                scope="ytd_9m",
                value="360",
                period_end=date(2025, 5, 31),
                fact_id="revenue-2025-q3-ytd",
            ),
            _canonical_fact(
                metric_code="revenue",
                fiscal_year=2025,
                fiscal_quarter=4,
                scope="annual_12m",
                value="500",
                period_end=date(2025, 8, 30),
                fact_id="revenue-2025-fy",
            ),
        ]

    def test_ytd_and_annual_subtraction_produce_four_discrete_quarters(self) -> None:
        quarters = derive_discrete_quarters(
            self._fiscal_2025_facts(),
            metric_code="revenue",
        )

        self.assertEqual([item.value for item in quarters], [100, 120, 140, 140])
        self.assertEqual(
            [item.derivation for item in quarters],
            ["direct", "ytd_subtraction", "ytd_subtraction", "annual_subtraction"],
        )
        self.assertEqual(
            quarters[3].input_fact_ids,
            ("revenue-2025-fy", "revenue-2025-q3-ytd"),
        )

    def test_direct_quarter_conflict_is_disputed_instead_of_silently_preferred(self) -> None:
        facts = [
            *self._fiscal_2025_facts(),
            _canonical_fact(
                metric_code="revenue",
                fiscal_year=2025,
                fiscal_quarter=2,
                scope="discrete_3m",
                value="121",
                period_end=date(2025, 2, 28),
                fact_id="revenue-2025-q2-direct",
            ),
        ]

        quarters = derive_discrete_quarters(facts, metric_code="revenue")
        q2 = next(item for item in quarters if item.fiscal_quarter == 2)

        self.assertEqual(q2.status, "disputed")
        self.assertIsNone(q2.value)
        self.assertIn("direct_derived_value_conflict", q2.issue_codes)

    def test_ttm_requires_four_consecutive_ready_quarters(self) -> None:
        quarters = derive_discrete_quarters(
            [
                *self._fiscal_2025_facts(),
                _canonical_fact(
                    metric_code="revenue",
                    fiscal_year=2026,
                    fiscal_quarter=1,
                    scope="ytd_3m",
                    value="110",
                    period_end=date(2025, 11, 29),
                    fact_id="revenue-2026-q1-ytd",
                ),
            ],
            metric_code="revenue",
        )

        ttm = derive_ttm(quarters, metric_code="revenue")
        missing = derive_ttm(
            [item for item in quarters if item.fiscal_quarter != 3],
            metric_code="revenue",
        )

        self.assertEqual(ttm.status, "ready")
        self.assertEqual(ttm.value, 510)
        self.assertEqual(ttm.fiscal_year, 2026)
        self.assertEqual(ttm.fiscal_quarter, 1)
        self.assertEqual(missing.status, "blocked")
        self.assertIn("ttm_period_missing", missing.issue_codes)

    def test_fcf_margin_growth_and_net_debt_preserve_lineage(self) -> None:
        revenue = _derived_value(
            metric_code="revenue",
            value="1000",
            fact_id="revenue",
        )
        operating_income = _derived_value(
            metric_code="operating_income",
            value="250",
            fact_id="operating-income",
        )
        operating_cash_flow = _derived_value(
            metric_code="operating_cash_flow",
            value="400",
            fact_id="ocf",
        )
        capex = _derived_value(
            metric_code="capex",
            value="120",
            fact_id="capex",
        )
        previous_revenue = _derived_value(
            metric_code="revenue",
            value="800",
            fact_id="previous-revenue",
            period_end=date(2025, 3, 29),
            fiscal_year=2025,
        )
        debt = _derived_value(metric_code="debt_total", value="900", fact_id="debt")
        cash = _derived_value(metric_code="cash", value="300", fact_id="cash")

        fcf = derive_pair_metric(
            metric_code="free_cash_flow",
            left=operating_cash_flow,
            right=capex,
            operation="subtract",
        )
        margin = derive_pair_metric(
            metric_code="operating_margin",
            left=operating_income,
            right=revenue,
            operation="margin_percent",
        )
        growth = derive_pair_metric(
            metric_code="revenue_yoy_growth",
            left=revenue,
            right=replace(previous_revenue, period_end=revenue.period_end),
            operation="growth_percent",
        )
        net_debt = derive_pair_metric(
            metric_code="net_debt",
            left=debt,
            right=cash,
            operation="subtract",
        )

        self.assertEqual(fcf.value, 280)
        self.assertEqual(margin.value, 25)
        self.assertEqual(growth.value, 25)
        self.assertEqual(net_debt.value, 600)
        self.assertEqual(fcf.input_fact_ids, ("ocf", "capex"))

    def test_zero_denominator_and_period_mismatch_are_blocked(self) -> None:
        numerator = _derived_value(metric_code="net_income", value="10", fact_id="net")
        zero = _derived_value(metric_code="revenue", value="0", fact_id="zero")
        other_period = _derived_value(
            metric_code="capex",
            value="1",
            fact_id="capex",
            period_end=date(2025, 12, 27),
        )

        margin = derive_pair_metric(
            metric_code="net_margin",
            left=numerator,
            right=zero,
            operation="margin_percent",
        )
        fcf = derive_pair_metric(
            metric_code="free_cash_flow",
            left=numerator,
            right=other_period,
            operation="subtract",
        )

        self.assertEqual(margin.status, "blocked")
        self.assertIn("zero_denominator", margin.issue_codes)
        self.assertEqual(fcf.status, "blocked")
        self.assertIn("derived_period_mismatch", fcf.issue_codes)


class USSecRequestPolicyTests(unittest.TestCase):
    def _provider_error(
        self,
        *,
        status: str,
        http_status_code: int,
        retry_after_seconds: int | None = None,
    ) -> ProviderHttpError:
        failure = ProviderHttpFailure(
            context=ProviderRequestContext(
                market="us",
                provider="sec_edgar",
                resource="sec_submissions",
                target="0000320193",
            ),
            status=status,
            source_url=SUBMISSIONS_SOURCE_URL,
            http_status_code=http_status_code,
            rate_limited=status == "rate_limited",
            retry_after_seconds=retry_after_seconds,
        )
        return ProviderHttpError("SEC request failed", failure=failure)

    def test_rate_limit_retries_once_and_honors_bounded_retry_after(self) -> None:
        delays: list[float] = []
        attempts = 0
        policy = SecRequestPolicy(
            min_interval_seconds=0,
            max_attempts=2,
            max_retry_after_seconds=5,
            sleep=delays.append,
        )

        def request():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise self._provider_error(
                    status="rate_limited",
                    http_status_code=429,
                    retry_after_seconds=2,
                )
            return "ok"

        self.assertEqual(policy.execute(request), "ok")
        self.assertEqual(attempts, 2)
        self.assertEqual(delays, [2.0])

    def test_blocked_or_long_retry_after_does_not_retry(self) -> None:
        for error in (
            self._provider_error(status="blocked", http_status_code=403),
            self._provider_error(
                status="rate_limited",
                http_status_code=429,
                retry_after_seconds=30,
            ),
        ):
            attempts = 0
            policy = SecRequestPolicy(
                min_interval_seconds=0,
                max_attempts=2,
                max_retry_after_seconds=5,
                sleep=lambda _seconds: None,
            )

            def request():
                nonlocal attempts
                attempts += 1
                raise error

            with self.assertRaises(ProviderHttpError):
                policy.execute(request)
            self.assertEqual(attempts, 1)

    def test_default_interval_targets_at_most_four_requests_per_second(self) -> None:
        self.assertGreaterEqual(SecRequestPolicy().min_interval_seconds, 0.25)


class USSecSubmissionsFreshnessTests(unittest.TestCase):
    def test_submissions_parser_selects_latest_relevant_xbrl_filing(self) -> None:
        snapshot = parse_sec_submissions(
            json.loads(SUBMISSIONS_FIXTURE_PATH.read_text(encoding="utf-8")),
            source_url=SUBMISSIONS_SOURCE_URL,
            fetched_at=datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(snapshot.cik, "0000320193")
        self.assertEqual(len(snapshot.filings), 2)
        self.assertEqual(
            snapshot.latest_relevant_filing.accession_number,
            "0000320193-26-000013",
        )
        self.assertTrue(snapshot.latest_relevant_filing.is_xbrl)

    def test_submissions_cache_survives_process_memory_reset(self) -> None:
        snapshot = parse_sec_submissions(
            json.loads(SUBMISSIONS_FIXTURE_PATH.read_text(encoding="utf-8")),
            source_url=SUBMISSIONS_SOURCE_URL,
            fetched_at=datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc),
        )
        cache_path = (
            FIXTURE_PATH.parents[4]
            / ".tmp"
            / f"us_sec_submissions_test_{os.getpid()}.json"
        )
        try:
            writer = SecSubmissionsCache()
            self.assertTrue(writer.put(snapshot, cache_path=cache_path))

            reader = SecSubmissionsCache()
            restored = reader.get("320193", cache_path=cache_path)
        finally:
            cache_path.unlink(missing_ok=True)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.cik, "0000320193")
        self.assertEqual(
            restored.latest_relevant_filing.accession_number,
            "0000320193-26-000013",
        )
        self.assertEqual(restored.fetched_at, snapshot.fetched_at)

    def test_freshness_compares_remote_and_local_accessions(self) -> None:
        checked_at = datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc)
        current = evaluate_sec_filing_freshness(
            local_accession_number="0000320193-26-000013",
            local_filing_date=date(2026, 5, 1),
            local_fetched_at=checked_at,
            expected_accession_number="0000320193-26-000013",
            expected_filing_date=date(2026, 5, 1),
            last_checked_at=checked_at,
            now=checked_at + timedelta(hours=2),
        )
        stale = evaluate_sec_filing_freshness(
            local_accession_number="0000320193-25-000057",
            local_filing_date=date(2025, 5, 2),
            local_fetched_at=checked_at,
            expected_accession_number="0000320193-26-000013",
            expected_filing_date=date(2026, 5, 1),
            last_checked_at=checked_at,
            now=checked_at + timedelta(hours=2),
        )

        self.assertEqual(current.status, "current")
        self.assertTrue(current.decision_usable)
        self.assertEqual(stale.status, "stale")
        self.assertIn("newer_sec_filing_available", stale.issue_codes)

    def test_fetch_age_fallback_becomes_stale_without_recent_submissions_check(self) -> None:
        fetched_at = datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc)
        freshness = evaluate_sec_filing_freshness(
            local_accession_number="0000320193-26-000013",
            local_filing_date=date(2026, 5, 1),
            local_fetched_at=fetched_at,
            now=fetched_at + timedelta(hours=25),
        )

        self.assertEqual(freshness.status, "stale")
        self.assertFalse(freshness.decision_usable)
        self.assertIn("sec_facts_refresh_overdue", freshness.issue_codes)


if __name__ == "__main__":
    unittest.main()
