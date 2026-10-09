"""Brreg API client for official registry data with SHA-256 hashing."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional
import structlog
import httpx

from signalpost.config import BRREG_ENHETSREGISTERET_URL, BRREG_REGNSKAPSREGISTERET_URL
from signalpost.utils.request_budget import RequestBudget

logger = structlog.get_logger()

USER_AGENT = "SignalpostAgent/1.0 (+https://builderr.ai)"
ENTITY_URL = f"{BRREG_ENHETSREGISTERET_URL}/enheter"
REGNSKAP_URL = f"{BRREG_REGNSKAPSREGISTERET_URL}/regnskap"


class BrregResponse:
    def __init__(self, status_code: int, data: Any = None, raw_bytes: bytes = b"", url: str = ""):
        self.status_code = status_code
        self.data = data
        self.raw_bytes = raw_bytes
        self.url = url
        self.sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None


class BrregClient:
    def __init__(self, budget: Optional[RequestBudget] = None, timeout: float = 10.0):
        self.budget = budget
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )

    async def _fetch(self, url: str) -> BrregResponse:
        if self.budget and not self.budget.can_request():
            logger.warning("request_budget_exhausted", url=url)
            return BrregResponse(429, None, b"", url)
        try:
            resp = await self.client.get(url)
            if self.budget:
                self.budget.record_request()
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = None
                return BrregResponse(resp.status_code, data, resp.content, str(resp.url))
            elif resp.status_code == 404:
                return BrregResponse(404, None, resp.content, str(resp.url))
            else:
                return BrregResponse(resp.status_code, None, resp.content, str(resp.url))
        except Exception as e:
            logger.warning("brreg_fetch_error", url=url, error=str(e))
            return BrregResponse(500, None, b"", url)

    async def get_entity(self, org_number: str) -> BrregResponse:
        url = f"{ENTITY_URL}/{org_number}"
        return await self._fetch(url)

    async def get_roles(self, org_number: str) -> BrregResponse:
        url = f"{ENTITY_URL}/{org_number}/roller"
        return await self._fetch(url)

    async def get_subunits(self, org_number: str) -> BrregResponse:
        url = f"{BRREG_ENHETSREGISTERET_URL}/underenheter?overordnetEnhet={org_number}&size=100"
        return await self._fetch(url)

    async def get_financials(self, org_number: str) -> BrregResponse:
        url = f"{REGNSKAP_URL}/{org_number}"
        return await self._fetch(url)

    async def get_financial_years(self, org_number: str) -> BrregResponse:
        url = f"{REGNSKAP_URL}/aarsregnskap/kopi/{org_number}/aar"
        return await self._fetch(url)

    async def close(self):
        await self.client.aclose()
