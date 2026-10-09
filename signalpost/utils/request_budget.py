"""Request budget tracker — enforces the 2000 outbound request limit."""
import threading


class RequestBudget:
    """Thread-safe request counter with a hard cap."""

    def __init__(self, max_requests: int = 2000):
        self.max_requests = max_requests
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - self._used)

    @property
    def is_exhausted(self) -> bool:
        return self._used >= self.max_requests

    def consume(self, count: int = 1) -> bool:
        """Consume request slots. Returns False if budget exceeded."""
        with self._lock:
            if self._used + count > self.max_requests:
                return False
            self._used += count
            return True

    def can_afford(self, count: int = 1) -> bool:
        """Check if we can afford `count` more requests."""
        return self._used + count <= self.max_requests

    # Alias for backward compatibility
    def can_request(self) -> bool:
        return self.can_afford(1)

    def record_request(self) -> bool:
        return self.consume(1)
