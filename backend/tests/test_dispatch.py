from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, DispatchDelivery
from app.dispatch import templates as dispatch_templates
from app.dispatch import service as dispatch_service
from app.dispatch.mail_sender import MailSenderConfigurationError
from app.dispatch.schemas import (
    DispatchPreviewRequest,
    DispatchRecipientGroupCreate,
    DispatchScheduleCreate,
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


def _watchlist_row(
    stock_id: str,
    name: str,
    *,
    change_pct: float,
    score: float,
    bucket: str,
    bucket_label: str,
    action_label: str,
    reason: str,
    signal_labels: list[str],
) -> dict:
    return {
        "stock_id": stock_id,
        "stock_name": name,
        "label": f"{stock_id} {name}",
        "bucket": bucket,
        "bucket_label": bucket_label,
        "urgency": "high",
        "action_label": action_label,
        "reason": reason,
        "trade_date": "2026-06-30",
        "time": "2026-06-30",
        "close": 100,
        "change_pct": change_pct,
        "score": score,
        "status": bucket,
        "signal_labels": signal_labels,
        "matched_signal_keys": [bucket],
        "primary_signal_label": signal_labels[0],
        "stale": False,
    }


def _watchlist_brief_envelope() -> dict:
    radar_rows = [
        _watchlist_row(
            "2330",
            "台積電",
            change_pct=2.4,
            score=88,
            bucket="breakout_high",
            bucket_label="突破前高",
            action_label="追蹤突破延續",
            reason="突破前高且量能放大",
            signal_labels=["突破", "放量"],
        ),
        _watchlist_row(
            "2303",
            "聯電",
            change_pct=5.7,
            score=72,
            bucket="surge_up",
            bucket_label="急漲",
            action_label="等回測",
            reason="急漲後等待回測",
            signal_labels=["動能延續"],
        ),
        _watchlist_row(
            "2454",
            "聯發科",
            change_pct=-2.1,
            score=-30,
            bucket="risk",
            bucket_label="風險",
            action_label="優先檢查風控",
            reason="主要訊號：動能轉弱",
            signal_labels=["動能轉弱"],
        ),
    ]
    return {
        "kind": "watchlist_brief",
        "as_of": "2026-06-30",
        "warnings": ["Watchlist context uses local daily indicator data."],
        "missing": ["broker_branch_daily"],
        "data": {
            "overview": {
                "kind": "watchlist_sector_overview",
                "group_name": "科技股",
                "as_of": "2026-06-30",
                "display": "科技股結構偏多；上漲 2、下跌 1。",
                "stance": "結構偏多",
                "confidence": "medium",
                "human_answer": {
                    "lines": [
                        "結論：科技股結構偏多；上漲 2、下跌 1。",
                        "雷達：3 檔命中；優先看 2330 台積電。",
                    ],
                    "text": "結論：科技股結構偏多；上漲 2、下跌 1。",
                },
                "breadth": {
                    "requested_stock_count": 3,
                    "ranked_count": 3,
                    "up_count": 2,
                    "down_count": 1,
                    "no_data_count": 0,
                    "stale_stock_count": 0,
                    "average_change_pct": 2.0,
                    "average_change_pct_text": "+2.00%",
                },
                "radar": {
                    "mode": "all",
                    "matched_count": 3,
                    "radar_count": 3,
                    "trade_date": "2026-06-30",
                    "target_trade_date": "2026-06-30",
                    "is_current": True,
                    "stale_stock_count": 0,
                    "buckets": [
                        {"key": "breakout_high", "label": "突破前高", "count": 1},
                        {"key": "surge_up", "label": "急漲", "count": 1},
                        {"key": "risk", "label": "風險", "count": 1},
                    ],
                    "results": radar_rows,
                },
                "radar_rows": radar_rows,
                "follow_rows": [radar_rows[0]],
                "pullback_rows": [radar_rows[1]],
                "defensive_rows": [radar_rows[2]],
                "strong_rows": [radar_rows[0], radar_rows[1]],
                "weak_rows": [radar_rows[2]],
            }
        },
    }


def _market_overview_envelope_with_industry_codes() -> dict:
    return {
        "kind": "market_overview",
        "as_of": "2026-06-30",
        "warnings": [],
        "missing": [],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
        "data": {
            "latest_trade_date": "2026-06-30",
            "breadth": {
                "advance_count": 120,
                "decline_count": 80,
                "unchanged_count": 10,
                "total_count": 210,
                "trade_value": 123_000_000_000,
                "positive_ratio": 120 / 200,
                "average_change_pct": 1.2,
                "advance_decline_ratio": 1.5,
                "top_value_share": 0.42,
            },
            "distribution": {
                "limit_up_count": 3,
                "limit_down_count": 1,
                "strong_up_count": 12,
                "strong_down_count": 4,
            },
            "top_gainers": [],
            "top_losers": [],
            "value_leaders": [
                {
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "change_pct": 3.94,
                    "close_price": 2505,
                    "trade_value": 93_600_000_000,
                    "industry": "24",
                }
            ],
            "top_industries": [
                {
                    "industry": 28,
                    "advance_count": 5,
                    "decline_count": 2,
                    "average_change_pct": 2.89,
                    "trade_value": 26_400_000_000,
                    "top_stock_id": "1815",
                    "top_stock_name": "富喬",
                }
            ],
            "weak_industries": [
                {
                    "industry": "31",
                    "advance_count": 1,
                    "decline_count": 4,
                    "average_change_pct": -1.5,
                    "trade_value": 18_800_000_000,
                    "top_stock_id": "2345",
                    "top_stock_name": "智邦",
                }
            ],
        },
    }


class FakeSender:
    def send(self, *, recipients, subject, body_text, body_html):
        return {
            "sent_count": len(list(recipients)),
            "requested_count": len(list(recipients)),
            "subject": subject,
            "body_text_length": len(body_text),
            "body_html_length": len(body_html),
        }


def _fake_enqueue_job(
    db: Session,
    *,
    job_type: str,
    target: str | None = None,
    request=None,
    progress_total: int = 1,
    message: str | None = None,
    **_kwargs,
):
    job = dispatch_service.job_service.create_job(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=progress_total,
        message=message,
    )
    return job, True


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
        self.assertIn("今日看點", preview["body_text"])
        self.assertIn("圖表摘要", preview["body_text"])
        self.assertIn("研究檢查清單", preview["body_text"])
        self.assertIn("市場廣度", preview["body_text"])
        self.assertIn("成交值焦點", preview["body_text"])
        self.assertIn("<!doctype html>", preview["body_html"])
        self.assertIn('role="presentation"', preview["body_html"])
        self.assertIn('width="1360"', preview["body_html"])
        self.assertIn("OPEN MARKET INTELLIGENCE", preview["body_html"])
        self.assertIn("今日看點", preview["body_html"])
        self.assertIn("圖表摘要", preview["body_html"])
        self.assertIn("市場結構", preview["body_html"])
        self.assertIn("成交值焦點", preview["body_html"])
        self.assertIn('width="50%"', preview["body_html"])

    def test_market_preview_formats_numeric_industry_codes(self) -> None:
        with dispatch_db_session() as db, patch.object(
            dispatch_templates.tools,
            "read_market_overview",
            return_value=_market_overview_envelope_with_industry_codes(),
        ):
            preview = dispatch_service.build_preview(
                db=db,
                payload=DispatchPreviewRequest(
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                ),
            )

        self.assertIn("半導體業", preview["body_text"])
        self.assertIn("電子零組件業", preview["body_text"])
        self.assertIn("其他電子業", preview["body_text"])
        self.assertIn("半導體業", preview["body_html"])
        self.assertIn("電子零組件業", preview["body_html"])
        self.assertIn("其他電子業", preview["body_html"])
        self.assertNotIn(">24<", preview["body_html"])
        self.assertNotIn(">28<", preview["body_html"])
        self.assertNotIn(">31<", preview["body_html"])

    def test_market_preview_can_include_taiwan_watchlist_radar(self) -> None:
        with dispatch_db_session() as db, patch.object(
            dispatch_templates.reports,
            "build_watchlist_brief",
            return_value=_watchlist_brief_envelope(),
        ) as build_watchlist_brief:
            preview = dispatch_service.build_preview(
                db=db,
                payload=DispatchPreviewRequest(
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                    include_radar=True,
                    radar_group_id=7,
                    radar_mode="all",
                    content_depth="deep",
                    radar_limit=12,
                ),
            )

        build_watchlist_brief.assert_called_once()
        self.assertEqual(build_watchlist_brief.call_args.kwargs["group_id"], 7)
        self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_mode"], "all")
        self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_limit"], 12)
        self.assertIn("台股大盤總覽", preview["subject"])
        self.assertIn("## 總覽雷達：科技股", preview["body_text"])
        self.assertIn("### 雷達判讀", preview["body_text"])
        self.assertIn("### 圖表摘要", preview["body_text"])
        self.assertIn("### 研究檢查清單", preview["body_text"])
        self.assertIn("### 突破 / 動能", preview["body_text"])
        self.assertIn("總覽雷達：科技股", preview["body_html"])
        self.assertIn("雷達圖表摘要", preview["body_html"])
        self.assertIn("雷達分桶圖", preview["body_html"])
        self.assertIn("訊號：突破", preview["body_html"])
        self.assertEqual(preview["metadata"]["radar"]["dispatch_version"], "v2")
        self.assertEqual(preview["metadata"]["radar"]["group_id"], 7)
        self.assertEqual(preview["metadata"]["radar"]["radar_limit"], 12)
        self.assertIn("radar: Watchlist context uses local daily indicator data.", preview["warnings"])
        self.assertIn("radar:broker_branch_daily", preview["missing"])

    def test_market_preview_rejects_us_radar_request(self) -> None:
        with dispatch_db_session() as db:
            with self.assertRaises(dispatch_service.DispatchValidationError):
                dispatch_service.build_preview(
                    db=db,
                    payload=DispatchPreviewRequest(
                        template_key="market_overview",
                        scope_type="market",
                        scope_id="us",
                        include_radar=True,
                        radar_group_id=7,
                    ),
                )

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

    def test_watchlist_deep_preview_renders_radar_v2_sections(self) -> None:
        with dispatch_db_session() as db, patch.object(
            dispatch_templates.reports,
            "build_watchlist_brief",
            return_value=_watchlist_brief_envelope(),
        ) as build_watchlist_brief:
            preview = dispatch_service.build_preview(
                db=db,
                payload=DispatchPreviewRequest(
                    template_key="watchlist_brief",
                    scope_type="watchlist",
                    scope_id="7",
                    radar_mode="all",
                    content_depth="deep",
                    radar_limit=16,
                ),
            )

        build_watchlist_brief.assert_called_once()
        self.assertEqual(build_watchlist_brief.call_args.kwargs["group_id"], 7)
        self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_mode"], "all")
        self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_limit"], 16)
        self.assertEqual(preview["template_key"], "watchlist_brief")
        self.assertIn("科技股 自選股觀察", preview["subject"])
        self.assertIn("派報 v2", preview["body_html"])
        self.assertIn("雷達總覽", preview["body_html"])
        self.assertIn("自選股結構", preview["body_html"])
        self.assertIn("雷達判讀", preview["body_html"])
        self.assertIn("圖表摘要", preview["body_html"])
        self.assertIn("雷達分桶圖", preview["body_html"])
        self.assertIn("研究檢查清單", preview["body_html"])
        self.assertIn("突破 / 動能", preview["body_html"])
        self.assertIn("風險 / 轉弱 / 過熱", preview["body_html"])
        self.assertIn("雷達完整清單", preview["body_html"])
        self.assertIn("訊號：突破", preview["body_html"])
        self.assertIn("## 自選股結構", preview["body_text"])
        self.assertIn("## 雷達判讀", preview["body_text"])
        self.assertIn("## 雷達總覽", preview["body_text"])
        self.assertIn("## 風險 / 轉弱 / 過熱", preview["body_text"])
        self.assertEqual(preview["metadata"]["dispatch_version"], "v2")
        self.assertEqual(preview["metadata"]["content_depth"], "deep")
        self.assertEqual(preview["metadata"]["radar_limit"], 16)
        self.assertEqual(preview["metadata"]["radar_sections"]["risk_count"], 1)

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

    def test_create_schedule_normalizes_time_and_request(self) -> None:
        with dispatch_db_session() as db:
            group = _recipient_group(db)
            schedule = dispatch_service.create_schedule(
                db=db,
                payload=DispatchScheduleCreate(
                    name="Morning dispatch",
                    description="Pre-open market brief",
                    recipient_group_id=group["id"],
                    send_time="8:55",
                    day_of_week="weekdays",
                    timezone="Asia/Taipei",
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                    content_depth="deep",
                    radar_limit=12,
                ),
            )

        self.assertEqual(schedule["name"], "Morning dispatch")
        self.assertEqual(schedule["send_time"], "08:55")
        self.assertEqual(schedule["day_of_week"], "mon-fri")
        self.assertEqual(schedule["timezone"], "Asia/Taipei")
        self.assertEqual(schedule["template_key"], "market_overview")
        self.assertEqual(schedule["request"]["content_depth"], "deep")
        self.assertEqual(schedule["request"]["radar_limit"], 12)

    def test_due_schedule_queues_once_per_run_key(self) -> None:
        with dispatch_db_session() as db, patch.object(
            dispatch_service.job_service,
            "enqueue_job",
            side_effect=_fake_enqueue_job,
        ):
            group = _recipient_group(db)
            schedule = dispatch_service.create_schedule(
                db=db,
                payload=DispatchScheduleCreate(
                    name="Morning dispatch",
                    recipient_group_id=group["id"],
                    send_time="08:55",
                    day_of_week="mon-fri",
                    timezone="Asia/Taipei",
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                ),
            )
            now = datetime(2026, 7, 1, 8, 55, tzinfo=ZoneInfo("Asia/Taipei"))

            first = dispatch_service.enqueue_due_schedules(db=db, now=now)
            second = dispatch_service.enqueue_due_schedules(db=db, now=now)

            saved_schedule = dispatch_service.get_schedule(db=db, schedule_id=schedule["id"])
            delivery_count = db.query(DispatchDelivery).count()

        self.assertEqual(first["queued_count"], 1)
        self.assertEqual(first["error_count"], 0)
        self.assertEqual(second["queued_count"], 0)
        self.assertEqual(delivery_count, 1)
        self.assertEqual(saved_schedule.last_run_key, "2026-07-01 08:55 Asia/Taipei")
        self.assertIsNotNone(saved_schedule.last_delivery_id)
        self.assertIsNotNone(saved_schedule.last_job_run_id)

    def test_run_schedule_now_queues_delivery_without_consuming_timed_run(self) -> None:
        with dispatch_db_session() as db, patch.object(
            dispatch_service.job_service,
            "enqueue_job",
            side_effect=_fake_enqueue_job,
        ):
            group = _recipient_group(db)
            schedule = dispatch_service.create_schedule(
                db=db,
                payload=DispatchScheduleCreate(
                    name="Manual test",
                    recipient_group_id=group["id"],
                    send_time="08:55",
                    day_of_week="mon-fri",
                    timezone="Asia/Taipei",
                    template_key="market_overview",
                    scope_type="market",
                    scope_id="tw",
                ),
            )

            result = dispatch_service.run_schedule_now(db=db, schedule_id=schedule["id"])
            saved_schedule = dispatch_service.get_schedule(db=db, schedule_id=schedule["id"])

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["job"]["job_type"], "dispatch.mail_delivery")
        self.assertEqual(result["delivery"]["recipient_group_id"], group["id"])
        self.assertTrue(saved_schedule.last_run_key.startswith("manual:"))


if __name__ == "__main__":
    unittest.main()
