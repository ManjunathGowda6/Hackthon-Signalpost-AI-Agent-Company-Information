"""Base collector interface."""
from abc import ABC, abstractmethod
from signalpost.utils.request_budget import RequestBudget
class BaseCollector(ABC):
    def __init__(self, budget=None): self.budget = budget or RequestBudget()
    @abstractmethod
    async def collect(self, org_number, entity_data): ...
    @property
    @abstractmethod
    def source_tier(self): ...
    @property
    @abstractmethod
    def source_class(self): ...
