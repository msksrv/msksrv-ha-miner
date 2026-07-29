"""Rolling median/MAD statistics with a bounded sample window."""

from __future__ import annotations

import statistics
from collections import deque
from typing import Any


class RollingStats:
    """Bounded-window median and MAD (median absolute deviation)."""

    __slots__ = ("max_samples", "_samples", "sample_count", "first_at", "last_at")

    def __init__(self, max_samples: int = 360) -> None:
        self.max_samples = max_samples
        self._samples: deque[float] = deque(maxlen=max_samples)
        self.sample_count = 0
        self.first_at: str | None = None
        self.last_at: str | None = None

    def add(self, value: float, *, timestamp: str | None = None) -> None:
        self._samples.append(float(value))
        self.sample_count += 1
        if self.first_at is None and timestamp:
            self.first_at = timestamp
        if timestamp:
            self.last_at = timestamp

    def median(self) -> float | None:
        if not self._samples:
            return None
        return float(statistics.median(self._samples))

    def mad(self) -> float | None:
        if len(self._samples) < 2:
            return None
        med = statistics.median(self._samples)
        return float(statistics.median(abs(x - med) for x in self._samples))

    def ready(self, min_samples: int = 10) -> bool:
        return len(self._samples) >= min_samples

    def is_outlier(self, value: float, *, min_samples: int = 20) -> bool:
        """True when value should not update the baseline."""
        if len(self._samples) < min_samples:
            return False
        med = self.median()
        mad = self.mad()
        if med is None:
            return False
        spread = mad if mad and mad > 0 else abs(med) * 0.1
        return abs(value - med) > max(spread * 3, abs(med) * 0.25)

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": list(self._samples),
            "sample_count": self.sample_count,
            "first_at": self.first_at,
            "last_at": self.last_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, max_samples: int = 360) -> RollingStats:
        obj = cls(max_samples=max_samples)
        if not data:
            return obj
        obj.sample_count = int(data.get("sample_count") or 0)
        obj.first_at = data.get("first_at")
        obj.last_at = data.get("last_at")
        for val in data.get("samples") or []:
            try:
                obj._samples.append(float(val))
            except (TypeError, ValueError):
                pass
        return obj
