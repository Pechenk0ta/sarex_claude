"""Limit on failed logins, against password guessing.

Kept in process memory: the app runs as a single uvicorn process (see Dockerfile), and a
restart resetting the counters is acceptable for an internal tool.
"""

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class LoginLimiter:
    max_failures: int = 5
    window_seconds: float = 15 * 60
    _failures: dict[str, deque[float]] = field(default_factory=dict)

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def blocked_for(self, keys: list[str], now: float | None = None) -> int:
        """Seconds until a new attempt is allowed (0 = allowed)."""
        moment = time.monotonic() if now is None else now
        wait = 0.0
        for key in keys:
            attempts = self._recent(key, moment)
            if len(attempts) >= self.max_failures:
                wait = max(wait, self.window_seconds - (moment - attempts[0]))
        return int(wait) + (1 if wait else 0)

    def failed(self, keys: list[str], now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        for key in keys:
            self._recent(key, moment).append(moment)

    def succeeded(self, keys: list[str]) -> None:
        for key in keys:
            self._failures.pop(key, None)


login_limiter = LoginLimiter()
