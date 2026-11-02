"""Source acceptance only: isolated SQLite, no application engine or live data."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.market.trading_calendar import TAIWAN_TZ
from app.research.paper_outcome import calculate_paper_outcomes, evaluate_proposal
from app.research.trade_journal import (
    create_proposal, list_versions, proposal_at, proposal_versions, revise_proposal,
)
from app.research.trade_proposal import (
    EvidenceItem, PaperBar, PaperCosts, PaperStrategy, PaperTarget, ProposalEvidence,
)
from app.watchlists.radar_outcome_v2_service import trading_dates_after


UTC = timezone.utc
DECISION = datetime(2026, 10, 27, 8, tzinfo=UTC)
DATES = trading_dates_after(date(2026, 10, 27), 15)
AS_OF = datetime.combine(DATES[-1], time(10), UTC)
MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20261030_0094_research_trade_journal.py"


def migration():
    spec = importlib.util.spec_from_file_location("research_journal_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine(tmp_path):
    # Exercise the real additive migration, never Base.metadata.create_all().
    engine = create_engine("sqlite:///" + (tmp_path / "research.sqlite").as_posix())
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
    yield engine
    engine.dispose()


def evidence():
    return ProposalEvidence(
        as_of_trade_date=date(2026, 10, 27), cutoff=DECISION - timedelta(minutes=1),
        price_basis="unadjusted:v1",
        items=(EvidenceItem(source_ref="fixture:daily:2330", source_available_at=DECISION - timedelta(hours=1),
                            received_at=DECISION - timedelta(hours=1), data_revision="original",
                            snapshot_json='{"close":100,"stop":95}'),),
    )


def strategy(**changes):
    values = dict(
        version="fixture-strategy-v1", direction=1, mode="aggressive", entry_rule="next_open",
        entry_price=100, stop_price=95, targets=(PaperTarget(price=110, fraction=1),),
        shares=1000, thesis="Historical research hypothesis", paper_eligibility="eligible",
        qualification_refs=("fixture:daily:2330",),
    )
    values.update(changes)
    return PaperStrategy(**values)


def costs(**changes):
    values = dict(version="cost-v1", commission_rate=0.001425, minimum_commission=20,
                  sell_tax_rate=0.003, slippage_per_share=0,
                  short_borrow_per_share_session=0, other_cost=0,
                  assumptions=("Example assumptions, not verified broker fees",))
    values.update(changes)
    return PaperCosts(**values)


def create(db, **changes):
    values = dict(symbol="2330", evidence=evidence(), strategy=strategy(), costs=costs(),
                  effective_at=DECISION, change_reason="Initial research", now=DECISION)
    values.update(changes)
    return create_proposal(db, **values)


def bar(day, **changes):
    stamp = datetime.combine(day, time(8), UTC)
    values = dict(symbol="2330", trade_date=day, open_price=100, high_price=104, low_price=98,
                  close_price=102, source_ref="fixture:canonical-daily", data_revision="v1",
                  source_available_at=stamp, received_at=stamp, price_basis="unadjusted:v1",
                  corporate_action="clear")
    values.update(changes)
    return PaperBar(**values)


def path(**changes):
    return [bar(day, **changes) for day in DATES]


def evaluate(version, bars=None, **changes):
    values = dict(version=version, decision_at=DECISION, outcome_as_of=AS_OF,
                  bars=path() if bars is None else bars)
    values.update(changes)
    return calculate_paper_outcomes(**values)


def test_journal_persists_immutable_versions_and_initial_risk(engine):
    with Session(engine) as db, db.begin():
        original = create(db)
    later = DECISION + timedelta(days=1)
    with Session(engine) as db, db.begin():
        revised = revise_proposal(
            db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
            strategy=strategy(version="v2", entry_price=101, stop_price=98),
            costs=costs(version="cost-v2", commission_rate=0.001),
            effective_at=later, now=later, change_reason="Tighten the hypothesis",
        )
    with Session(engine) as db:
        historical = proposal_at(db, creation_id=original.creation_id, decision_at=DECISION)
        current = proposal_at(db, creation_id=original.creation_id, decision_at=later)
        versions = list_versions(db, creation_id=original.creation_id, as_of=later)
    assert historical == original
    assert current == revised
    assert len(versions) == 2
    assert revised.supersedes == original.revision_id
    assert revised.evidence == original.evidence
    assert revised.evidence_hash == original.evidence_hash
    assert revised.initial_stop_distance == 5
    assert revised.initial_risk_amount == 5000
    assert revised.costs.version == "cost-v2"


@pytest.mark.parametrize("statement", [
    "UPDATE research_trade_proposal_version SET payload_json='{}'",
    "DELETE FROM research_trade_proposal_version",
    "INSERT OR REPLACE INTO research_trade_proposal_version SELECT * FROM research_trade_proposal_version",
])
def test_database_rejects_mutation_even_outside_service(engine, statement):
    with Session(engine) as db, db.begin():
        original = create(db)
    with Session(engine) as db:
        with pytest.raises(IntegrityError, match="immutable"):
            db.execute(text(statement))
        db.rollback()
        assert proposal_at(db, creation_id=original.creation_id, decision_at=DECISION) == original


def test_caller_owns_rollback_and_read_does_not_write(engine):
    with Session(engine) as db:
        original = create(db)
        db.rollback()
        with pytest.raises(LookupError):
            proposal_at(db, creation_id=original.creation_id, decision_at=DECISION)
        assert db.execute(select(proposal_versions)).all() == []


def test_future_effective_revision_is_visible_but_not_active_and_conflicts(engine):
    with Session(engine) as db, db.begin():
        original = create(db)
        later = DECISION + timedelta(hours=1)
        future = later + timedelta(days=1)
        revised = revise_proposal(
            db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
            strategy=strategy(version="v2"), costs=costs(), effective_at=future, now=later,
            change_reason="Prospective revision",
        )
        assert proposal_at(db, creation_id=original.creation_id, decision_at=later) == original
        assert len(list_versions(db, creation_id=original.creation_id, as_of=DECISION)) == 1
        with pytest.raises(ValueError, match="conflict"):
            revise_proposal(db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
                            strategy=strategy(), costs=costs(), effective_at=future + timedelta(days=1),
                            now=later, change_reason="Stale writer")
        assert proposal_at(db, creation_id=original.creation_id, decision_at=future) == revised


def test_backdating_revision_and_future_evidence_rejected(engine):
    with Session(engine) as db, db.begin():
        original = create(db)
        with pytest.raises(ValueError, match="prospectively"):
            revise_proposal(db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
                            strategy=strategy(), costs=costs(), effective_at=DECISION,
                            now=DECISION + timedelta(days=1), change_reason="Backdated")
        with pytest.raises(ValueError, match="backdate"):
            create(db, effective_at=DECISION - timedelta(seconds=1))
    values = evidence().model_dump()
    values["items"][0]["received_at"] = DECISION + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="unavailable"):
        ProposalEvidence.model_validate(values)


def test_revision_does_not_change_historical_replay(engine):
    with Session(engine) as db, db.begin():
        original = create(db)
        first = evaluate_proposal(db, creation_id=original.creation_id, decision_at=DECISION,
                                  outcome_as_of=AS_OF, bars=path())
        later = DECISION + timedelta(days=1)
        revise_proposal(db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
                        strategy=strategy(version="future", stop_price=99), costs=costs(version="future-cost"),
                        effective_at=later, now=later, change_reason="Later adjustment")
        second = evaluate_proposal(db, creation_id=original.creation_id, decision_at=DECISION,
                                   outcome_as_of=AS_OF, bars=path())
        assert first == second
        assert first["realized_trade_r"] is None
        assert first["actual_fill"] is None


def test_ten_fifteen_horizons_mfe_mae_initial_stop_r_and_costs(engine):
    with Session(engine) as db:
        result = evaluate(create(db))
    assert [item["horizon_sessions"] for item in result["outcomes"]] == [10, 15]
    for outcome in result["outcomes"]:
        assert outcome["coverage"] == "complete"
        assert outcome["path_metrics"]["mfe_trade_r"] == pytest.approx(0.8)
        assert outcome["path_metrics"]["mae_trade_r"] == pytest.approx(0.4)
        paper = outcome["paper"]
        assert paper["fill_assessment"] == "paper"
        assert paper["state"] == "expired"
        assert paper["trade_r"] == pytest.approx(0.4)
        assert paper["gross_pnl"] == 2000
        assert paper["cost_amount"] == pytest.approx(100000 * 0.001425 + 102000 * (0.001425 + 0.003))
        assert paper["net_trade_r"] == pytest.approx(paper["net_pnl"] / 5000)


def test_window_is_trading_days_including_official_holiday(engine):
    dates = trading_dates_after(date(2026, 10, 8), 10)
    assert date(2026, 10, 9) not in dates
    assert date(2026, 10, 10) not in dates
    assert dates[0] == date(2026, 10, 12)


def test_calendar_snapshot_does_not_drift_on_later_calendar_changes(engine):
    with Session(engine) as db:
        original = create(db)
        first = evaluate(original)
        with patch("app.watchlists.radar_outcome_v2_service.trading_dates_after", side_effect=AssertionError("calendar drift")), \
             patch("app.market.trading_calendar.has_taiwan_calendar_year", return_value=False):
            assert evaluate(original) == first


def test_late_qualification_cannot_be_attached_without_frozen_evidence(engine):
    with Session(engine) as db:
        with pytest.raises(ValidationError, match="frozen evidence"):
            create(db, strategy=strategy(qualification_refs=("future:borrow-receipt",)))


def test_revised_strategy_uses_original_one_r_and_its_prospective_window(engine):
    later = DECISION + timedelta(days=1)
    with Session(engine) as db, db.begin():
        original = create(db)
        revised = revise_proposal(
            db, creation_id=original.creation_id, expected_revision_id=original.revision_id,
            strategy=strategy(version="v2", entry_price=101, stop_price=98), costs=costs(),
            effective_at=later, now=later, change_reason="New prospective hypothesis",
        )
        bars = [bar(day, open_price=101, low_price=99, close_price=103) for day in revised.planned_trade_dates]
        result = calculate_paper_outcomes(version=revised, decision_at=later,
                                         outcome_as_of=AS_OF + timedelta(days=7), bars=bars)
    assert result["window_anchor_trade_date"] == "2026-10-28"
    assert result["initial_risk_amount"] == 5000
    assert result["outcomes"][0]["paper"]["trade_r"] == pytest.approx(0.4)


def test_pure_path_math_is_reused_without_exporting_radar_atr_semantics(engine):
    from app.watchlists.radar_outcome_v2_service import calculate_outcome_path
    with Session(engine) as db:
        original = create(db)
        with patch("app.research.paper_outcome.calculate_outcome_path", wraps=calculate_outcome_path) as calculator:
            result = evaluate(original)
        assert calculator.call_count == 2
        assert all(call.kwargs["signal_atr"] is None for call in calculator.call_args_list)
        assert "signal_atr" not in result["outcomes"][0]["path_metrics"]


@pytest.mark.parametrize("direction,levels,prices", [
    (1, {}, dict(open_price=100, high_price=112, low_price=98, close_price=111)),
    (-1, dict(stop_price=105, targets=(PaperTarget(price=90, fraction=1),)),
     dict(open_price=100, high_price=102, low_price=88, close_price=89)),
])
def test_directional_targets_and_favorable_mfe(engine, direction, levels, prices):
    bars = path()
    bars[1] = bar(DATES[1], **prices)
    with Session(engine) as db:
        result = evaluate(create(db, strategy=strategy(direction=direction, **levels)), bars)
    paper = result["outcomes"][0]["paper"]
    assert paper["state"] == "target"
    assert paper["trade_r"] == pytest.approx(2)
    assert result["outcomes"][0]["path_metrics"]["mfe_trade_r"] == pytest.approx(2.4)


@pytest.mark.parametrize("direction,stop,prices", [
    (1, 95, dict(open_price=90, high_price=92, low_price=88, close_price=91)),
    (-1, 105, dict(open_price=110, high_price=112, low_price=108, close_price=111)),
])
def test_gap_stop_can_lose_more_than_one_initial_r(engine, direction, stop, prices):
    bars = path()
    bars[1] = bar(DATES[1], **prices)
    target = 110 if direction == 1 else 90
    with Session(engine) as db:
        result = evaluate(create(db, strategy=strategy(direction=direction, stop_price=stop,
                                targets=(PaperTarget(price=target, fraction=1),))), bars)
    paper = result["outcomes"][0]["paper"]
    assert paper["state"] == "stop"
    assert paper["trade_r"] == -2


def test_same_bar_stop_target_never_reported_as_profit(engine):
    bars = path()
    bars[2] = bar(DATES[2], high_price=112, low_price=94)
    with Session(engine) as db:
        outcome = evaluate(create(db), bars)["outcomes"][0]
    assert outcome["paper"]["fill_assessment"] == "ambiguous"
    assert outcome["paper"]["trade_r"] is None
    assert outcome["paper"]["net_pnl"] is None
    assert "stop_target_order_unknown_in_daily_bar" in outcome["limitations"]


def test_intraday_entry_and_exit_order_unknown(engine):
    bars = path()
    bars[0] = bar(DATES[0], open_price=98, high_price=111, low_price=94, close_price=100)
    with Session(engine) as db:
        outcome = evaluate(create(db, strategy=strategy(entry_rule="at_or_above")), bars)["outcomes"][0]
    assert outcome["paper"]["fill_assessment"] == "ambiguous"
    assert outcome["paper"]["trade_r"] is None
    assert "entry_exit_order_unknown_in_daily_bar" in outcome["limitations"]


def test_partial_targets_and_expiry(engine):
    bars = path()
    bars[1] = bar(DATES[1], high_price=106, close_price=105)
    with Session(engine) as db:
        outcome = evaluate(create(db, strategy=strategy(targets=(
            PaperTarget(price=105, fraction=0.5), PaperTarget(price=110, fraction=0.5)))), bars)["outcomes"][0]
    assert [exit["kind"] for exit in outcome["paper"]["exits"]] == ["target", "expiry"]
    assert outcome["paper"]["trade_r"] == pytest.approx(0.7)


@pytest.mark.parametrize("eligibility,expected", [("unknown", "unknown"), ("ineligible", "unfilled")])
def test_qualification_is_not_inferred_from_price_touch(engine, eligibility, expected):
    with Session(engine) as db:
        outcome = evaluate(create(db, strategy=strategy(paper_eligibility=eligibility)))["outcomes"][0]
    assert outcome["paper"]["triggered"] is True
    assert outcome["paper"]["fill_assessment"] == expected
    assert outcome["paper"]["trade_r"] is None


def test_untriggered_does_not_invent_a_fill(engine):
    with Session(engine) as db:
        outcome = evaluate(create(db, strategy=strategy(entry_rule="at_or_below", entry_price=97,
                                                        stop_price=95)))["outcomes"][0]
    assert outcome["paper"]["triggered"] is False
    assert outcome["paper"]["fill_assessment"] == "unfilled"
    assert outcome["paper"]["trade_r"] is None


def test_missing_middle_bar_does_not_bridge_to_later_profit(engine):
    bars = path()
    bars.pop(1)
    bars[1] = bar(DATES[2], high_price=112)
    with Session(engine) as db:
        outcome = evaluate(create(db), bars)["outcomes"][0]
    assert outcome["coverage"] == "partial"
    assert outcome["path_metrics"]["observed_sessions"] == 1
    assert outcome["paper"]["state"] == "open"
    assert outcome["paper"]["trade_r"] is None


def test_outcome_receipt_cutoff_and_later_revisions_do_not_leak(engine):
    bars = path()
    cutoff = bars[9].received_at
    later_revision = bar(DATES[0], high_price=999, data_revision="future",
                         received_at=cutoff + timedelta(seconds=1))
    with Session(engine) as db:
        original = create(db)
        first = evaluate(original, bars, outcome_as_of=cutoff)
        second = evaluate(original, bars + [later_revision], outcome_as_of=cutoff)
        refreshed = evaluate(original, bars + [later_revision], outcome_as_of=AS_OF)
    assert first == second
    assert first["outcomes"][0]["coverage"] == "complete"
    assert first["outcomes"][1]["coverage"] == "partial"
    assert first["outcomes"][1]["paper"]["state"] == "open"
    assert refreshed["outcomes"][0]["path_metrics"]["mfe_price"] == pytest.approx(899)


@pytest.mark.parametrize("field", ["received_at", "source_available_at"])
def test_both_receipt_and_source_availability_are_bounded(engine, field):
    bars = path()
    values = bars[0].model_dump()
    values[field] = AS_OF + timedelta(seconds=1)
    bars[0] = PaperBar.model_validate(values)
    with Session(engine) as db:
        outcome = evaluate(create(db), bars)["outcomes"][0]
    assert outcome["missing_trade_dates"] == [DATES[0].isoformat()]
    assert outcome["paper"]["triggered"] is None


@pytest.mark.parametrize("changes", [dict(corporate_action="discontinuous"), dict(price_basis="adjusted:v2")])
def test_price_basis_discontinuity_suppresses_paper_profit_and_metrics(engine, changes):
    bars = path()
    bars[2] = bar(DATES[2], **changes)
    with Session(engine) as db:
        outcome = evaluate(create(db), bars)["outcomes"][0]
    assert outcome["paper"]["state"] == "unevaluable"
    assert outcome["paper"]["trade_r"] is None
    assert outcome["path_metrics"] == {}


def test_unknown_costs_and_corporate_coverage_stay_visible(engine):
    with Session(engine) as db:
        outcome = evaluate(create(db, costs=PaperCosts(version="unknown")),
                           path(corporate_action="unknown"))["outcomes"][0]
    assert outcome["paper"]["trade_r"] == 0.4
    assert outcome["paper"]["net_trade_r"] is None
    assert "cost_unknown" in outcome["limitations"]
    assert "corporate_action_coverage_unknown" in outcome["limitations"]


def test_short_borrow_unknown_does_not_become_zero(engine):
    with Session(engine) as db:
        outcome = evaluate(create(db, strategy=strategy(direction=-1, stop_price=105,
                           targets=(PaperTarget(price=90, fraction=1),)),
                           costs=costs(short_borrow_per_share_session=None)))["outcomes"][0]
    assert outcome["paper"]["trade_r"] == -0.4
    assert outcome["paper"]["net_trade_r"] is None


@pytest.mark.parametrize("changes", [dict(open_price=float("nan")), dict(low_price=105),
                                     dict(high_price=float("inf")), dict(close_price=0)])
def test_invalid_ohlc_rejected(changes):
    with pytest.raises(ValidationError):
        bar(DATES[0], **changes)


def test_naive_or_premature_daily_receipts_rejected():
    with pytest.raises(ValidationError):
        bar(DATES[0], received_at=datetime.combine(DATES[0], time(8)))
    with pytest.raises(ValidationError, match="session close"):
        bar(DATES[0], source_available_at=datetime.combine(DATES[0], time(9), TAIWAN_TZ))


def test_wrong_symbol_and_unresolved_provider_candidates_rejected(engine):
    with Session(engine) as db:
        original = create(db)
        with pytest.raises(ValueError, match="symbol"):
            evaluate(original, [bar(DATES[0], symbol="2409")])
        with pytest.raises(ValueError, match="provider selection"):
            evaluate(original, path() + [bar(DATES[0], source_ref="other-provider")])
        with pytest.raises(ValueError, match="indistinguishable"):
            evaluate(original, path() + [bar(DATES[0], data_revision="conflicting", high_price=200)])


def test_partial_daily_bar_never_used(engine):
    bars = path()
    bars[0] = bar(DATES[0], final=False, high_price=999)
    with Session(engine) as db:
        outcome = evaluate(create(db), bars)["outcomes"][0]
    assert outcome["paper"]["triggered"] is None
    assert outcome["path_metrics"] == {}


def test_migration_is_additive_and_refuses_to_drop_research_history(engine):
    assert inspect(engine).get_table_names() == ["research_trade_proposal_version"]
    with Session(engine) as db, db.begin():
        create(db)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="retention"):
                migration().downgrade()


def test_radar_active_contract_remains_unchanged():
    from app.watchlists.radar_outcome_v2_service import DEFAULT_HORIZONS
    from app.watchlists.radar_rule_contract import RADAR_V2_OUTCOME_CONFIG
    assert DEFAULT_HORIZONS == (1, 3, 5)
    assert RADAR_V2_OUTCOME_CONFIG["entry_proxy_price_type"] == "next_trading_day_open"
