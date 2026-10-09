"""Tier 1: Official registry collector."""
from signalpost.collectors.base import BaseCollector
from signalpost.identity.brreg_client import BrregClient
from signalpost.identity.roles_client import RolesClient
from signalpost.identity.subunits_client import SubunitsClient

class RegistryCollector(BaseCollector):
    source_tier = 1; source_class = "official_registry"
    def __init__(self, budget=None):
        super().__init__(budget)
        self.brreg = BrregClient(budget=budget)
        self.roles = RolesClient(self.brreg); self.subunits = SubunitsClient(self.brreg)
    async def collect(self, org_number, entity_data=None):
        result = {"entity":entity_data, "roles":[], "subunits":[], "financials":None}
        try: result["roles"] = [r.model_dump() for r in await self.roles.get_leadership(org_number)]
        except: pass
        try: result["subunits"] = await self.subunits.get_workplaces(org_number)
        except: pass
        return result
