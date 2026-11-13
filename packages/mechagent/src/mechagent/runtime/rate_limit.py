"""Studio API 的进程内滑动窗口限流。"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitDecision:
    """一次请求的限流判定。"""

    allowed: bool
    limit: int | None
    remaining: int | None
    retry_after: int


class SlidingWindowRateLimiter:
    """按 key 记录请求时间的进程内滑动窗口限流器。

    ``limit=None`` 表示不启用限流。计数只存在于当前进程，适用于单机或由
    外部网关负责跨实例协调的受控内网部署。
    """

    def __init__(
        self,
        limit: int | None = 120,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if limit is not None and limit < 1:
            raise ValueError("rate limit 必须为正整数或 None。")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("rate limit 窗口必须是正有限数值。")
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        """记录一次请求并返回是否允许继续处理。"""

        if self._limit is None:
            return RateLimitDecision(True, None, None, 0)
        now = self._clock()
        cutoff = now - self._window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                retry_after = max(1, math.ceil(events[0] + self._window_seconds - now))
                return RateLimitDecision(False, self._limit, 0, retry_after)
            events.append(now)
            return RateLimitDecision(True, self._limit, self._limit - len(events), 0)
