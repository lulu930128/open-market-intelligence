from __future__ import annotations

from collections.abc import Callable
from typing import Any


ProgressEvent = dict[str, Any]
ProgressCallback = Callable[[ProgressEvent], None]


def emit_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    **extra: Any,
) -> None:
    if callback is None:
        return

    stage_text = str(stage or "").strip()
    message_text = str(message or "").strip()
    if not stage_text or not message_text:
        return

    event: ProgressEvent = {
        "stage": stage_text,
        "message": message_text,
    }
    event.update({key: value for key, value in extra.items() if value is not None})

    try:
        callback(event)
    except Exception:
        return
