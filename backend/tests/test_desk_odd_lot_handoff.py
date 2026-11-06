"""Incident order parameters through Backend -> CLI -> injected Runtime only."""
from test_conditional_candidates import setup, invoke


def test_one_share_cash_stage_without_protection_sends_once_to_fake_sdk(setup):
    raw = {"client_intent_id": "fixture-2330-odd-readback", "symbol": "2330", "action": "Buy",
        "condition": "CASH", "lot": "Odd", "quantity_shares": 1, "price": "2315",
        "protection": {"direction": 1, "enabled": False, "exit_limit_price": "2315",
            "protection_mode": "LOCAL_SYNTHETIC", "stop_limit_price": None,
            "stop_loss": None, "take_profit": None, "targets": []}}
    row = invoke(setup, "create", raw, owner_id="MCP", manual_stage=True)
    with setup[0]() as db:
        service = setup[1](db)
        original = service.control

        def control(value):
            result = original(value)
            return {**result, "session_date_matches": True} if value["operation"] == "status" else result

        service.control = control
        arguments = {"expected_revision": row["revision"], "expected_digest": row["digest"]}
        first = service.send_staged(row["id"], **arguments)
        second = service.send_staged(row["id"], **arguments)
    assert first == second
    assert first["lifecycle"] == "SUBMITTED"
    assert len(setup[3].broker.attempts) == 1
    commands = [v["request"]["argv"][0] for v in setup[4] if v["operation"] == "command"]
    assert commands == ["desk-submit"]
    execution = first["manual_stage"]["submission"]["receipt"]["execution"]
    assert execution["quantity"] == 1
    assert execution["submit_claims"] == 1
    view = setup[2].desk_order("TW", execution["execution_id"])
    assert view["protection"]["rules"]["enabled"] is False
    assert setup[3].broker.cancels == []
