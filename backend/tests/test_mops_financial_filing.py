from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialParseRun,
    TaiwanFinancialParseRunReview,
    TaiwanFinancialStatementFact,
)
from app.market.financial_filing_ingestion import (
    ingest_mops_financial_filings,
    replay_stored_mops_financial_filings,
)
from app.market.financial_parse_runs import (
    get_canonical_parse_run,
    review_financial_parse_run,
)
from app.market.providers.mops_financial_filing import (
    FetchedMopsFinancialFiling,
    MopsDocumentRecord,
    MopsFinancialFetchBatch,
    fetch_mops_financial_filings,
    parse_document_index,
)
from app.parsers.mops_ixbrl import (
    MopsIxbrlParseError,
    decode_mops_html,
    parse_mops_ixbrl,
)


def _ixbrl_bytes() -> bytes:
    html = """\
<html>
<head><meta http-equiv="Content-Type" content="text/html; charset=big5"></head>
<body>
<xbrli:context id="From20260101To20260331">
  <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="From20250101To20250331">
  <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="AsOf20260331">
  <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
</xbrli:context>
<xbrli:context id="DimensionContext">
  <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
  <xbrli:scenario><xbrldi:explicitMember dimension="sample:Axis">sample:Member</xbrldi:explicitMember></xbrli:scenario>
</xbrli:context>
<xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
<xbrli:unit id="EarningsPerShare">
  <xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide>
</xbrli:unit>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20260101To20260331" unitRef="EarningsPerShare" scale="0" decimals="2">3.90</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20250101To20250331" unitRef="EarningsPerShare" scale="0" decimals="2">2.69</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="DimensionContext" unitRef="EarningsPerShare" scale="0" decimals="2">0.01</ix:nonFraction>
<ix:nonFraction name="ifrs-full:Revenue" contextRef="From20260101To20260331" unitRef="TWD" scale="3" decimals="-3">1,234,567</ix:nonFraction>
<ix:nonFraction name="ifrs-full:Assets" contextRef="AsOf20260331" unitRef="TWD" scale="3" decimals="-3">9,876,543</ix:nonFraction>
<ix:nonFraction name="tifrs-notes:NumberOfShares1" contextRef="AsOf20260331" unitRef="TWD" scale="0">2053044</ix:nonFraction>
</body>
</html>
"""
    return html.encode("cp950")


def _parsed_fixture():
    raw = _ixbrl_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    parsed = parse_mops_ixbrl(
        raw,
        stock_id="2327",
        fiscal_year=2026,
        fiscal_quarter=1,
        report_id="C",
        source_share_basis_id=f"2327:2026Q1:{content_hash[:16]}:presentation",
    )
    document = MopsDocumentRecord(
        stock_id="2327",
        fiscal_year=2026,
        fiscal_quarter=1,
        filename="202601_2327_AI1.pdf",
        uploaded_at=datetime(
            2026,
            5,
            15,
            14,
            25,
            9,
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        file_size_bytes=1_999_852,
        correction_status="無",
        registry_url="https://doc.twse.com.tw/example",
    )
    filing = FetchedMopsFinancialFiling(
        stock_id="2327",
        fiscal_year=2026,
        fiscal_quarter=1,
        report_id="C",
        ixbrl_url="https://mopsov.twse.com.tw/example",
        raw_bytes=raw,
        decoded_text=decode_mops_html(raw),
        content_type="text/html",
        content_hash=content_hash,
        fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        document=document,
        parsed=parsed,
    )
    return filing


def _q2_ixbrl_bytes() -> bytes:
    html = """\
<html>
<head><meta http-equiv="Content-Type" content="text/html; charset=big5"></head>
<body>
<xbrli:context id="From20260101To20260630">
  <xbrli:entity><xbrli:identifier>2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="From20260401To20260630">
  <xbrli:entity><xbrli:identifier>2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="From20250101To20250630">
  <xbrli:entity><xbrli:identifier>2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="From20250401To20250630">
  <xbrli:entity><xbrli:identifier>2327</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:unit id="EarningsPerShare">
  <xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide>
</xbrli:unit>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20260101To20260630" unitRef="EarningsPerShare" decimals="2">7.20</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20260401To20260630" unitRef="EarningsPerShare" decimals="2">3.30</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20250101To20250630" unitRef="EarningsPerShare" decimals="2">20.51</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20250401To20250630" unitRef="EarningsPerShare" decimals="2">9.74</ix:nonFraction>
</body>
</html>
"""
    return html.encode("cp950")


def _bank_q1_ixbrl_bytes() -> bytes:
    html = """\
<html>
<head><meta http-equiv="Content-Type" content="text/html; charset=big5"></head>
<body>
<xbrli:context id="From20250101To20250331">
  <xbrli:entity><xbrli:identifier>2801</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="From20240101To20240331">
  <xbrli:entity><xbrli:identifier>2801</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:unit id="EarningsPerShare">
  <xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide>
</xbrli:unit>
<table><tr><td><pre>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShareFromContinuingOperations" contextRef="From20250101To20250331" unitRef="EarningsPerShare" decimals="2">0.37</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShareFromContinuingOperations" contextRef="From20240101To20240331" unitRef="EarningsPerShare" decimals="2">0.34</ix:nonFraction>
</pre></td></tr><tr><td><pre>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20250101To20250331" unitRef="EarningsPerShare" decimals="2">0.37</ix:nonFraction>
<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="From20240101To20240331" unitRef="EarningsPerShare" decimals="2">0.34</ix:nonFraction>
</pre></td></tr></table>
</body>
</html>
"""
    return html.encode("cp950")


class MopsIxbrlParserTests(unittest.TestCase):
    def test_decodes_big5_and_selects_only_canonical_dimensionless_facts(self) -> None:
        parsed = _parsed_fixture().parsed

        self.assertEqual(parsed.stock_id, "2327")
        self.assertEqual(parsed.numeric_fact_count, 6)
        self.assertEqual(len(parsed.facts), 4)
        by_metric_role = {
            (fact.metric_code, fact.presentation_role): fact
            for fact in parsed.facts
        }
        self.assertEqual(
            by_metric_role[("basic_eps", "current_period")].source_value,
            Decimal("3.90"),
        )
        self.assertEqual(
            by_metric_role[("basic_eps", "comparative_period")].source_value,
            Decimal("2.69"),
        )
        self.assertEqual(
            by_metric_role[("revenue", "current_period")].source_value,
            Decimal("1234567"),
        )
        self.assertEqual(
            by_metric_role[("revenue", "current_period")].source_unit,
            "TWD_thousand",
        )
        self.assertEqual(
            by_metric_role[("total_assets", "current_period")].period_kind,
            "instant",
        )
        self.assertNotIn(
            "NumberOfShares1",
            {fact.source_label for fact in parsed.facts},
        )

    def test_q2_preserves_official_ytd_and_discrete_quarter_contexts(self) -> None:
        parsed = parse_mops_ixbrl(
            _q2_ixbrl_bytes(),
            stock_id="2327",
            fiscal_year=2026,
            fiscal_quarter=2,
            report_id="C",
            source_share_basis_id="2327:2026Q2:test:presentation",
        )

        eps = {
            (fact.presentation_role, fact.period_scope): fact
            for fact in parsed.facts
            if fact.metric_code == "basic_eps"
        }
        self.assertEqual(len(eps), 4)
        self.assertEqual(
            eps[("current_period", "ytd_6m")].source_value,
            Decimal("7.20"),
        )
        self.assertEqual(
            eps[("current_period", "discrete_3m")].source_value,
            Decimal("3.30"),
        )
        self.assertEqual(
            eps[("comparative_period", "ytd_6m")].source_value,
            Decimal("20.51"),
        )
        self.assertEqual(
            eps[("comparative_period", "discrete_3m")].source_value,
            Decimal("9.74"),
        )

    def test_preserves_dimensionless_issued_capital_as_instant_fact(self) -> None:
        raw = _ixbrl_bytes().replace(
            b"</body>",
            (
                b'<ix:nonFraction name="ifrs-full:IssuedCapital" '
                b'contextRef="AsOf20260331" unitRef="TWD" scale="3" '
                b'decimals="-3">12,578,524</ix:nonFraction></body>'
            ),
        )

        parsed = parse_mops_ixbrl(
            raw,
            stock_id="2327",
            fiscal_year=2026,
            fiscal_quarter=1,
            report_id="C",
            source_share_basis_id="2327:2026Q1:test:presentation",
        )

        issued_capital = [
            fact for fact in parsed.facts if fact.metric_code == "issued_capital"
        ]
        self.assertEqual(len(issued_capital), 1)
        self.assertEqual(
            issued_capital[0].source_value,
            Decimal("12578524"),
        )
        self.assertEqual(issued_capital[0].source_unit, "TWD_thousand")
        self.assertEqual(issued_capital[0].period_kind, "instant")
        self.assertEqual(issued_capital[0].period_scope, "instant_period_end")

    def test_bank_interim_table_keeps_total_eps_without_continuing_duplicate(
        self,
    ) -> None:
        parsed = parse_mops_ixbrl(
            _bank_q1_ixbrl_bytes(),
            stock_id="2801",
            fiscal_year=2025,
            fiscal_quarter=1,
            report_id="C",
            source_share_basis_id="2801:2025Q1:test:presentation",
        )

        eps = [
            fact
            for fact in parsed.facts
            if fact.metric_code == "basic_eps"
        ]
        self.assertEqual(len(eps), 2)
        self.assertEqual(
            {
                fact.presentation_role: fact.source_value
                for fact in eps
            },
            {
                "current_period": Decimal("0.37"),
                "comparative_period": Decimal("0.34"),
            },
        )
        self.assertTrue(
            all(
                "BasicEarningsLossPerShare|" in fact.fact_key
                for fact in eps
            )
        )

    def test_rejects_canonical_fact_with_missing_context(self) -> None:
        raw = _ixbrl_bytes().replace(
            b'contextRef="From20260101To20260331"',
            b'contextRef="MissingContext"',
            1,
        )
        with self.assertRaisesRegex(MopsIxbrlParseError, "unknown context"):
            parse_mops_ixbrl(
                raw,
                stock_id="2327",
                fiscal_year=2026,
                fiscal_quarter=1,
                report_id="C",
                source_share_basis_id="basis",
            )

    def test_document_index_uses_official_upload_time_and_ignores_english_pdf(
        self,
    ) -> None:
        html = """\
<html><head><meta charset="big5"></head><body><table>
<tr><td>2327</td><td>115 年 第一季</td><td>財務報告</td><td></td><td></td>
<td>IFRSs合併財報</td><td></td>
<td><a href='javascript:readfile2("A","2327","202601_2327_AI1.pdf");'>202601_2327_AI1.pdf</a></td>
<td>1,999,852</td><td>115/05/15 14:25:09</td><td>無</td></tr>
<tr><td>2327</td><td>115 年 第一季</td><td>財務報告</td><td></td><td></td>
<td>IFRSs英文版</td><td></td>
<td><a href='javascript:readfile2("A","2327","202601_2327_AIA.pdf");'>202601_2327_AIA.pdf</a></td>
<td>2,391,959</td><td>115/07/13 14:03:21</td><td>無</td></tr>
</table></body></html>
""".encode("cp950")

        records = parse_document_index(
            html,
            stock_id="2327",
            fiscal_year=2026,
            registry_url="https://doc.twse.com.tw/example",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].filename, "202601_2327_AI1.pdf")
        self.assertEqual(records[0].file_size_bytes, 1_999_852)
        self.assertEqual(records[0].uploaded_at.year, 2026)
        self.assertEqual(records[0].uploaded_at.tzinfo, ZoneInfo("Asia/Taipei"))

    def test_document_index_maps_individual_report_to_ai2_document(self) -> None:
        html = """\
<html><head><meta charset="big5"></head><body><table>
<tr><td>2867</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs個別財報</td><td></td>
<td><a href='javascript:readfile2("A","2867","202601_2867_AI2.pdf");'>202601_2867_AI2.pdf</a></td>
<td>2,224,561</td><td>115/05/15 18:29:22</td><td>無</td></tr>
<tr><td>2867</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs英文版-個別財報</td><td></td>
<td><a href='javascript:readfile2("A","2867","202601_2867_AIB.pdf");'>202601_2867_AIB.pdf</a></td>
<td>2,404,177</td><td>115/07/14 14:01:45</td><td>無</td></tr>
</table></body></html>
""".encode("cp950")

        records = parse_document_index(
            html,
            stock_id="2867",
            fiscal_year=2026,
            registry_url="https://doc.twse.com.tw/example",
            report_id="A",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].filename, "202601_2867_AI2.pdf")
        self.assertEqual(records[0].correction_status, "無")

    def test_auto_report_selects_one_consistent_individual_scope(self) -> None:
        index_response = Mock()
        index_response.content = """\
<html><head><meta charset="big5"></head><body><table>
<tr><td>3528</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs個別財報</td><td></td>
<td><a href='javascript:readfile2("A","3528","202601_3528_AI2.pdf");'>202601_3528_AI2.pdf</a></td>
<td>1,224,561</td><td>115/05/15 18:29:22</td><td>無</td></tr>
</table></body></html>
""".encode("cp950")
        index_response.raise_for_status.return_value = None
        ixbrl_response = Mock()
        ixbrl_response.content = _ixbrl_bytes().replace(b"2327", b"3528")
        ixbrl_response.headers = {"Content-Type": "text/html;charset=big5"}
        ixbrl_response.raise_for_status.return_value = None

        batch = fetch_mops_financial_filings(
            stock_id="3528",
            periods=[(2026, 1)],
            report_id="AUTO",
            request_get=Mock(side_effect=[index_response, ixbrl_response]),
        )

        self.assertEqual(batch.selected_report_id, "A")
        self.assertEqual(batch.filings[0].report_id, "A")
        self.assertEqual(
            batch.filings[0].document.filename,
            "202601_3528_AI2.pdf",
        )
        self.assertTrue(
            all(
                fact.consolidation_scope == "individual"
                for fact in batch.filings[0].parsed.facts
            )
        )

    def test_auto_report_refuses_to_mix_report_scopes_between_periods(self) -> None:
        index_response = Mock()
        index_response.content = """\
<html><head><meta charset="big5"></head><body><table>
<tr><td>9999</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs合併財報</td><td></td>
<td><a href='javascript:readfile2("A","9999","202601_9999_AI1.pdf");'>202601_9999_AI1.pdf</a></td>
<td>1,000</td><td>115/05/15 10:00:00</td><td>無</td></tr>
<tr><td>9999</td><td>115 年 第二季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs個別財報</td><td></td>
<td><a href='javascript:readfile2("A","9999","202602_9999_AI2.pdf");'>202602_9999_AI2.pdf</a></td>
<td>1,000</td><td>115/08/15 10:00:00</td><td>無</td></tr>
</table></body></html>
""".encode("cp950")
        index_response.raise_for_status.return_value = None

        with self.assertRaisesRegex(
            ValueError,
            "no single official report scope covers every requested period",
        ):
            fetch_mops_financial_filings(
                stock_id="9999",
                periods=[(2026, 1), (2026, 2)],
                report_id="AUTO",
                request_get=Mock(return_value=index_response),
            )

    def test_financial_holding_registry_followup_is_bounded(self) -> None:
        initial_response = Mock()
        initial_response.content = """\
<html><head><meta charset="big5"></head><body>
<form method="post"><input type="hidden" name="check2858" value="Y">
<input type="hidden" name="co_id" value="2881"></form>
</body></html>
""".encode("cp950")
        initial_response.raise_for_status.return_value = None

        followup_response = Mock()
        followup_response.content = """\
<html><head><meta charset="big5"></head><body><table>
<tr><td>2881</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td>
<td>IFRSs合併財報</td><td></td>
<td><a href='javascript:readfile2("A","2881","202601_2881_AI1.pdf");'>202601_2881_AI1.pdf</a></td>
<td>3,248,196</td><td>115/05/29 12:01:13</td><td>無</td></tr>
</table></body></html>
""".encode("cp950")
        followup_response.raise_for_status.return_value = None

        ixbrl_response = Mock()
        ixbrl_response.content = _ixbrl_bytes().replace(b"2327", b"2881")
        ixbrl_response.headers = {"Content-Type": "text/html;charset=big5"}
        ixbrl_response.raise_for_status.return_value = None
        request_get = Mock(side_effect=[initial_response, ixbrl_response])
        request_post = Mock(return_value=followup_response)

        batch = fetch_mops_financial_filings(
            stock_id="2881",
            periods=[(2026, 1)],
            report_id="C",
            request_get=request_get,
            request_post=request_post,
        )

        self.assertEqual(batch.request_count, 3)
        self.assertEqual(batch.request_limit, 3)
        self.assertEqual(batch.filings[0].document.filename, "202601_2881_AI1.pdf")
        self.assertEqual(
            request_post.call_args.kwargs["data"]["check2858"],
            "Y",
        )


class MopsFinancialFilingIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.filing = _parsed_fixture()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _fetcher(self, **_kwargs) -> MopsFinancialFetchBatch:
        return MopsFinancialFetchBatch(filings=(self.filing,), request_count=2)

    def test_dry_run_is_bounded_and_does_not_mutate_database(self) -> None:
        summary = ingest_mops_financial_filings(
            self.db,
            stock_id="2327",
            periods=[(2026, 1)],
            apply=False,
            fetcher=self._fetcher,
        )

        self.assertEqual(summary["mode"], "dry_run")
        self.assertEqual(summary["request_count"], 2)
        self.assertEqual(summary["request_limit"], 2)
        self.assertEqual(summary["filings_created"], 1)
        self.assertEqual(summary["facts_created"], 4)
        self.assertEqual(
            summary["documents"][0]["eps_facts"][0]["source_unit"],
            "TWD_per_share",
        )
        self.assertEqual(self.db.query(SourceRegistry).count(), 0)
        self.assertEqual(self.db.query(RawFetchResult).count(), 0)

    def test_apply_is_idempotent_and_preserves_official_known_at(self) -> None:
        first = ingest_mops_financial_filings(
            self.db,
            stock_id="2327",
            periods=[(2026, 1)],
            apply=True,
            fetcher=self._fetcher,
        )
        self.db.commit()
        second = ingest_mops_financial_filings(
            self.db,
            stock_id="2327",
            periods=[(2026, 1)],
            apply=True,
            fetcher=self._fetcher,
        )

        self.assertEqual(first["filings_created"], 1)
        self.assertEqual(first["parse_runs_created"], 1)
        self.assertEqual(first["facts_created"], 4)
        self.assertEqual(second["filings_reused"], 1)
        self.assertEqual(second["parse_runs_reused"], 1)
        self.assertEqual(second["facts_reused"], 4)
        self.assertEqual(self.db.query(RawFetchResult).count(), 1)
        self.assertEqual(self.db.query(TaiwanFinancialFiling).count(), 1)
        self.assertEqual(self.db.query(TaiwanFinancialParseRun).count(), 1)
        self.assertEqual(self.db.query(TaiwanFinancialStatementFact).count(), 4)
        parse_run = self.db.query(TaiwanFinancialParseRun).one()
        self.assertEqual(parse_run.review_status, "pending")
        self.assertIsNone(
            get_canonical_parse_run(self.db, filing_id=parse_run.filing_id)
        )
        review = review_financial_parse_run(
            self.db,
            parse_run_id=parse_run.id,
            expected_output_hash=parse_run.output_hash or "",
            reviewer="test-reviewer",
            apply=True,
            reviewed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(review["decision"], "approved")
        self.assertIsNotNone(review["review_event_id"])
        self.assertEqual(
            self.db.query(TaiwanFinancialParseRunReview).count(),
            1,
        )
        repeated_review = review_financial_parse_run(
            self.db,
            parse_run_id=parse_run.id,
            expected_output_hash=parse_run.output_hash or "",
            reviewer="test-reviewer",
            apply=True,
            reviewed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        self.assertFalse(repeated_review["changed"])
        self.assertEqual(
            self.db.query(TaiwanFinancialParseRunReview).count(),
            1,
        )
        self.assertEqual(
            get_canonical_parse_run(self.db, filing_id=parse_run.filing_id).id,
            parse_run.id,
        )
        stored = self.db.query(TaiwanFinancialFiling).one()
        self.assertEqual(stored.source_document_id, "202601_2327_AI1.pdf")
        self.assertEqual(stored.known_at.year, 2026)
        self.assertEqual(stored.known_at.month, 5)
        self.assertEqual(stored.known_at.hour, 6)
        self.assertEqual(stored.known_at.minute, 25)
        self.assertIsNone(stored.announced_at)

    def test_stored_raw_replay_is_network_free_and_idempotent(self) -> None:
        ingest_mops_financial_filings(
            self.db,
            stock_id="2327",
            periods=[(2026, 1)],
            apply=True,
            fetcher=self._fetcher,
        )
        self.db.commit()
        filing = self.db.query(TaiwanFinancialFiling).one()

        first = replay_stored_mops_financial_filings(
            self.db,
            filing_ids=[filing.id],
            apply=True,
        )
        second = replay_stored_mops_financial_filings(
            self.db,
            filing_ids=[filing.id],
            apply=True,
        )

        self.assertEqual(first["parse_runs_reused"], 1)
        self.assertEqual(first["facts_reused"], 4)
        self.assertEqual(second["parse_runs_reused"], 1)
        self.assertEqual(self.db.query(TaiwanFinancialParseRun).count(), 1)

    def test_caller_rollback_removes_all_ingestion_rows(self) -> None:
        ingest_mops_financial_filings(
            self.db,
            stock_id="2327",
            periods=[(2026, 1)],
            apply=True,
            fetcher=self._fetcher,
        )
        self.db.rollback()

        self.assertEqual(self.db.query(SourceRegistry).count(), 0)
        self.assertEqual(self.db.query(TaiwanFinancialFiling).count(), 0)
        self.assertEqual(self.db.query(TaiwanFinancialStatementFact).count(), 0)


if __name__ == "__main__":
    unittest.main()
