"""Tier 2: Company website crawler."""
from signalpost.collectors.base import BaseCollector
class WebsiteCollector(BaseCollector):
    source_tier = 2; source_class = "company_website"
    async def collect(self, org_number, entity_data):
        return {"pages":[], "structured_data":[], "social_links":[]}
