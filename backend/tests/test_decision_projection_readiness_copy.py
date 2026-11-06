"""The v4 readiness pass copies mutable contract state, not unused history."""
from copy import deepcopy

from app.ai import decision_envelope
from test_ai_decision_envelope import _v2_response


def test_owned_v4_readiness_matches_legacy_without_copying_unread_analysis():
    source = _v2_response()
    original = deepcopy(source)
    expected = decision_envelope.build(source)
    expected["evidence"]["result"] = {}

    class UnreadHistory(list):
        def __deepcopy__(self, memo):
            raise AssertionError("unused technical history was copied for readiness")

    source["analysis"]["unused_technical_history"] = UnreadHistory([{"close": 123}])
    actual = decision_envelope.build(source, include_evidence_result=False)
    assert actual == expected
    actual["decision"]["context"]["fixture_change"] = True
    actual["status"]["readiness"]["decision_ready"] = "changed"
    source["analysis"].pop("unused_technical_history")
    assert source == original
