"""Tiny simulated database layer used by the demo project (read-only demo code)."""
import time


class DatabaseConnectionTimeout(Exception):
    """Raised when no connection can be acquired from the pool in time."""


class Database:
    def __init__(self, pool_size=10, acquire_timeout=5.0):
        self.pool_size = pool_size
        self.acquire_timeout = acquire_timeout
        self._in_use = 0

    def _acquire_connection(self):
        deadline = time.monotonic() + self.acquire_timeout
        while self._in_use >= self.pool_size:
            if time.monotonic() > deadline:
                raise DatabaseConnectionTimeout(
                    f"Timed out after {self.acquire_timeout}s waiting for a connection "
                    f"(pool_size={self.pool_size})"
                )
            time.sleep(0.05)
        self._in_use += 1

    def execute(self, query, params=()):
        self._acquire_connection()
        try:
            return {"query": query, "params": params, "rows": []}
        finally:
            self._in_use -= 1
