from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, ProviderEvent
from app.observability.provider_fallback import observe_provider_fallback
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)


class ProviderFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _provider_error(self) -> ProviderHttpError:
        failure = ProviderHttpFailure(
            context=ProviderRequestContext(
                market="tw",
                provider="twse_mis",
                resource="intraday",
                target="2330",
            ),
            status="rate_limited",
            source_url="https://example.test/provider",
            http_status_code=429,
            rate_limited=True,
            retry_after_seconds=60,
            error_message="Provider request failed: HTTP 429.",
        )
        return ProviderHttpError(failure.error_message or "provider failed", failure=failure)

    def test_canonical_failure_is_persisted_with_an_independent_session(self) -> None:
        recorded = observe_provider_fallback(
            self._provider_error(),
            operation="intraday.primary",
            session_factory=self.session_factory,
        )

        with Session(self.engine) as db:
            event = db.query(ProviderEvent).one()

        self.assertTrue(recorded)
        self.assertEqual(event.event_type, "fallback")
        self.assertEqual(event.market, "tw")
        self.assertEqual(event.provider, "twse_mis")
        self.assertEqual(event.resource, "intraday")
        self.assertEqual(event.target, "2330")
        self.assertEqual(event.status, "rate_limited")
        self.assertEqual(event.http_status_code, 429)
        self.assertTrue(event.rate_limited)

    def test_unclassified_failure_is_logged_without_opening_a_session(self) -> None:
        session_factory = Mock(side_effect=AssertionError("session must not be opened"))

        with patch("app.observability.provider_fallback.logger.warning") as warning:
            recorded = observe_provider_fallback(
                ValueError("malformed payload"),
                operation="indices.parse",
                session_factory=session_factory,
            )

        self.assertFalse(recorded)
        session_factory.assert_not_called()
        warning.assert_called_once()

    def test_telemetry_failure_does_not_replace_the_market_fallback(self) -> None:
        db = Mock(spec=Session)
        session_factory = Mock(return_value=db)

        with (
            patch(
                "app.observability.provider_fallback.record_provider_event",
                side_effect=RuntimeError("database unavailable"),
            ),
            patch("app.observability.provider_fallback.logger.exception"),
        ):
            recorded = observe_provider_fallback(
                self._provider_error(),
                operation="indices.primary",
                session_factory=session_factory,
            )

        self.assertFalse(recorded)
        db.rollback.assert_called_once()
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
