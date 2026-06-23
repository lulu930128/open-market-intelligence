from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.dispatch import templates as dispatch_templates
from app.db.models import Base
from app.dispatch import service as dispatch_service
from app.dispatch.mail_sender import MailSenderConfigurationError
from app.dispatch.schemas import (
    DispatchPreviewRequest,
    DispatchRecipientGroupCreate,
    DispatchSendRequest,
)


@contextmanager
def dispatch_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _recipient_group(db: Session):
    return dispatch_service.create_recipient_group(
        db=db,
        payload=DispatchRecipientGroupCreate(
            name="test recipients",
            emails=["USER@example.com", "user@example.com", "second@example.com"],
        ),
    )


def _market_send_payload(group_id: int) -> DispatchSendRequest:
    return DispatchSendRequest(
        recipient_group_id=group_id,
        template_key="market_overview",
        scope_type="market",
    )


class FakeSender:
    def send(self, *, recipients, subject, body_text, body_html):
        return {
            "sent_count": len(list(recipients)),
            "requested_count": len(list(recipients)),
            "subject": subject,
            "body_text_length": len(body_text),
            "body_html_length": len(body_html),
        }


class DispatchTests(unittest.TestCase):
    def test_recipient_group_normalizes_and_dedupes_emails(self) -> None:
        with dispatch_db_session() as db:
            group = _recipient_group(db)

        self.assertEqual(group["emails"], ["user@example.com", "second@example.com"])
        self.assertTrue(group["enabled"])

    def test_recipient_group_rejects_invalid_email(self) -> None:
        with dispatch_db_session() as db:
            with self.assertRaises(dispatch_service.DispatchValidationError):
                dispatch_service.create_recipient_group(
                    db=db,
                    payload=DispatchRecipientGroupCreate(
                        name="bad recipients",
                        emails=["not-an-email"],
                    ),
                )

    def test_market_preview_works_without_smtp_configuration(self) -> None:
        with dispatch_db_session() as db:
            preview = dispatch_service.build_preview(
                db=db,
                payload=DispatchPreviewRequest(
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                ),
            )

        self.assertEqual(preview["template_key"], "market_overview")
        self.assertIn("台股大盤總覽", preview["subject"])
        self.assertIn("資料限制", preview["body_text"])
        self.assertIn("市場廣度", preview["body_text"])
        self.assertIn("成交值焦點", preview["body_text"])
        self.assertIn("<!doctype html>", preview["body_html"])
        self.assertIn('role="presentation"', preview["body_html"])
        self.assertIn('width="1080"', preview["body_html"])
        self.assertIn("OPEN MARKET INTELLIGENCE", preview["body_html"])
        self.assertIn("市場結構", preview["body_html"])
        self.assertIn("成交值焦點", preview["body_html"])
        self.assertIn('width="50%"', preview["body_html"])

    def test_us_market_preview_uses_watchlist_intraday_ranking(self) -> None:
        ranking_payload = {
            "requested_symbol_count": 3,
            "ranked_count": 3,
            "no_data_count": 0,
            "trade_date": "2026-06-22",
            "target_trade_date": "2026-06-22",
            "is_current": True,
            "current_symbol_count": 3,
            "stale_symbol_count": 0,
            "results": [
                {
                    "symbol": "NVDA",
                    "security_name": "NVIDIA Corporation",
                    "time": "2026-06-22T14:35:00Z",
                    "close": 141.25,
                    "change_pct": 3.2,
                    "volume": 120000000,
                    "status": "intraday",
                    "source": "yahoo_chart",
                },
                {
                    "symbol": "AAPL",
                    "security_name": "Apple Inc.",
                    "time": "2026-06-22T14:35:00Z",
                    "close": 202.5,
                    "change_pct": 0.4,
                    "volume": 48000000,
                    "status": "intraday",
                    "source": "yahoo_chart",
                },
                {
                    "symbol": "TSLA",
                    "security_name": "Tesla Inc.",
                    "trade_date": "2026-06-22",
                    "close": 300.1,
                    "change_pct": -1.7,
                    "volume": 72000000,
                    "status": "ready",
                },
            ],
        }
        with dispatch_db_session() as db, patch.object(
            dispatch_templates.us_market_service,
            "get_us_watchlist_ranking",
            return_value=ranking_payload,
        ):
            preview = dispatch_service.build_preview(
                db=db,
                payload=DispatchPreviewRequest(
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="us",
                ),
            )

        self.assertEqual(preview["scope_id"], "us")
        self.assertIn("美股自選股即時總覽", preview["subject"])
        self.assertIn("盤中覆蓋", preview["body_text"])
        self.assertIn("NVDA NVIDIA Corporation", preview["body_text"])
        self.assertIn("即時結構", preview["body_html"])
        self.assertIn("盤中 / yahoo_chart", preview["body_html"])
        self.assertEqual(preview["metadata"]["breadth"]["intraday_count"], 2)

    def test_send_delivery_records_error_when_smtp_is_not_configured(self) -> None:
        with dispatch_db_session() as db:
            group = _recipient_group(db)
            payload = _market_send_payload(group["id"])
            preview = dispatch_service.build_preview(db=db, payload=payload)
            delivery = dispatch_service.create_delivery(
                db=db,
                payload=payload,
                preview=preview,
                recipient_group=dispatch_service.get_recipient_group(db, group["id"]),
            )

            with (
                patch.object(
                    dispatch_service.SmtpMailSender,
                    "from_settings",
                    side_effect=MailSenderConfigurationError("missing smtp"),
                ),
                self.assertRaises(MailSenderConfigurationError),
            ):
                dispatch_service.send_delivery(db=db, delivery_id=delivery.id)

            db.refresh(delivery)
            self.assertEqual(delivery.status, "error")
            self.assertEqual(delivery.error_message, "missing smtp")

    def test_send_delivery_records_success(self) -> None:
        with dispatch_db_session() as db:
            group = _recipient_group(db)
            payload = _market_send_payload(group["id"])
            preview = dispatch_service.build_preview(db=db, payload=payload)
            delivery = dispatch_service.create_delivery(
                db=db,
                payload=payload,
                preview=preview,
                recipient_group=dispatch_service.get_recipient_group(db, group["id"]),
            )
            serialized = dispatch_service.serialize_delivery(delivery)

            self.assertIn("台股大盤總覽", serialized["body_text"])
            self.assertIn("OPEN MARKET INTELLIGENCE", serialized["body_html"])
            self.assertEqual(serialized["preview"]["template_key"], "market_overview")

            with patch.object(
                dispatch_service.SmtpMailSender,
                "from_settings",
                return_value=FakeSender(),
            ):
                result = dispatch_service.send_delivery(db=db, delivery_id=delivery.id)

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["recipient_count"], 2)
            db.refresh(delivery)
            self.assertEqual(delivery.status, "success")
            self.assertIsNotNone(delivery.sent_at)


if __name__ == "__main__":
    unittest.main()
