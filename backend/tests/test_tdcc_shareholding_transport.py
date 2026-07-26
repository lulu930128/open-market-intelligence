from __future__ import annotations

import ssl
import unittest

from app.market import shareholding_history_backfill


class TdccShareholdingTransportTests(unittest.TestCase):
    def test_compatibility_context_keeps_certificate_verification_enabled(self) -> None:
        context = shareholding_history_backfill._tdcc_ssl_context()

        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict_flag:
            self.assertEqual(context.verify_flags & strict_flag, 0)


if __name__ == "__main__":
    unittest.main()
