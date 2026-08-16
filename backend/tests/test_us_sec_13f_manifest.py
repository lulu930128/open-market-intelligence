from __future__ import annotations

import unittest

from app.us_market.errors import USMarketDataFetchError
from app.us_market.ownership_13f_manifest import parse_13f_manifest_html


BASE_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"


class USSec13FManifestTests(unittest.TestCase):
    def test_manifest_parser_normalizes_current_legacy_and_transition_periods(self) -> None:
        html = """
        <a href="/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip">
          2026 March April May 13F
        </a>
        <a href="/files/structureddata/data/form-13f-data-sets/01jan2024-29feb2024_form13f.zip">
          2024 January February 13F
        </a>
        <a href="/files/structureddata/data/form-13f-data-sets/2023q4_form13f.zip">
          2023 Q4 13F
        </a>
        <a href="https://example.test/not-sec.zip">ignore me</a>
        """

        entries = parse_13f_manifest_html(html, base_url=BASE_URL)

        self.assertEqual(
            [entry.period_key for entry in entries],
            ["2026Q1", "2024JANFEB", "2023Q4"],
        )
        self.assertEqual(entries[0].source_window_start, "2026-03-01")
        self.assertEqual(entries[0].source_window_end, "2026-05-31")
        self.assertTrue(entries[0].source_url.startswith("https://www.sec.gov/"))

    def test_manifest_parser_rejects_empty_or_duplicate_period_identity(self) -> None:
        with self.assertRaisesRegex(USMarketDataFetchError, "no data-set archives"):
            parse_13f_manifest_html("<html></html>", base_url=BASE_URL)

        html = """
        <a href="/files/structureddata/data/form-13f-data-sets/2023q4_form13f.zip">Q4</a>
        <a href="/files/structureddata/data/form-13f-data-sets/copy/2023q4_form13f.zip">Q4 copy</a>
        """
        with self.assertRaisesRegex(USMarketDataFetchError, "duplicate period keys"):
            parse_13f_manifest_html(html, base_url=BASE_URL)


if __name__ == "__main__":
    unittest.main()
