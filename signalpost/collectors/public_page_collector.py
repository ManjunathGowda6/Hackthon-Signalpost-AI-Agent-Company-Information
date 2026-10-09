"""Tier 4: Public page collector."""
from signalpost.collectors.base import BaseCollector
class PublicPageCollector(BaseCollector):
    source_tier = 4; source_class = "public_page"
    async def collect(self, org_number, entity_data): return {"pages":[]}
