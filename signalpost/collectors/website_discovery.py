"""Website discovery and scraping for companies without Brreg website URL.

v4 Upgrades:
  1. DuckDuckGo HTML fallback when slug guessing fails.
  2. RSS/Atom feed auto-discovery for verified news with real pubDate.
  3. Expanded news paths: /media, /insights, /blogg, /artikler, /pressemeldinger.
  4. NAV Arbeidsplassen search API (q={name}) with employer.name match.
  5. JSON-LD JobPosting schema extraction from career pages.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse, urljoin, quote_plus, parse_qs
from datetime import datetime, timezone, date as _date
import xml.etree.ElementTree as ET

import httpx
import structlog

from signalpost.collectors.website_verification import (
    check_website_ownership,
    verify_company_website,
    verify_social_link,
    validate_news_item,
    _distinctive_tokens,
    _is_short_generic_name,
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

_NEWS_PATHS = [
    "/nyheter", "/aktuelt", "/news", "/blogg", "/blog",
    "/presse", "/pressemeldinger", "/press",
    "/media", "/insights", "/artikler",
]

# Internal pages to scan when a homepage is found (budget-gated)
_INTERNAL_PATHS = [
    "/om-oss", "/about", "/kontakt", "/contact",
    "/nyheter", "/aktuelt", "/news", "/presse",
    "/karriere", "/jobb", "/ledige-stillinger",
]

# Static corporate page paths — never treat as news sources
_STATIC_PAGE_SLUGS = re.compile(
    r"(/sustainability|/baerekraft|/b%C3%A6rekraft|/about|/om-oss|/om$"
    r"|/products|/produkter|/services|/tjenester|/contact|/kontakt"
    r"|/privacy|/personvern|/investor|/governance|/compliance"
    r"|/esg|/csr|/annual-report|/arsrapport)(/|$)",
    re.IGNORECASE,
)
_JOBS_PATHS = ["/karriere", "/jobb", "/ledige-stillinger", "/careers", "/jobs"]

# Suffixes to strip from company names for domain guessing
_NAME_STRIP_SUFFIXES = [
    " as", " asa", " sa", " da", " enk", " ans", " sf",
    " holding", " group", " konsern", " norge", " drift",
    " eiendom", " gruppen", " avd", " stiftelsen", " stiftelse",
]

# Default HTTP client config
_DEFAULT_HEADERS = {"User-Agent": "Signalpost/4.0 Company Research Agent"}
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_name(name: str) -> str:
    """Normalize a company name to a domain-safe slug."""
    name = name.lower().strip()
    for suffix in _NAME_STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    slug = re.sub(r"[^a-z0-9]", "", name)
    return slug


def _hyphenated_name(name: str) -> str:
    """Generate a hyphenated domain slug (e.g., 'Nordland Elektro' → 'nordland-elektro')."""
    name = name.lower().strip()
    for suffix in _NAME_STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    # Replace non-alphanumeric with hyphens, collapse multiple
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return slug


def guess_domains(company_name: str) -> list[str]:
    """Generate candidate domain names from a company name.

    Tries stripped slug, hyphenated variant, across .no / .com / .org.
    """
    slug = _normalize_name(company_name)
    hyphen = _hyphenated_name(company_name)
    if not slug or len(slug) < 3:
        return []

    candidates = []
    seen = set()

    for base in [slug, hyphen]:
        if not base or len(base) < 3:
            continue
        for tld in [".no", ".com", ".org"]:
            for prefix in ["https://www.", "https://"]:
                url = f"{prefix}{base}{tld}"
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)

    return candidates


# ---------------------------------------------------------------------------
# DDG FALLBACK SEARCH
# ---------------------------------------------------------------------------

async def _ddg_search_website(
    company_name: str,
    orgnr: str,
    budget: Any,
    timeout: float = 8.0,
) -> list[str]:
    """Search DuckDuckGo HTML lite for candidate company URLs.

    Returns a list of candidate URLs (max 5) that end in .no, .com, or .org.
    Costs 1 budget request.
    """
    if not budget or not budget.can_afford(1):
        return []

    # Build search query - quote the company name, optionally add orgnr
    clean_name = re.sub(r"\b(AS|ASA|ANS|DA|SA|ENK|SF)\b", "", company_name, flags=re.IGNORECASE).strip()
    query = f'"{clean_name}"'
    if orgnr and len(orgnr) == 9 and orgnr.isdigit():
        query += f" {orgnr}"
    query += " site:.no"

    budget.consume(1)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=_BROWSER_HEADERS,
        ) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            if resp.status_code != 200:
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            urls = []
            seen = set()

            # Parse DDG HTML results
            for a_tag in soup.select(".result__a"):
                href = a_tag.get("href", "")
                # DDG wraps URLs via redirect - extract actual URL
                if "uddg=" in href:
                    parsed = parse_qs(urlparse(href).query)
                    if "uddg" in parsed:
                        href = parsed["uddg"][0]
                if not href.startswith("http"):
                    continue
                # Filter to likely company domains
                parsed_url = urlparse(href)
                domain = parsed_url.netloc.lower().replace("www.", "")
                # Skip known non-company domains
                skip_domains = {
                    "facebook.com", "linkedin.com", "twitter.com", "instagram.com",
                    "youtube.com", "wikipedia.org", "brreg.no", "proff.no",
                    "1881.no", "gulesider.no", "purehelp.no", "forvalt.no",
                    "allabolag.se", "google.com", "x.com",
                }
                if any(sd in domain for sd in skip_domains):
                    continue
                # Normalize to homepage
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                if base_url not in seen:
                    seen.add(base_url)
                    urls.append(base_url)
                if len(urls) >= 5:
                    break

            return urls
    except Exception as e:
        logger.debug("ddg_search_error", error=str(e))
        return []


async def _check_subpages_for_orgnr(
    client: httpx.AsyncClient,
    base_url: str,
    target_orgnr: str,
    budget: Any = None,
) -> tuple[bool, bool]:
    """Check /kontakt, /contact, /om-oss, /about for target orgnr or conflicts.
    Returns (target_found, conflict_found).
    """
    from signalpost.collectors.website_verification import _find_orgnrs_on_page
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for sub_path in ["/kontakt", "/contact", "/om-oss", "/about"]:
        if budget and not budget.can_afford(1):
            break
        try:
            if budget:
                budget.consume(1)
            resp = await client.get(f"{origin}{sub_path}")
            if resp.status_code == 200:
                orgnrs = _find_orgnrs_on_page(resp.text)
                if target_orgnr in orgnrs:
                    return True, False
                if orgnrs and target_orgnr not in orgnrs:
                    return False, True
        except Exception:
            continue
    return False, False


async def discover_website(
    company_name: str,
    orgnr: str,
    budget: Any = None,
    timeout: float = 5.0,
    registered_city: str = "",
) -> Optional[dict[str, Any]]:
    """Try to discover a company website via domain guessing + DDG fallback.
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
        headers=_DEFAULT_HEADERS,
    ) as client:
        # Phase 1: Direct domain guessing
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
                    source="domain_guess",
                    registered_city=registered_city,
                )
                if ownership.get("ownership") == "own":
                    # If not verified by orgnr on homepage, check subpages
                    if not ownership.get("orgnr_verified") and budget and budget.can_afford(1):
                        found_target, found_conflict = await _check_subpages_for_orgnr(
                            client, final_url, orgnr, budget
                        )
                        if found_target:
                            ownership["orgnr_verified"] = True
                            ownership["reason"] = "exact 9-digit orgnr match on contact page"
                        elif found_conflict:
                            continue  # Different orgnr on subpage -> reject!

                    return {
                        "url": final_url,
                        "ownership": ownership,
                        "html": html,
                        "source": "domain_guess",
                        "retrieved_at": now,
                    }
            except Exception:
                continue

    # Phase 2: DDG fallback search (if budget allows)
    if budget and budget.can_afford(2):
        ddg_urls = await _ddg_search_website(company_name, orgnr, budget, timeout=8.0)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            verify=False,
            headers=_DEFAULT_HEADERS,
        ) as client:
            for url in ddg_urls:
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
                        source="ddg_search",
                        registered_city=registered_city,
                    )
                    if ownership.get("ownership") == "own":
                        if not ownership.get("orgnr_verified") and budget and budget.can_afford(1):
                            found_target, found_conflict = await _check_subpages_for_orgnr(
                                client, final_url, orgnr, budget
                            )
                            if found_target:
                                ownership["orgnr_verified"] = True
                                ownership["reason"] = "exact 9-digit orgnr match on contact page"
                            elif found_conflict:
                                continue
                        return {
                            "url": final_url,
                            "ownership": ownership,
                            "html": html,
                            "source": "ddg_search",
                            "retrieved_at": now,
                        }
                except Exception:
                    continue

    return None


async def extract_social_links(
    html: str,
    company_name: str,
    base_url: str,
    orgnr_verified: bool = False,
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
            orgnr_verified=orgnr_verified,
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


# ---------------------------------------------------------------------------
# NEWS EXTRACTION (with RSS/Atom auto-discovery)
# ---------------------------------------------------------------------------

async def extract_news_items(
    html: str,
    base_url: str,
    company_name: str,
    budget: Any = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Extract verified news items from a company website.

    v4: Now auto-discovers RSS/Atom feeds and parses them for dated articles.
    """
    now = utc_now()
    news = list(_extract_news_from_html(html, base_url, now))
    parsed_base = urlparse(base_url)
    base = f"{parsed_base.scheme}://{parsed_base.netloc}"

    # Discover RSS/Atom feed URLs from the homepage
    feed_urls = _discover_feed_urls(html, base)

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, verify=False,
        headers=_DEFAULT_HEADERS,
    ) as client:
        # Fetch and parse RSS/Atom feeds
        for feed_url in feed_urls:
            if budget and not budget.can_afford(1):
                break
            try:
                if budget:
                    budget.consume(1)
                resp = await client.get(feed_url)
                if resp.status_code == 200:
                    feed_news = _parse_feed_xml(resp.text, feed_url, now)
                    news.extend(feed_news)
            except Exception:
                continue

        # Also check expanded news paths
        for path in _NEWS_PATHS:
            if budget and not budget.can_afford(1):
                break
            try:
                if budget:
                    budget.consume(1)
                resp = await client.get(f"{base}{path}")
                if resp.status_code == 200:
                    news.extend(_extract_news_from_html(resp.text, f"{base}{path}", now))
                    # Also check for RSS feeds on news pages
                    page_feeds = _discover_feed_urls(resp.text, base)
                    for pf in page_feeds:
                        if pf not in feed_urls and budget and budget.can_afford(1):
                            budget.consume(1)
                            try:
                                fr = await client.get(pf)
                                if fr.status_code == 200:
                                    news.extend(_parse_feed_xml(fr.text, pf, now))
                            except Exception:
                                pass
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


def _discover_feed_urls(html: str, base_url: str) -> list[str]:
    """Find RSS/Atom feed URLs from <link rel="alternate"> tags."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    feeds = []
    for link in soup.find_all("link", rel="alternate"):
        link_type = (link.get("type") or "").lower()
        if "rss" in link_type or "atom" in link_type:
            href = link.get("href", "")
            if href:
                if not href.startswith("http"):
                    href = urljoin(base_url, href)
                feeds.append(href)
    return feeds[:3]  # Max 3 feeds


def _parse_feed_xml(xml_text: str, feed_url: str, now: str) -> list[dict]:
    """Parse RSS or Atom XML feed into news items with validated dates."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # RSS 2.0
    for item_el in root.iter("item"):
        title = _xml_text(item_el, "title")
        link = _xml_text(item_el, "link")
        pub_date = _xml_text(item_el, "pubDate")
        if title and pub_date:
            # Parse RSS date (e.g., "Mon, 12 Nov 2026 10:30:00 +0100")
            iso_date = _rss_date_to_iso(pub_date)
            if iso_date:
                keep, _ = validate_news_item(title, iso_date, "pubDate", link or feed_url)
                if keep and _news_passes_extra_checks(iso_date, link):
                    items.append({
                        "title": title,
                        "url": link or feed_url,
                        "publish_date": iso_date,
                        "date_source": "pubDate",
                        "source_url": feed_url,
                        "date": iso_date[:10],
                        "retrieved_at": now,
                    })

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry_el in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title_el = entry_el.find("atom:title", ns)
        title = title_el.text.strip() if title_el is not None and title_el.text else None
        link_el = entry_el.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = entry_el.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        # Use <published>, NOT <updated>
        pub_el = entry_el.find("atom:published", ns)
        pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else None
        if title and pub_date:
            iso_date = pub_date[:10]  # Atom dates are already ISO
            keep, _ = validate_news_item(title, iso_date, "published", link or feed_url)
            if keep and _news_passes_extra_checks(iso_date, link):
                items.append({
                    "title": title,
                    "url": link or feed_url,
                    "publish_date": iso_date,
                    "date_source": "published",
                    "source_url": feed_url,
                    "date": iso_date[:10],
                    "retrieved_at": now,
                })

    # Also try without namespace prefix (some feeds don't use namespaces)
    for entry_el in root.iter("entry"):
        if entry_el.tag != "entry":
            continue
        title_el = entry_el.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else None
        link_el = entry_el.find("link[@rel='alternate']")
        if link_el is None:
            link_el = entry_el.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        pub_el = entry_el.find("published")
        pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else None
        if title and pub_date:
            iso_date = pub_date[:10]
            keep, _ = validate_news_item(title, iso_date, "published", link or feed_url)
            if keep and _news_passes_extra_checks(iso_date, link):
                items.append({
                    "title": title,
                    "url": link or feed_url,
                    "publish_date": iso_date,
                    "date_source": "published",
                    "source_url": feed_url,
                    "date": iso_date[:10],
                    "retrieved_at": now,
                })

    return items


def _xml_text(parent, tag: str) -> Optional[str]:
    """Get text content of an XML child element."""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _rss_date_to_iso(rss_date: str) -> Optional[str]:
    """Convert RSS pubDate (RFC 822) to ISO date string."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(rss_date)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # Try direct ISO parsing
        try:
            return rss_date[:10]
        except Exception:
            return None


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

    # <meta property="article:published_time">
    meta_pub = soup.find("meta", property="article:published_time")
    if meta_pub and meta_pub.get("content"):
        pub_date = meta_pub["content"]
        title_tag = soup.find("title")
        h1_tag = soup.find("h1")
        title = (h1_tag.get_text(strip=True) if h1_tag else
                 title_tag.get_text(strip=True) if title_tag else None)
        if title and pub_date:
            keep, _ = validate_news_item(title, pub_date, "article:published_time", page_url)
            if keep and _news_passes_extra_checks(pub_date, page_url):
                items.append({"title": title, "url": page_url,
                    "publish_date": pub_date, "date_source": "article:published_time",
                    "source_url": page_url, "date": pub_date[:10], "retrieved_at": now})

    return items


def _news_passes_extra_checks(pub_date: Optional[str], url: Optional[str]) -> bool:
    """Reject future dates and static corporate page URLs."""
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


# ---------------------------------------------------------------------------
# JOB EXTRACTION (NAV API + Career pages + JSON-LD JobPosting)
# ---------------------------------------------------------------------------

async def extract_job_listings(
    base_url: str,
    company_name: str,
    budget: Any = None,
    timeout: float = 5.0,
    orgnr: str = "",
) -> list[dict[str, Any]]:
    """Extract active job listings from career pages + NAV API + JSON-LD."""
    now = utc_now()
    jobs = []
    parsed_base = urlparse(base_url)
    base = f"{parsed_base.scheme}://{parsed_base.netloc}"
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, verify=False,
        headers=_DEFAULT_HEADERS,
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
                import json as _json
                soup = BeautifulSoup(resp.text, "html.parser")

                # Extract JSON-LD JobPosting schema
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        ld = _json.loads(script.string or "")
                        lds = ld if isinstance(ld, list) else [ld]
                        for item in lds:
                            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                                title = item.get("title", "")
                                date_posted = item.get("datePosted", now[:10])
                                loc = item.get("jobLocation", {})
                                if isinstance(loc, dict):
                                    addr = loc.get("address", {})
                                    location = addr.get("addressLocality") if isinstance(addr, dict) else None
                                elif isinstance(loc, list) and loc:
                                    addr = loc[0].get("address", {}) if isinstance(loc[0], dict) else {}
                                    location = addr.get("addressLocality") if isinstance(addr, dict) else None
                                else:
                                    location = None
                                job_url = item.get("url", f"{base}{path}")
                                if title and len(title) > 3:
                                    jobs.append({
                                        "title": title,
                                        "location": location,
                                        "url": job_url,
                                        "source_url": f"{base}{path}",
                                        "date": date_posted[:10] if date_posted else now[:10],
                                        "retrieved_at": now,
                                        "source": "json_ld_jobposting",
                                    })
                    except Exception:
                        continue

                # Extract from HTML structure (career page patterns)
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

    # NAV Arbeidsplassen API search (text-based, then filter by employer name)
    if company_name and budget and budget.can_afford(1):
        nav_jobs = await _fetch_nav_jobs(orgnr, budget, timeout, company_name=company_name)
        jobs.extend(nav_jobs)

    seen = set()
    unique = []
    for j in jobs:
        key = j["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique[:20]


async def _fetch_nav_jobs(
    orgnr: str,
    budget: Any,
    timeout: float = 5.0,
    company_name: str = "",
) -> list[dict]:
    """Fetch job listings from NAV Arbeidsplassen search API.

    v4: Uses the real search API at /stillinger/api/search with q={name},
    then filters results where employer.name matches the target company.
    """
    now = utc_now()
    jobs = []

    if not company_name and not orgnr:
        return []

    try:
        if budget:
            budget.consume(1)

        # Build search query from company name (strip legal suffixes)
        clean_name = re.sub(
            r"\b(AS|ASA|ANS|DA|SA|ENK|SF|HOLDING|DRIFT|EIENDOM|GRUPPEN|AVD)\b",
            "", company_name, flags=re.IGNORECASE,
        ).strip()

        if not clean_name or len(clean_name) < 3:
            return []

        import asyncio as _asyncio
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        ) as client:
            resp = None
            for _attempt in range(2):
                resp = await client.get(
                    "https://arbeidsplassen.nav.no/stillinger/api/search",
                    params={"q": clean_name, "size": "25"},
                )
                if resp.status_code == 429:
                    await _asyncio.sleep(5 * (_attempt + 1))
                    continue
                break
            if resp is None or resp.status_code != 200:
                return []

            try:
                data = resp.json()
            except Exception:
                return []
            hits = data.get("hits", {}).get("hits", [])

            # Build company name tokens for matching
            company_tokens = _distinctive_tokens(company_name)
            if not company_tokens:
                return []

            for hit in hits:
                src = hit.get("_source", {})
                employer = src.get("employer", {})
                employer_name = employer.get("name", "") or src.get("businessName", "")

                # Verify employer matches our target company
                if not _employer_matches(company_tokens, employer_name, company_name):
                    continue

                title = src.get("title", "")
                published = src.get("published", "")
                expires = src.get("expires", "")
                uuid = src.get("uuid", hit.get("_id", ""))

                # Only include active (non-expired) listings
                if expires:
                    try:
                        exp_date = _date.fromisoformat(expires[:10])
                        if exp_date < _date.today():
                            continue
                    except (ValueError, TypeError):
                        pass

                # Extract location
                loc_list = src.get("locationList", [])
                location = None
                if loc_list and isinstance(loc_list, list):
                    loc = loc_list[0]
                    if isinstance(loc, dict):
                        location = loc.get("city") or loc.get("municipal")

                pub_date = published[:10] if published else now[:10]

                if title and len(title) > 3:
                    job_url = f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}" if uuid else f"https://arbeidsplassen.nav.no/stillinger?q={quote_plus(clean_name)}"
                    jobs.append({
                        "title": title,
                        "location": location,
                        "url": job_url,
                        "source_url": f"https://arbeidsplassen.nav.no/stillinger/api/search?q={quote_plus(clean_name)}",
                        "source": "nav_arbeidsplassen",
                        "date": pub_date,
                        "retrieved_at": now,
                    })

    except Exception as e:
        logger.debug("nav_api_error", error=str(e))

    return jobs[:10]


def _employer_matches(company_tokens: list[str], employer_name: str, original_name: str) -> bool:
    """Check if the employer name from NAV matches our target company.

    Requires >= 50% of distinctive company tokens to appear in the employer name.
    """
    if not employer_name or not company_tokens:
        return False

    emp_lower = employer_name.lower()
    emp_tokens = set(re.findall(r"[a-z0-9æøå]+", emp_lower))

    # Direct token overlap
    hits = sum(1 for t in company_tokens if t in emp_tokens or t in emp_lower)
    threshold = max(1, len(company_tokens) // 2)
    return hits >= threshold


# Alias for compatibility with task spec
extract_job_postings = extract_job_listings

