"""Test-only cooperative acquisition fakes for the dark 02A control plane."""

from __future__ import annotations

from collections.abc import Callable

from app.market_data.policies import AcquisitionResult
from app.market_data.research_lease import (
    AcquisitionActivity,
    AcquisitionAttemptContext,
    CancelResult,
    CleanupResult,
    CleanupStatus,
    ProviderAttemptResult,
)


class FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.value = initial

    def __call__(self) -> float:
        return self.value

    def wait(self, seconds: float) -> None:
        self.value += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.wait(seconds)


class MutableCancellationToken:
    def __init__(self) -> None:
        self.cancelled = False

    def is_cancelled(self) -> bool:
        return self.cancelled

    def cancel(self) -> None:
        self.cancelled = True


class FakeLeaseHandle:
    def __init__(
        self,
        provider: FakeLeaseProvider,
        context: AcquisitionAttemptContext,
    ) -> None:
        self._provider = provider
        self._owner_token = provider.override_owner_token or context.owner_token
        self._started_at = provider.clock()
        self._active = True
        self._terminal = False
        self._cancelled = False
        self._released = False
        self._delivered = False
        self.poll_count = 0

    @property
    def owner_token(self) -> str:
        return self._owner_token

    @property
    def active(self) -> bool:
        return self._active

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def activity(self) -> AcquisitionActivity:
        return self._provider.activity

    def poll(self) -> ProviderAttemptResult | None:
        self.poll_count += 1
        if self._released or self._cancelled:
            return None
        if self._provider.raise_on_poll:
            raise RuntimeError("provider secret must not escape")
        if self._provider.terminal_without_result:
            self._terminal = True
            return None
        if self._provider.clock() - self._started_at < self._provider.ready_after_seconds:
            return None
        self._terminal = True
        self._delivered = True
        return self._provider.result

    def cancel(self, reason_code: str) -> CancelResult:
        self._provider.cancel_count += 1
        if self._provider.raise_on_cancel:
            raise RuntimeError("cancel secret must not escape")
        self._cancelled = True
        self._terminal = True
        return CancelResult(accepted=True, detail_code="CANCEL_ACCEPTED")

    def release(self) -> CleanupResult:
        if self._released:
            return CleanupResult(
                status=CleanupStatus.RELEASED,
                detail_code="ALREADY_RELEASED",
            )
        self._provider.release_count += 1
        if self._provider.raise_on_release:
            raise RuntimeError("release secret must not escape")
        self._released = True
        self._active = False
        self._terminal = True
        self._provider.active_handles -= 1
        return CleanupResult(
            status=CleanupStatus.RELEASED,
            detail_code="RELEASED",
        )

    def late_callback(self) -> bool:
        """Return whether a callback could reactivate outward acquisition state."""

        if self._cancelled or self._released or self._terminal:
            return False
        self._delivered = True
        return True


class FakeLeaseProvider:
    def __init__(
        self,
        *,
        clock: FakeClock,
        result: ProviderAttemptResult,
        ready_after_seconds: float = 0.0,
        external_calls: int | None = None,
        subscriptions_created: int | None = None,
        override_owner_token: str | None = None,
        raise_on_start: bool = False,
        raise_on_poll: bool = False,
        raise_on_cancel: bool = False,
        raise_on_release: bool = False,
        terminal_without_result: bool = False,
    ) -> None:
        self.clock = clock
        self.result = result
        self.ready_after_seconds = ready_after_seconds
        self.override_owner_token = override_owner_token
        self.raise_on_start = raise_on_start
        self.raise_on_poll = raise_on_poll
        self.raise_on_cancel = raise_on_cancel
        self.raise_on_release = raise_on_release
        self.terminal_without_result = terminal_without_result
        self.start_count = 0
        self.cancel_count = 0
        self.release_count = 0
        self.active_handles = 0
        self.handles: list[FakeLeaseHandle] = []
        self.activity = AcquisitionActivity(
            external_calls=(
                result.acquisition.external_calls
                if external_calls is None
                else external_calls
            ),
            subscriptions_created=(
                result.acquisition.subscriptions_created
                if subscriptions_created is None
                else subscriptions_created
            ),
        )

    def start(self, context: AcquisitionAttemptContext) -> FakeLeaseHandle:
        self.start_count += 1
        if self.raise_on_start:
            raise RuntimeError("start secret must not escape")
        handle = FakeLeaseHandle(self, context)
        self.handles.append(handle)
        self.active_handles += 1
        return handle


class CancellingWaiter:
    def __init__(
        self,
        clock: FakeClock,
        cancellation: MutableCancellationToken,
        *,
        cancel_at: float,
    ) -> None:
        self.clock = clock
        self.cancellation = cancellation
        self.cancel_at = cancel_at

    def __call__(self, seconds: float) -> None:
        self.clock.wait(seconds)
        if self.clock() >= self.cancel_at:
            self.cancellation.cancel()


def fixed_id_factory(values: list[str]) -> Callable[[], str]:
    iterator = iter(values)
    return lambda: next(iterator)
