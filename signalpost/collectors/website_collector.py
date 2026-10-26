"""Tier 2: Company website crawler using trafilatura."""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone
import structlog
import httpx

from signalpost.collectors.base import BaseCollector
from signalpost.config import USER_AGENT, HTTP_TIMEOUT
from signalpost.collectors.website_verification import (
    check_website_ownership,
    verify_social_link,
    validate_news_item,
)

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
            "news_items": [],
            "website_url": None,
            "website_status": "not_available",
            "website_ownership": None,
        }

        # Get website URL and company name from entity_data
        url = None
        company_name = ""
        if entity_data and isinstance(entity_data, dict):
            url = entity_data.get("hjemmeside")
            company_name = entity_data.get("navn", "")

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

                # ----- AUDIT RULE 1: Parent-group ownership check -----
                ownership = check_website_ownership(
                    html, final_url, org_number, company_name,
                )
                result["website_ownership"] = ownership
                suppress = ownership.get("suppress_socials", False)

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

                # ----- Extract social links with AUDIT RULE 2 -----
                social_domains = [
                    "linkedin.com", "twitter.com", "x.com",
                    "facebook.com", "instagram.com", "youtube.com",
                    "github.com",
                ]
                social_links = []
                if not suppress:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, "lxml")
                        for a_tag in soup.find_all("a", href=True):
                            href = a_tag["href"]
                            for sd in social_domains:
                                if sd in href:
                                    # Get context for agency-block detection
                                    a_html = str(a_tag)
                                    parent = a_tag.parent
                                    parent_text = parent.get_text(separator=" ", strip=True) if parent else ""

                                    keep, reason = verify_social_link(
                                        href, a_html, company_name, parent_text,
                                    )
                                    if keep:
                                        social_links.append({
                                            "platform": sd.split(".")[0],
                                            "url": href,
                                            "source": final_url,
                                            "retrieved_at": utc_now(),
                                            "verification": "passed",
                                        })
                                    else:
                                        logger.debug(
                                            "social_link_rejected",
                                            url=href, reason=reason,
                                            org=org_number,
                                        )
                                    break
                    except Exception:
                        pass
                else:
                    logger.info(
                        "social_links_suppressed",
                        reason="parent-group website",
                        org=org_number, url=final_url,
                    )

                # ----- Extract news items with AUDIT RULE 3 -----
                news_items = []
                if not suppress:
                    news_items = _extract_news(html, final_url, structured)

                result["pages"].append({
                    "url": final_url,
                    "title": _extract_title(html),
                    "main_text": (main_text or "")[:3000],
                    "retrieved_at": utc_now(),
                })
                result["structured_data"] = structured[:10]
                result["social_links"] = _dedupe_social(social_links)
                result["news_items"] = news_items

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


def _extract_news(html: str, page_url: str, structured: list[dict]) -> list[dict]:
    """Extract genuine news/blog items from structured data, validating each one."""
    news_items: list[dict] = []

    for entry in structured:
        data = entry.get("data", {})
        item_type = data.get("@type", "")

        # Look for news-like structured data types
        if item_type in ("NewsArticle", "Article", "BlogPosting", "WebPage"):
            title = data.get("headline") or data.get("name") or ""
            pub_date = data.get("datePublished")
            date_source = "datePublished" if pub_date else None

            # Fallback: check for article:published_time in OpenGraph
            if not pub_date and entry.get("syntax") == "opengraph":
                pub_date = data.get("article:published_time")
                date_source = "article:published_time" if pub_date else None

            # NEVER use modified_time or updated as publish date
            # (the validate_news_item function enforces this)

            keep, reason = validate_news_item(title, pub_date, date_source, page_url)
            if keep:
                news_items.append({
                    "title": title,
                    "published_date": pub_date,
                    "date_source": date_source,
                    "url": data.get("url") or page_url,
                    "source": page_url,
                    "retrieved_at": utc_now(),
                })

    return news_items
