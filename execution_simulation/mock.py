"""Closed fixture vocabulary. There is no broker interface or adapter injection."""

from enum import Enum

from execution.contracts import EventKind, SimulationEvent
from execution.validation import require


class Fixture(str, Enum):
    SDK_ACCEPT = "SDK_ACCEPT"
    SDK_PENDING = "SDK_PENDING"
    SDK_REJECT = "SDK_REJECT"
    SDK_TIMEOUT = "SDK_TIMEOUT"
    SDK_AMBIGUOUS = "SDK_AMBIGUOUS"
    SDK_CANCEL = "SDK_CANCEL"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    TIMEOUT = "TIMEOUT"
    QUERY_UNAVAILABLE = "QUERY_UNAVAILABLE"
    QUERY_ERROR = "QUERY_ERROR"
    CANCEL = "CANCEL"
    CANCEL_PENDING = "CANCEL_PENDING"


class SimulatedCrash(BaseException):
    """Test fault injection, intentionally bypasses ordinary command rejection."""


def receipt(command_id, preview_id, kind, fixture, now, sequence, filled):
    require(type(fixture) is Fixture, "INVALID_MOCK_FIXTURE")
    require((kind == "SEND" and fixture in {
        Fixture.ACCEPT, Fixture.REJECT, Fixture.TIMEOUT, Fixture.QUERY_UNAVAILABLE, Fixture.QUERY_ERROR,
    }) or (kind == "CANCEL" and fixture in {
        Fixture.CANCEL, Fixture.CANCEL_PENDING, Fixture.TIMEOUT,
        Fixture.QUERY_UNAVAILABLE, Fixture.QUERY_ERROR,
    }), "INVALID_MOCK_FIXTURE")
    if fixture in {Fixture.QUERY_UNAVAILABLE, Fixture.QUERY_ERROR, Fixture.CANCEL_PENDING}:
        return None
    report = EventKind.REJECTED if fixture is Fixture.REJECT else (
        EventKind.ACCEPTED if kind == "SEND" else EventKind.CANCELLED)
    return SimulationEvent("mock-" + command_id, preview_id, report, now, sequence, filled)
