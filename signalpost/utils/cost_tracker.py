"""API cost tracker — enforces the $10 budget limit."""
import threading


class CostTracker:
    """Thread-safe cost tracker with a hard cap."""

    def __init__(self, max_cost_usd: float = 10.0):
        self.max_cost_usd = max_cost_usd
        self._total_cost = 0.0
        self._lock = threading.Lock()
        self._breakdown: dict[str, float] = {}

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def remaining(self) -> float:
        return max(0.0, self.max_cost_usd - self._total_cost)

    @property
    def is_exhausted(self) -> bool:
        return self._total_cost >= self.max_cost_usd

    def add_cost(self, amount: float, category: str = "general") -> bool:
        """Add cost. Returns False if budget exceeded."""
        with self._lock:
            if self._total_cost + amount > self.max_cost_usd:
                return False
            self._total_cost += amount
            self._breakdown[category] = self._breakdown.get(category, 0.0) + amount
            return True

    def can_afford(self, amount: float) -> bool:
        """Check if we can afford an additional cost."""
        return self._total_cost + amount <= self.max_cost_usd

    @property
    def breakdown(self) -> dict[str, float]:
        return dict(self._breakdown)
