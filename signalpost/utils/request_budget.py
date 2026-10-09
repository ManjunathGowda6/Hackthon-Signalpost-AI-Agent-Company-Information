"""Request budget tracker."""
import threading
class RequestBudget:
    def __init__(self, max_requests=2000):
        self.max_requests = max_requests; self._used = 0; self._lock = threading.Lock()
    @property
    def used(self): return self._used
    @property
    def remaining(self): return max(0, self.max_requests - self._used)
    @property
    def is_exhausted(self): return self._used >= self.max_requests
    def consume(self, count=1):
        with self._lock:
            if self._used + count > self.max_requests: return False
            self._used += count; return True
    def can_afford(self, count=1): return self._used + count <= self.max_requests
