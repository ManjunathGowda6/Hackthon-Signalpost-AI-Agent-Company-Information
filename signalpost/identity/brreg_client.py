"""Brreg API client for official registry data with SHA-256 hashing."""
from __future__ import annotations

import hashlib
from typing import Any, Optional
import structlog
import httpx

from signalpost.config import BRREG_ENHETSREGISTERET_URL, BRREG_REGNSKAPSREGISTERET_URL
from signalpost.utils.request_budget import RequestBudget

logger = structlog.get_logger()

USER_AGENT = "SignalpostAgent/1.0 (builderr.ai research agent)"
ENTITY_URL = f"{BRREG_ENHETSREGISTERET_URL}/enheter"
REGNSKAP_URL = BRREG_REGNSKAPSREGISTERET_URL


class BrregResponse:
    """Wraps an HTTP response with content hash."""
    def __init__(self, status_code: int, data: Any = None,
                 raw_bytes: bytes = b"", url: str = ""):
        self.status_code = status_code
        self.data = data
        self.raw_bytes = raw_bytes
        self.url = url
        self.sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and self.data is not None


class BrregClient:
    """Async client for data.brreg.no APIs."""
    def __init__(self, budget: Optional[RequestBudget] = None, timeout: float = 15.0):
        self.budget = budget
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def _fetch(self, url: str) -> BrregResponse:
        if self.budget and not self.budget.can_afford(1):
            logger.warning("request_budget_exhausted", url=url)
            return BrregResponse(429, None, b"", url)
        try:
            client = await self._get_client()
            resp = await client.get(url)
            if self.budget:
                self.budget.consume(1)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = None
                return BrregResponse(resp.status_code, data, resp.content, str(resp.url))
            elif resp.status_code == 404:
                return BrregResponse(404, None, resp.content, str(resp.url))
            else:
                logger.warning("brreg_http_error", url=url, status=resp.status_code)
                return BrregResponse(resp.status_code, None, resp.content, str(resp.url))
        except httpx.TimeoutException:
            logger.warning("brreg_timeout", url=url)
            return BrregResponse(408, None, b"", url)
        except Exception as e:
            logger.warning("brreg_fetch_error", url=url, error=str(e))
            return BrregResponse(500, None, b"", url)

    # ── Public API ──
    async def get_entity(self, org_number: str) -> BrregResponse:
        return await self._fetch(f"{ENTITY_URL}/{org_number}")

    async def get_roles(self, org_number: str) -> BrregResponse:
        return await self._fetch(f"{ENTITY_URL}/{org_number}/roller")

    async def get_subunits(self, org_number: str) -> BrregResponse:
        return await self._fetch(
            f"{BRREG_ENHETSREGISTERET_URL}/underenheter"
            f"?overordnetEnhet={org_number}&size=100"
        )

    async def get_financials(self, org_number: str) -> BrregResponse:
        return await self._fetch(f"{REGNSKAP_URL}/{org_number}")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
