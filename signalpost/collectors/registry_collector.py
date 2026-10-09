"""Tier 1: Official registry collector — entity + roles + subunits + financials."""
from __future__ import annotations

from typing import Any
import structlog

from signalpost.collectors.base import BaseCollector
from signalpost.identity.brreg_client import BrregClient
from signalpost.identity.roles_client import RolesClient
from signalpost.identity.subunits_client import SubunitsClient

logger = structlog.get_logger()


class RegistryCollector(BaseCollector):
    """Collects all official registry data for a company."""
    source_tier = 1
    source_class = "official_registry"

    def __init__(self, budget=None):
        super().__init__(budget)
        self.brreg = BrregClient(budget=budget)
        self.roles_client = RolesClient(self.brreg)
        self.subunits_client = SubunitsClient(self.brreg)

    async def collect(self, org_number: str, entity_data: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entity": entity_data,
            "roles": [],
            "subunits": [],
            "financials_data": None,
        }

        # If we don't already have entity data, fetch it
        if entity_data is None:
            entity_resp = await self.brreg.get_entity(org_number)
            if entity_resp.ok:
                result["entity"] = entity_resp.data
            else:
                return result

        # Fetch roles
        try:
            result["roles"] = await self.roles_client.get_leadership(org_number)
        except Exception as e:
            logger.warning("roles_fetch_error", org=org_number, error=str(e))

        # Fetch subunits / workplaces
        try:
            result["subunits"] = await self.subunits_client.get_workplaces(org_number)
        except Exception as e:
            logger.warning("subunits_fetch_error", org=org_number, error=str(e))

        # Fetch financial data from Regnskapsregisteret
        try:
            fin_resp = await self.brreg.get_financials(org_number)
            if fin_resp.ok:
                result["financials_data"] = fin_resp.data
        except Exception as e:
            logger.warning("financials_fetch_error", org=org_number, error=str(e))

        return result

    async def close(self):
        await self.brreg.close()
