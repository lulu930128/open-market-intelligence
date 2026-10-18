"""Bounded internal MIS acquisition evidence, persisted in the existing receipt.

No market readiness/freshness policy lives here. Original-message examples are
field/size limited; the digest covers the returned original messages, not HTTP bytes.
"""
from __future__ import annotations

from concurrent.futures import Future, wait
from hashlib import sha256
import json
from threading import Lock, Thread
from time import monotonic
from typing import Callable


EXAMPLE_FIELDS = ("c", "d", "t", "z", "v", "tv", "ts", "pz", "ps", "o", "h", "l", "y")
_IO_LOCK = Lock()
_IN_FLIGHT: dict[str, Future] = {}


class AcquisitionInFlight(RuntimeError):
    """An earlier timed-out transport still owns the single IO slot."""


class AcquisitionDeadlineExceeded(TimeoutError):
    """Caller budget expired; this does not establish a socket timeout."""


def reset_io_slots() -> None:
    """Test/reset seam: never detach an active worker and allow another to spawn."""
    with _IO_LOCK:
        if any(not future.done() for future in _IN_FLIGHT.values()):
            raise AcquisitionInFlight("TWSE_MIS_TRANSPORT_RESET_REQUIRES_IDLE")
        _IN_FLIGHT.clear()


def bounded_fetch(fetch: Callable, seconds: float, *args, **kwargs):
    """Bound caller wait even when requests' socket timeout is not a wall deadline.

One daemon IO slot per venue (at most two), no queue/retries. A late response cannot mutate the provider
cache or guard: only the waiting acquisition thread does that. A stuck transport
blocks subsequent IO until completion instead of accumulating background workers.
    """
    venue = kwargs.get("exchange")
    if venue not in {"tse", "otc"}:
        raise ValueError("MIS breadth transport requires an explicit venue")
    deadline = monotonic() + seconds
    if seconds <= 0:
        raise AcquisitionDeadlineExceeded("TWSE_MIS_ACQUISITION_DEADLINE")
    with _IO_LOCK:
        previous = _IN_FLIGHT.get(venue)
        if previous is not None and not previous.done():
            raise AcquisitionInFlight("TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT")
        future = Future()
        _IN_FLIGHT[venue] = future

        def run():
            try:
                future.set_result(fetch(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

        Thread(target=run, name=f"twse-mis-breadth-{venue}-io", daemon=True).start()
    completed, _ = wait((future,), timeout=max(0.0, deadline - monotonic()))
    if not completed:
        raise AcquisitionDeadlineExceeded("TWSE_MIS_ACQUISITION_DEADLINE")
    # Resolve outside the wait: Future.result also raises the worker's own
    # TimeoutError, which must not be relabeled as caller budget exhaustion.
    return future.result()


def original_message_evidence(messages: list[dict], missing: list[dict]) -> dict:
    return {
        "message_digest_sha256": sha256(json.dumps(messages, sort_keys=True, default=str,
                                                   separators=(",", ":")).encode()).hexdigest(),
        "digest_basis": "parsed_original_messages_before_classification",
        "missing_examples": [
            {key: str(message[key])[:96] for key in EXAMPLE_FIELDS if key in message}
            for message in missing[:3]
        ],
    }


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"count": len(values), "min": min(values, default=None),
            "max": max(values, default=None),
            "p50": ordered[(len(ordered) - 1) // 2] if ordered else None,
            "p95": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)] if ordered else None}
