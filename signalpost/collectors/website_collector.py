"""Tier 2: Company website crawler using trafilatura."""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone
import structlog
import httpx

from signalpost.collectors.base import BaseCollector
from signalpost.config import USER_AGENT, HTTP_TIMEOUT

logger = structlog.get_logger()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WebsiteCollector(BaseCollector):
    """Crawls the official company website and extracts text + structured data."""
    source_tier = 2
    source_class = "company_website"

    async def collect(self, org_number: str, entity_data: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "pages": [],
            "structured_data": [],
            "social_links": [],
            "website_url": None,
            "website_status": "not_available",
        }

        # Get website URL from entity_data
        url = None
        if entity_data and isinstance(entity_data, dict):
            url = entity_data.get("hjemmeside")

        if not url:
            return result

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        result["website_url"] = url

        if not self.budget.can_afford(1):
            result["website_status"] = "blocked"
            return result

        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                self.budget.consume(1)

                if resp.status_code != 200:
                    result["website_status"] = "failed"
                    return result

                result["website_status"] = "available"
                html = resp.text
                final_url = str(resp.url)

                # Extract main text with trafilatura
                try:
                    import trafilatura
                    main_text = trafilatura.extract(html, include_links=True, favor_recall=True)
                except Exception:
                    main_text = None

                # Extract structured data with extruct
                structured = []
                try:
                    import extruct
                    metadata = extruct.extract(
                        html, base_url=final_url,
                        syntaxes=["json-ld", "microdata", "opengraph"],
                        uniform=True,
                    )
                    for syntax, items in metadata.items():
                        if isinstance(items, list):
                            for item in items:
                                structured.append({
                                    "syntax": syntax,
                                    "data": item,
                                })
                except Exception:
                    pass

                # Extract social links from HTML
                social_domains = [
                    "linkedin.com", "twitter.com", "x.com",
                    "facebook.com", "instagram.com", "youtube.com",
                    "github.com",
                ]
                social_links = []
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "lxml")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        for sd in social_domains:
                            if sd in href:
                                social_links.append({
                                    "platform": sd.split(".")[0],
                                    "url": href,
                                    "source": final_url,
                                    "retrieved_at": utc_now(),
                                })
                                break
                except Exception:
                    pass

                result["pages"].append({
                    "url": final_url,
                    "title": _extract_title(html),
                    "main_text": (main_text or "")[:3000],
                    "retrieved_at": utc_now(),
                })
                result["structured_data"] = structured[:10]
                result["social_links"] = _dedupe_social(social_links)

        except httpx.TimeoutException:
            logger.warning("website_timeout", url=url, org=org_number)
            result["website_status"] = "failed"
        except Exception as e:
            logger.warning("website_error", url=url, org=org_number, error=str(e))
            result["website_status"] = "failed"

        return result


def _extract_title(html: str) -> Optional[str]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        t = soup.find("title")
        return t.get_text(strip=True) if t else None
    except Exception:
        return None


def _dedupe_social(links: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for link in links:
        url = link["url"]
        if url not in seen:
            seen.add(url)
            out.append(link)
    return out
