"""Brreg API client - identity anchor."""
import structlog
from signalpost.config import BRREG_ENHETSREGISTERET_URL
from signalpost.utils.http_client import HttpClient
from signalpost.utils.request_budget import RequestBudget

logger = structlog.get_logger()
ENTITY_URL = f"{BRREG_ENHETSREGISTERET_URL}/enheter"

class BrregClient:
    def __init__(self, budget=None):
        self.http = HttpClient(budget=budget)

    async def get_entity(self, org_number):
        url = f"{ENTITY_URL}/{org_number}"
        logger.info("brreg_fetch", org_nr=org_number)
        resp = await self.http.get(url)
        if resp is None: return None
        if resp.status_code == 404: return None
        if resp.status_code != 200: return None
        return resp.json()

    async def get_roles(self, org_number):
        resp = await self.http.get(f"{ENTITY_URL}/{org_number}/roller")
        if resp and resp.status_code == 200: return resp.json()
        return None

    async def get_subunits(self, org_number):
        resp = await self.http.get(f"{BRREG_ENHETSREGISTERET_URL}/underenheter?overordnetEnhet={org_number}")
        if resp and resp.status_code == 200:
            return resp.json().get("_embedded",{}).get("underenheter",[])
        return []

    async def close(self): await self.http.close()
