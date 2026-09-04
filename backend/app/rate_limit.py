"""Small, thread-safe rate limiter for the public API."""
from collections import defaultdict, deque
from datetime import datetime, timezone
from hashlib import sha256
from math import ceil
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    """Limit a client to ``limit`` requests in each ``window``-second interval."""

    def __init__(self, limit: int = 3, window: int = 10):
        self.limit = limit
        self.window = window
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @staticmethod
    def _key(client_identifier: str) -> str:
        """Hash a token/IP before it becomes a storage identifier."""
        return sha256(client_identifier.encode("utf-8")).hexdigest()

    def allow(self, client_identifier: str, pool=None) -> tuple[bool, int]:
        """Return whether a request is allowed and a retry delay, if any.

        Oracle is used when configured, keeping the limit consistent across Uvicorn
        workers. The in-memory fallback supports local development without Oracle.
        """
        key = self._key(client_identifier)
        if pool:
            return self._allow_oracle(key, pool)
        return self._allow_memory(key)

    def _allow_memory(self, key: str) -> tuple[bool, int]:
        now = monotonic()
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and now - timestamps[0] >= self.window:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(1, int(self.window - (now - timestamps[0])) + 1)
                return False, retry_after
            timestamps.append(now)
            return True, 0

    def _allow_oracle(self, key: str, pool) -> tuple[bool, int]:
        now = datetime.now(timezone.utc)
        with pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT window_started_at, request_count FROM ro_rate_limits "
                    "WHERE client_key=:key FOR UPDATE",
                    {"key": key},
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO ro_rate_limits (client_key, window_started_at, request_count) "
                        "VALUES (:key, SYSTIMESTAMP, 1)",
                        {"key": key},
                    )
                    connection.commit()
                    return True, 0
                started_at, count = row
                # Oracle can return TIMESTAMP WITH TIME ZONE columns as a
                # naive datetime, depending on client/session settings.
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = max(0.0, (now - started_at).total_seconds())
                if elapsed >= self.window:
                    cursor.execute(
                        "UPDATE ro_rate_limits SET window_started_at=SYSTIMESTAMP, request_count=1, "
                        "updated_at=SYSTIMESTAMP WHERE client_key=:key",
                        {"key": key},
                    )
                    connection.commit()
                    return True, 0
                if count >= self.limit:
                    connection.rollback()
                    return False, max(1, ceil(self.window - elapsed))
                cursor.execute(
                    "UPDATE ro_rate_limits SET request_count=request_count+1, updated_at=SYSTIMESTAMP "
                    "WHERE client_key=:key",
                    {"key": key},
                )
            connection.commit()
        return True, 0
