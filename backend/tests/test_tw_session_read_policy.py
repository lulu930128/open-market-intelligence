from unittest.mock import patch

import pytest

from app.ai import ask_execution
from app.ai.schemas import AiAskRequest


@pytest.mark.parametrize("realtime_policy", ["cache_only", "prefer_live", "require_live"])
@pytest.mark.parametrize("fallback_to_cached", [False, True])
@pytest.mark.parametrize("scope_type,target", [
    ("market", {"type": "market", "id": "TW", "market": "TW"}),
    ("stock", {"type": "tw_stock", "id": "2330"}),
])
def test_selected_intraday_read_is_independent_of_acquisition_permission(
    realtime_policy, fallback_to_cached, scope_type, target,
):
    payload = AiAskRequest(
        question="盤中資料",
        target=target,
        realtime_policy=realtime_policy,
        allow_external_fetch=False,
        refresh_policy={"fallback_to_cached": fallback_to_cached},
        selection={"include": ["intraday.bars"]},
    )
    policy = {
        "can_external_fetch": False,
        "refresh_policy": {"fallback_to_cached": fallback_to_cached},
        "query_plan": {"selected_capabilities": ["intraday.bars"]},
    }
    reader_name = "read_market_overview" if scope_type == "market" else "read_stock_context"
    evidence = {"kind": "test_context", "data": {"intraday": {"status": "missing"}}}
    with patch.object(ask_execution.tools, reader_name, return_value=evidence) as reader:
        _, result = ask_execution._read_data_only(
            db=object(), payload=payload, scope_type=scope_type, policy=policy,
        )
    assert result is evidence
    assert reader.call_args.kwargs["include_intraday"] is True
    assert reader.call_args.kwargs["market_data_params"]["external_fetch_allowed"] is False
    assert reader.call_args.kwargs["market_data_params"]["realtime_policy"] == realtime_policy
    assert reader.call_args.kwargs["market_data_params"]["fallback_to_cached"] is fallback_to_cached


@pytest.mark.parametrize("params,selection,query_plan", [
    ({"include_intraday": False}, {"include": ["intraday.bars"]}, {"selected_capabilities": ["intraday.bars"]}),
    ({}, {"exclude": ["intraday.bars"]}, {}),
    ({}, {"include": ["market.breadth"]}, {}),
    ({}, {}, {"selected_capabilities": ["market.breadth"]}),
    ({"include_intraday": True}, {}, {"selected_capabilities": ["market.breadth"]}),
])
def test_read_selection_does_not_expand_from_intraday_question(params, selection, query_plan):
    payload = AiAskRequest(
        question="現在盤中走勢", target={"type": "market", "id": "TW"},
        market_data_params=params, selection=selection, allow_external_fetch=True,
    )
    assert ask_execution._include_tw_intraday(
        payload, policy={"can_external_fetch": True, "query_plan": query_plan},
    ) is False


def test_optional_selected_intraday_is_readable_without_fetch_permission():
    payload = AiAskRequest(question="背景資料", target={"type": "tw_stock", "id": "2330"})
    assert ask_execution._include_tw_intraday(payload, policy={
        "can_external_fetch": False,
        "query_plan": {"selected_capabilities": [], "optional_selected_capabilities": ["intraday.bars"]},
    }) is True


def test_market_brief_horizon_does_not_override_explicit_read_exclusion():
    with patch.object(ask_execution.tools, "read_market_overview", return_value={"data": {}}) as reader:
        ask_execution.reports.build_market_brief(
            db=object(), include_intraday=False, analysis_horizon="intraday",
        )
    assert reader.call_args.kwargs["include_intraday"] is False


@pytest.mark.parametrize("realtime_policy", ["cache_only", "prefer_live", "require_live"])
def test_market_intraday_missing_read_has_no_network_job_or_database_writes(realtime_policy):
    import socket
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import Session
    from app.db.models import Base
    from app.jobs import service as job_service

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _conn, _cursor, statement, *_args: statements.append(statement))
    try:
        with Session(engine) as db:
            db.execute(text("PRAGMA query_only=ON"))
            payload = AiAskRequest(
                question="台股盤中", target={"type": "market", "id": "TW", "market": "TW"},
                realtime_policy=realtime_policy, allow_external_fetch=False,
                selection={"include": ["intraday.bars"]},
                market_data_params={"requested_domains": ["intraday"], "requested_capabilities": ["intraday.bars"]},
            )
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")) as network,
                patch.object(job_service, "enqueue_job", side_effect=AssertionError("job forbidden")) as enqueue,
            ):
                _, result = ask_execution._read_market_context(
                    db, payload, tool_runs=[], policy={"can_external_fetch": False, "query_plan": {"selected_capabilities": ["intraday.bars"]}},
                )
            assert result["missing"]
            network.assert_not_called()
            enqueue.assert_not_called()
            assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for statement in statements)
    finally:
        engine.dispose()
