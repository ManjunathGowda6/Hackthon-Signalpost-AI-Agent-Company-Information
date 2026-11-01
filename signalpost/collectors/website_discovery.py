"""Website discovery and scraping for companies without Brreg website URL.

Upgrade 1: Active Website & Social Discovery with strict verification.
Upgrade 2: News & job extraction from verified company websites.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse
from datetime import datetime, timezone

import httpx
import structlog

from signalpost.collectors.website_verification import (
    check_website_ownership, verify_social_link, validate_news_item,
    _distinctive_tokens,
)

logger = structlog.get_logger()

_SOCIAL_DOMAINS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "youtube.com": "youtube",
}

_NEWS_PATHS = ["/nyheter", "/aktuelt", "/news", "/blogg", "/blog"]

# Static corporate page paths — never treat as news sources
_STATIC_PAGE_SLUGS = re.compile(
    r"(/sustainability|/baerekraft|/b%C3%A6rekraft|/about|/om-oss|/om$"
    r"|/products|/produkter|/services|/tjenester|/contact|/kontakt"
    r"|/privacy|/personvern|/investor|/governance|/compliance"
    r"|/esg|/csr|/annual-report|/arsrapport)(/|$)",
    re.IGNORECASE,
)
_JOBS_PATHS = ["/karriere", "/jobb", "/ledige-stillinger", "/careers", "/jobs"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_name(name: str) -> str:
    """Normalize a company name to a domain-safe slug."""
    name = name.lower().strip()
    for suffix in [" as", " asa", " sa", " da", " enk", " ans",
                   " holding", " group", " konsern", " norge"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    slug = re.sub(r"[^a-z0-9]", "", name)
    return slug


def guess_domains(company_name: str) -> list[str]:
    """Generate candidate domain names from a company name."""
    slug = _normalize_name(company_name)
    if not slug or len(slug) < 3:
        return []
    candidates = []
    for tld in [".no", ".com"]:
        candidates.append(f"https://www.{slug}{tld}")
        candidates.append(f"https://{slug}{tld}")
    return candidates


async def discover_website(
    company_name: str,
    orgnr: str,
    budget: Any = None,
    timeout: float = 5.0,
) -> Optional[dict[str, Any]]:
    """Try to discover a company website via domain guessing.
    Returns a dict with {url, ownership, html, source} if verified, else None.
    """
    candidates = guess_domains(company_name)
    if not candidates:
        return None

    now = utc_now()
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        verify=False,
        headers={"User-Agent": "Signalpost/2.0 Company Research Agent"},
    ) as client:
        for url in candidates:
            if budget and not budget.can_afford(1):
                break
            try:
                if budget:
                    budget.consume(1)
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                html = resp.text
                final_url = str(resp.url)
                ownership = check_website_ownership(
                    html=html,
                    target_orgnr=orgnr,
                    target_name=company_name,
                    final_url=final_url,
                )
                if ownership.get("ownership") == "own":
                    return {
                        "url": final_url,
                        "ownership": ownership,
                        "html": html,
                        "source": "domain_guess",
                        "retrieved_at": now,
                    }
            except Exception:
                continue
    return None


async def extract_social_links(
    html: str,
    company_name: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Extract verified social media links from a page's HTML."""
    from bs4 import BeautifulSoup
    now = utc_now()
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen_urls = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href.startswith("http"):
            continue
        parsed = urlparse(href)
        domain = parsed.netloc.lower().replace("www.", "")
        platform = None
        for sd, pname in _SOCIAL_DOMAINS.items():
            if sd in domain:
                platform = pname
                break
        if not platform or href in seen_urls:
            continue
        seen_urls.add(href)
        parent = a_tag.parent
        parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
        a_html = str(a_tag)
        keep, reason = verify_social_link(
            link_url=href,
            link_element_html=a_html,
            target_name=company_name,
            parent_context_text=parent_text,
        )
        if keep:
            found.append({
                "platform": platform,
                "url": href,
                "source_url": base_url,
                "date": now[:10],
                "retrieved_at": now,
                "verification": reason,
            })
    return found


async def extract_news_items(
    html: str,
    base_url: str,
    company_name: str,
    budget: Any = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Extract verified news items from a company website."""
    now = utc_now()
    news = list(_extract_news_from_html(html, base_url, now))
    parsed_base = urlparse(base_url)
    base = f"{parsed_base.scheme}://{parsed_base.netloc}"
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, verify=False,
        headers={"User-Agent": "Signalpost/2.0"},
    ) as client:
        for path in _NEWS_PATHS:
            if budget and not budget.can_afford(1):
                break
            try:
                if budget:
                    budget.consume(1)
                resp = await client.get(f"{base}{path}")
                if resp.status_code == 200:
                    news.extend(_extract_news_from_html(resp.text, f"{base}{path}", now))
            except Exception:
                continue
    seen = set()
    unique = []
    for item in news:
        key = item["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:10]


def _extract_news_from_html(html: str, page_url: str, now: str) -> list[dict]:
    from bs4 import BeautifulSoup
    import json as _json
    soup = BeautifulSoup(html, "html.parser")
    items = []
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = _json.loads(script.string or "")
            lds = ld if isinstance(ld, list) else [ld]
            for item in lds:
                if isinstance(item, dict):
                    ld_type = item.get("@type", "")
                    if ld_type in ("NewsArticle", "Article", "BlogPosting"):
                        title = item.get("headline") or item.get("name", "")
                        pub_date = item.get("datePublished")
                        url = item.get("url") or page_url
                        if title and pub_date:
                            keep, _ = validate_news_item(title, pub_date, "datePublished", url)
                            if keep and _news_passes_extra_checks(pub_date, url):
                                items.append({"title": title, "url": url,
                                    "publish_date": pub_date, "date_source": "datePublished",
                                    "source_url": page_url, "date": pub_date[:10], "retrieved_at": now})
        except Exception:
            continue
    # <article> with <time>
    for article in soup.find_all("article"):
        title_el = article.find(["h1", "h2", "h3", "h4"])
        time_el = article.find("time", datetime=True)
        link_el = article.find("a", href=True)
        if title_el:
            title = title_el.get_text(strip=True)
            pub_date = time_el["datetime"] if time_el else None
            date_source = "<time datetime>" if time_el else None
            url = link_el["href"] if link_el else page_url
            if not url.startswith("http"):
                p = urlparse(page_url)
                url = f"{p.scheme}://{p.netloc}{url}"
            keep, _ = validate_news_item(title, pub_date, date_source, url)
            if keep and _news_passes_extra_checks(pub_date, url):
                items.append({"title": title, "url": url,
                    "publish_date": pub_date, "date_source": date_source,
                    "source_url": page_url, "date": pub_date[:10] if pub_date else now[:10],
                    "retrieved_at": now})
    return items


def _news_passes_extra_checks(pub_date: Optional[str], url: Optional[str]) -> bool:
    """Reject future dates and static corporate page URLs."""
    from datetime import date as _date
    # Reject future dates
    if pub_date:
        try:
            parsed = _date.fromisoformat(pub_date[:10])
            if parsed > _date.today():
                return False
        except (ValueError, TypeError):
            pass
    # Reject static corporate page URLs
    if url and _STATIC_PAGE_SLUGS.search(urlparse(url).path):
        return False
    return True


async def extract_job_listings(
    base_url: str,
    company_name: str,
    budget: Any = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Extract active job listings from career pages."""
    now = utc_now()
    jobs = []
    parsed_base = urlparse(base_url)
    base = f"{parsed_base.scheme}://{parsed_base.netloc}"
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, verify=False,
        headers={"User-Agent": "Signalpost/2.0"},
    ) as client:
        for path in _JOBS_PATHS:
            if budget and not budget.can_afford(1):
                break
            try:
                if budget:
                    budget.consume(1)
                resp = await client.get(f"{base}{path}")
                if resp.status_code != 200:
                    continue
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for el in soup.find_all(["article", "li", "div"],
                        class_=re.compile(r"(job|stilling|ledig|position|vacancy)", re.IGNORECASE)):
                    title_el = el.find(["h1", "h2", "h3", "h4", "a"])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "") if title_el.name == "a" else ""
                    if link and not link.startswith("http"):
                        link = f"{base}{link}"
                    loc_el = el.find(class_=re.compile(r"(location|sted|place)", re.IGNORECASE))
                    location = loc_el.get_text(strip=True) if loc_el else None
                    if title and len(title) > 5:
                        jobs.append({"title": title, "location": location,
                            "url": link or f"{base}{path}",
                            "source_url": f"{base}{path}",
                            "date": now[:10], "retrieved_at": now})
            except Exception:
                continue
    seen = set()
    unique = []
    for j in jobs:
        key = j["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique[:20]
