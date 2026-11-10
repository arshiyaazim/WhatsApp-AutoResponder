from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from collections import defaultdict, deque

from .env import secret_value


class RateLimitUnavailable(RuntimeError):
    pass


class RateLimiter:
    """Shared Redis sliding-window limiter; memory mode is for single-process development only."""

    _SCRIPT = """
    local key = KEYS[1]
    local redis_time = redis.call('TIME')
    local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
    local window = tonumber(ARGV[1])
    local maximum = tonumber(ARGV[2])
    local token = ARGV[3]
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    local n = redis.call('ZCARD', key)
    if n >= maximum then return 0 end
    redis.call('ZADD', key, now, token)
    redis.call('EXPIRE', key, window + 5)
    return 1
    """

    def __init__(self) -> None:
        self.backend = os.getenv("RATE_LIMIT_BACKEND", "redis").strip().lower()
        if self.backend not in {"memory", "redis"}:
            raise RuntimeError("RATE_LIMIT_BACKEND must be 'memory' or 'redis'")
        self.window = max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
        self.key_prefix = os.getenv("RATE_LIMIT_KEY_PREFIX", "whatsapp_autoresponder").strip().strip(":") or "whatsapp_autoresponder"
        if len(self.key_prefix) > 80 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-" for char in self.key_prefix):
            raise RuntimeError("RATE_LIMIT_KEY_PREFIX contains unsupported characters")
        self._lock = threading.Lock()
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None
        if self.backend == "redis":
            url = secret_value("RATE_LIMIT_REDIS_URL")
            if not url:
                raise RuntimeError("RATE_LIMIT_REDIS_URL is required when RATE_LIMIT_BACKEND=redis")
            try:
                import redis
                self._redis = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1,
                                                   health_check_interval=30, decode_responses=True)
            except Exception:
                raise RuntimeError("Could not configure the shared rate-limit backend") from None

    def ready(self) -> bool:
        if self.backend == "memory":
            return True
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def allow(self, identity: str, limit: int) -> bool:
        key = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()
        if self.backend == "redis":
            try:
                return bool(self._redis.eval(self._SCRIPT, 1, f"{self.key_prefix}:rate:{key}",
                                             self.window, limit, uuid.uuid4().hex))
            except Exception as exc:
                raise RateLimitUnavailable("shared rate-limit backend unavailable") from exc
        now = time.monotonic()
        with self._lock:
            if key not in self._requests and len(self._requests) >= 4096:
                for address in list(self._requests):
                    current = self._requests[address]
                    while current and now - current[0] >= self.window:
                        current.popleft()
                    if not current:
                        self._requests.pop(address, None)
                    if len(self._requests) < 4096:
                        break
                if len(self._requests) >= 4096:
                    self._requests.pop(next(iter(self._requests)), None)
            queue = self._requests[key]
            while queue and now - queue[0] >= self.window:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
        return True
