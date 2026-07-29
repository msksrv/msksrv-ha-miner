"""Confirm/recovery timers for repair issues."""

from __future__ import annotations

import time

from .definitions import RECOVERY_SECONDS


class RepairLifecycle:
    """Track how long conditions stay active or cleared."""

    def __init__(self, recovery_seconds: float = RECOVERY_SECONDS) -> None:
        self._recovery_seconds = recovery_seconds
        self._active_since: dict[str, float] = {}
        self._recovery_since: dict[str, float] = {}

    def confirmed(self, key: str, condition: bool, now: float, confirm_seconds: float) -> bool:
        """True when *condition* held continuously for *confirm_seconds*."""
        if not condition:
            self._active_since.pop(key, None)
            return False
        start = self._active_since.setdefault(key, now)
        if confirm_seconds <= 0:
            return True
        return (now - start) >= confirm_seconds

    def should_clear(self, key: str, condition: bool, now: float) -> bool:
        """True when *condition* cleared for recovery period."""
        if condition:
            self._recovery_since.pop(key, None)
            return False
        if key not in self._recovery_since:
            self._recovery_since[key] = now
            return False
        return (now - self._recovery_since[key]) >= self._recovery_seconds

    def reset_key(self, key: str) -> None:
        self._active_since.pop(key, None)
        self._recovery_since.pop(key, None)

    def reset_all(self) -> None:
        self._active_since.clear()
        self._recovery_since.clear()


def monotonic_now() -> float:
    return time.monotonic()
