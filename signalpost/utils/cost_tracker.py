"""API cost tracker."""
import threading
class CostTracker:
    def __init__(self, max_cost_usd=10.0):
        self.max_cost_usd = max_cost_usd; self._total_cost = 0.0
        self._lock = threading.Lock(); self._breakdown = {}
    @property
    def total_cost(self): return self._total_cost
    @property
    def remaining(self): return max(0.0, self.max_cost_usd - self._total_cost)
    @property
    def is_exhausted(self): return self._total_cost >= self.max_cost_usd
    def add_cost(self, amount, category="general"):
        with self._lock:
            if self._total_cost + amount > self.max_cost_usd: return False
            self._total_cost += amount
            self._breakdown[category] = self._breakdown.get(category, 0.0) + amount; return True
    def can_afford(self, amount): return self._total_cost + amount <= self.max_cost_usd
