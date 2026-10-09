"""Rate-limited async HTTP client."""
import asyncio, hashlib
import httpx
from signalpost.config import HTTP_TIMEOUT, USER_AGENT, HTTP_MAX_RETRIES
from signalpost.utils.request_budget import RequestBudget

class HttpClient:
    def __init__(self, budget=None):
        self.budget = budget or RequestBudget(); self._client = None
    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent":USER_AGENT}, follow_redirects=True)
        return self._client
    async def get(self, url, **kw):
        if not self.budget.consume(1): return None
        client = await self._get_client()
        for attempt in range(HTTP_MAX_RETRIES):
            try: return await client.get(url, **kw)
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == HTTP_MAX_RETRIES-1: raise
                await asyncio.sleep(1.0*(attempt+1))
        return None
    async def close(self):
        if self._client and not self._client.is_closed: await self._client.aclose()
    @staticmethod
    def hash_content(content): return hashlib.sha256(content).hexdigest()
