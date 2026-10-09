"""Tier 3: Licensed API collector."""
from signalpost.collectors.base import BaseCollector
class ApiCollector(BaseCollector):
    source_tier = 3; source_class = "licensed_api"
    async def collect(self, org_number, entity_data): return {"api_results":[]}
