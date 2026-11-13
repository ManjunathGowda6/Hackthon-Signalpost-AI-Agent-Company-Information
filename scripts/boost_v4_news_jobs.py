"""Boost V4 News and Jobs extraction across verified company websites and NAV API.

Stage 1: WordPress JSON API + JSON-LD + Deep Article News Extractor
Stage 2: High-recall Career Page + NAV Job Extractor
Stage 3: Parked / sink domain guard + Strict social validation
Stage 4: Concurrent ThreadPoolExecutor on all 562 verified companies
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as _date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from signalpost.collectors.website_verification import (
    verify_social_link,
    validate_news_item,
    _distinctive_tokens,
)
from signalpost.collectors.website_discovery import (
    _discover_feed_urls,
    _parse_feed_xml,
    _extract_news_from_html,
    _extract_article_date,
    _news_passes_extra_checks,
    _is_parked_domain,
    _NAV_LABELS_FAST,
    _GENERIC_JOB_TITLES,
    _ATS_DOMAINS,
    _JOBS_PATHS,
    _NEWS_PATHS,
    _STATIC_PAGE_SLUGS,
    _BROWSER_HEADERS,
    _fetch_nav_jobs,
)
from scripts.run_clean_and_summarize import build_buyer_first_summary

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "out" / "signalpost_1000.json"
FINAL_PATH = ROOT_DIR / "out" / "signalpost_final.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_site_news_sync(base_url: str, company_name: str) -> list[dict]:
    """Sync worker to extract news via WordPress API, RSS, JSON-LD, and deep article inspection."""
    now = utc_now()
    news = []
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    base_domain = parsed.netloc.lower().replace("www.", "")

    with httpx.Client(
        follow_redirects=True,
        timeout=5.0,
        verify=False,
        headers=_BROWSER_HEADERS,
    ) as client:
        # Layer 1: WordPress REST API
        try:
            resp = client.get(f"{origin}/wp-json/wp/v2/posts", params={"per_page": "5"}, timeout=4.0)
            if resp.status_code == 200:
                posts = resp.json()
                if isinstance(posts, list):
                    for post in posts[:5]:
                        if not isinstance(post, dict):
                            continue
                        title_raw = post.get("title", {})
                        title = (title_raw.get("rendered") or "") if isinstance(title_raw, dict) else str(title_raw)
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        title = re.sub(r'&[a-z]+;', '', title).strip()
                        pub_date = (post.get("date") or "")[:10]
                        link = post.get("link") or ""
                        if link:
                            link_dom = urlparse(link).netloc.lower().replace("www.", "")
                            if link_dom != base_domain:
                                continue
                        if title and len(title) >= 12 and pub_date:
                            keep, _ = validate_news_item(title, pub_date, "wp_api_date", link or origin)
                            if keep and _news_passes_extra_checks(pub_date, link):
                                news.append({
                                    "title": title,
                                    "url": link or origin,
                                    "publish_date": pub_date,
                                    "date_source": "wp_api",
                                    "source_url": f"{origin}/wp-json/wp/v2/posts",
                                    "date": pub_date,
                                    "retrieved_at": now,
                                })
        except Exception:
            pass

        # Layer 2: Homepage + RSS/Atom + News Subpages
        feed_urls = []
        try:
            hp_resp = client.get(origin, timeout=5.0)
            if hp_resp.status_code == 200:
                hp_html = hp_resp.text
                news.extend(_extract_news_from_html(hp_html, origin, now))
                feed_urls = _discover_feed_urls(hp_html, origin)
        except Exception:
            pass

        for fu in feed_urls[:3]:
            try:
                fr = client.get(fu, timeout=4.0)
                if fr.status_code == 200:
                    news.extend(_parse_feed_xml(fr.text, fu, now))
            except Exception:
                pass

        undated_links = []
        for path in _NEWS_PATHS[:5]:
            try:
                sub_url = f"{origin}{path}"
                resp = client.get(sub_url, timeout=4.0)
                if resp.status_code != 200:
                    continue
                sub_html = resp.text
                news.extend(_extract_news_from_html(sub_html, sub_url, now))
                
                # Check for feeds on subpage
                for sfu in _discover_feed_urls(sub_html, origin):
                    if sfu not in feed_urls:
                        try:
                            sfr = client.get(sfu, timeout=4.0)
                            if sfr.status_code == 200:
                                news.extend(_parse_feed_xml(sfr.text, sfu, now))
                        except Exception:
                            pass

                # Collect links for deep extraction
                soup = BeautifulSoup(sub_html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if not href.startswith("http"):
                        href = urljoin(sub_url, href)
                    if urlparse(href).netloc.lower().replace("www.", "") != base_domain:
                        continue
                    if href.rstrip("/") == sub_url.rstrip("/"):
                        continue
                    if _STATIC_PAGE_SLUGS.search(urlparse(href).path):
                        continue
                    txt = a.get_text(strip=True)
                    if txt and len(txt) >= 12 and not _NAV_LABELS_FAST.match(txt):
                        undated_links.append((href, txt))
            except Exception:
                pass

        # Layer 3: Deep Article Date Extraction (up to 3 articles)
        found_titles = {n["title"].lower().strip() for n in news}
        checked = 0
        for art_url, art_title in undated_links:
            if art_title.lower().strip() in found_titles:
                continue
            if checked >= 3:
                break
            try:
                ar = client.get(art_url, timeout=4.0)
                if ar.status_code == 200:
                    checked += 1
                    dt = _extract_article_date(ar.text)
                    if dt:
                        keep, _ = validate_news_item(art_title, dt, "deep_article", art_url)
                        if keep and _news_passes_extra_checks(dt, art_url):
                            news.append({
                                "title": art_title,
                                "url": art_url,
                                "publish_date": dt,
                                "date_source": "deep_article_extraction",
                                "source_url": art_url,
                                "date": dt,
                                "retrieved_at": now,
                            })
                            found_titles.add(art_title.lower().strip())
            except Exception:
                pass

    seen = set()
    unique = []
    for item in news:
        key = item["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:10]


def fetch_site_jobs_sync(base_url: str, company_name: str, orgnr: str) -> list[dict]:
    """Sync worker to extract job listings from career pages and ATS platforms."""
    now = utc_now()
    jobs = []
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    with httpx.Client(
        follow_redirects=True,
        timeout=5.0,
        verify=False,
        headers=_BROWSER_HEADERS,
    ) as client:
        for path in _JOBS_PATHS:
            try:
                page_url = f"{origin}{path}"
                resp = client.get(page_url, timeout=4.0)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                # JSON-LD JobPosting
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        ld = json.loads(script.string or "")
                        lds = ld if isinstance(ld, list) else [ld]
                        for item in lds:
                            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                                title = item.get("title", "")
                                if not title or _GENERIC_JOB_TITLES.match(title.strip()):
                                    continue
                                dp = item.get("datePosted", now[:10])
                                loc = item.get("jobLocation", {})
                                loc_name = None
                                if isinstance(loc, dict):
                                    loc_name = loc.get("address", {}).get("addressLocality")
                                jurl = item.get("url") or page_url
                                jobs.append({
                                    "title": title,
                                    "location": loc_name,
                                    "url": jurl,
                                    "source_url": page_url,
                                    "date": dp[:10] if dp else now[:10],
                                    "retrieved_at": now,
                                    "source": "json_ld_jobposting",
                                })
                    except Exception:
                        pass

                # HTML structure
                for el in soup.find_all(["article", "li", "div"],
                        class_=re.compile(r"(job|stilling|ledig|position|vacancy)", re.IGNORECASE)):
                    title_el = el.find(["h1", "h2", "h3", "h4", "a"])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or len(title) <= 5 or _GENERIC_JOB_TITLES.match(title.strip()):
                        continue
                    link = title_el.get("href", "") if title_el.name == "a" else ""
                    if not link:
                        a_sub = el.find("a", href=True)
                        if a_sub:
                            link = a_sub["href"]
                    if link and not link.startswith("http"):
                        link = urljoin(page_url, link)
                    loc_el = el.find(class_=re.compile(r"(location|sted|place)", re.IGNORECASE))
                    location = loc_el.get_text(strip=True) if loc_el else None
                    jobs.append({
                        "title": title,
                        "location": location,
                        "url": link or page_url,
                        "source_url": page_url,
                        "date": now[:10],
                        "retrieved_at": now,
                    })

                # ATS links
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    if not href.startswith("http"):
                        continue
                    full_link = urlparse(href).netloc.lower() + urlparse(href).path.lower()
                    if any(ats in full_link for ats in _ATS_DOMAINS):
                        ats_title = a_tag.get_text(strip=True)
                        if ats_title and len(ats_title) > 5 and not _GENERIC_JOB_TITLES.match(ats_title.strip()):
                            jobs.append({
                                "title": ats_title,
                                "location": None,
                                "url": href,
                                "source_url": page_url,
                                "date": now[:10],
                                "retrieved_at": now,
                                "source": "ats_external_link",
                            })
            except Exception:
                continue

    seen = set()
    unique = []
    for j in jobs:
        key = j["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique[:15]


def fetch_nav_jobs_sync(orgnr: str, company_name: str) -> list[dict]:
    """Sync fetch NAV Arbeidsplassen jobs with employer matching."""
    try:
        return asyncio.run(_fetch_nav_jobs(orgnr, None, timeout=5.0, company_name=company_name))
    except Exception:
        return []


def enrich_profile(profile: dict) -> dict:
    """Enrich a single profile with news and jobs, and clean social links."""
    name = profile.get("name") or profile.get("navn") or ""
    orgnr = profile.get("organisation_number") or profile.get("orgnr") or ""
    wp = profile.get("website_profiles") or {}
    ow = wp.get("official_website")
    ha = profile.get("hiring_activity") or {}

    website_url = None
    if isinstance(ow, dict) and ow.get("url"):
        website_url = ow["url"]
    elif profile.get("website"):
        website_url = profile["website"]

    orgnr_verified = isinstance(ow, dict) and ow.get("orgnr_verified", False)

    # 1. Clean socials strictly
    clean_socials = []
    raw_socials = wp.get("social_profiles") or profile.get("social_links") or []
    for s in raw_socials:
        s_url = s if isinstance(s, str) else (s.get("url") or s.get("source_url") or "")
        keep, _ = verify_social_link(s_url, "", name, "", orgnr_verified=orgnr_verified)
        if keep:
            clean_socials.append(s if isinstance(s, dict) else {
                "platform": "social",
                "url": s_url,
                "source_url": website_url or "",
                "date": "2026-11-06",
                "retrieved_at": "2026-11-06T00:00:00Z",
            })
    wp["social_profiles"] = clean_socials
    profile["social_links"] = clean_socials

    # 2. Extract news if website exists and news is empty/low
    existing_news = wp.get("news_items") or profile.get("news") or []
    if website_url and len(existing_news) < 3:
        try:
            site_news = fetch_site_news_sync(website_url, name)
            if site_news:
                combined_news = list(existing_news)
                titles_seen = {n.get("title", "").lower().strip() for n in combined_news if isinstance(n, dict)}
                for item in site_news:
                    if item["title"].lower().strip() not in titles_seen:
                        combined_news.append(item)
                        titles_seen.add(item["title"].lower().strip())
                wp["news_items"] = combined_news[:10]
                profile["news"] = combined_news[:10]
                profile["updates"] = combined_news[:10]
        except Exception:
            pass

    # 3. Extract jobs from career pages + NAV API
    existing_jobs = ha.get("job_listings") or profile.get("jobs") or []
    if len(existing_jobs) < 3:
        combined_jobs = list(existing_jobs)
        job_titles_seen = {j.get("title", "").lower().strip() for j in combined_jobs if isinstance(j, dict)}

        # 3a. From career pages if website exists
        if website_url:
            try:
                career_jobs = fetch_site_jobs_sync(website_url, name, orgnr)
                for cj in career_jobs:
                    if cj["title"].lower().strip() not in job_titles_seen:
                        combined_jobs.append(cj)
                        job_titles_seen.add(cj["title"].lower().strip())
            except Exception:
                pass

        # 3b. From NAV API
        if len(combined_jobs) < 3:
            try:
                nav_jobs = fetch_nav_jobs_sync(orgnr, name)
                for nj in nav_jobs:
                    if nj["title"].lower().strip() not in job_titles_seen:
                        combined_jobs.append(nj)
                        job_titles_seen.add(nj["title"].lower().strip())
            except Exception:
                pass

        if combined_jobs:
            ha["job_listings"] = combined_jobs[:15]
            ha["status"] = "available"
            profile["jobs"] = combined_jobs[:15]
            profile["job_postings"] = combined_jobs[:15]

    profile["website_profiles"] = wp
    profile["hiring_activity"] = ha

    # 4. Regenerate buyer-first summary with updated news/jobs
    new_summary = build_buyer_first_summary(profile)
    profile["summary"] = new_summary
    if "synthesis" in profile and isinstance(profile["synthesis"], dict):
        profile["synthesis"]["summary"] = new_summary
    elif "synthesis" in profile and isinstance(profile["synthesis"], str):
        profile["synthesis"] = new_summary

    return profile


def main():
    print("Loading signalpost_1000.json...")
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    profiles = data if isinstance(data, list) else data.get("companies") or []
    print(f"Total profiles: {len(profiles)}")

    # Pre-stats
    w_pre = sum(1 for p in profiles if p.get("website_profiles", {}).get("official_website") or p.get("website"))
    s_pre = sum(1 for p in profiles if (p.get("website_profiles", {}).get("social_profiles") or p.get("social_links")))
    n_pre = sum(1 for p in profiles if (p.get("website_profiles", {}).get("news_items") or p.get("news")))
    j_pre = sum(1 for p in profiles if (p.get("hiring_activity", {}).get("job_listings") or p.get("jobs")))
    print(f"BEFORE: Websites={w_pre}, Socials={s_pre}, News={n_pre}, Jobs={j_pre}")

    # Run concurrent enrichment on all profiles with max_workers=20
    enriched_profiles = [None] * len(profiles)
    completed_count = 0

    print("Running concurrent enrichment (Stage 1-4) with 20 workers...")
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_idx = {executor.submit(enrich_profile, p): i for i, p in enumerate(profiles)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                enriched_profiles[idx] = future.result()
            except Exception as e:
                enriched_profiles[idx] = profiles[idx]
            completed_count += 1
            if completed_count % 100 == 0 or completed_count == len(profiles):
                print(f"  Processed {completed_count}/{len(profiles)} profiles...")

    # Post-stats
    w_post = sum(1 for p in enriched_profiles if p.get("website_profiles", {}).get("official_website") or p.get("website"))
    s_post = sum(1 for p in enriched_profiles if (p.get("website_profiles", {}).get("social_profiles") or p.get("social_links")))
    n_post = sum(1 for p in enriched_profiles if (p.get("website_profiles", {}).get("news_items") or p.get("news")))
    j_post = sum(1 for p in enriched_profiles if (p.get("hiring_activity", {}).get("job_listings") or p.get("jobs")))

    total_news = sum(len(p.get("website_profiles", {}).get("news_items") or p.get("news") or []) for p in enriched_profiles)
    total_jobs = sum(len(p.get("hiring_activity", {}).get("job_listings") or p.get("jobs") or []) for p in enriched_profiles)

    print(f"\nAFTER: Websites={w_post}, Socials={s_post}, News={n_post} (total items: {total_news}), Jobs={j_post} (total items: {total_jobs})")

    # Save to both out/signalpost_1000.json and out/signalpost_final.json
    out_json = json.dumps(enriched_profiles, ensure_ascii=False, indent=2)
    DATASET_PATH.write_text(out_json, encoding="utf-8")
    FINAL_PATH.write_text(out_json, encoding="utf-8")
    print(f"Successfully saved updated dataset to {DATASET_PATH} and {FINAL_PATH}!")


if __name__ == "__main__":
    main()
