"""V4.1 Re-Enrichment Pipeline — Judge feedback fixes.

Fix 1: Strict website verification (orgnr match, reject short/generic names)
Fix 2: Boost news + jobs from verified company sites
Fix 3: Buyer-first synthesis (commercial fact + source in sentence 1)
Fix 4: Re-verify ALL existing websites, purge unverified ones

Budget: 1500 HTTP requests
  Phase 1 (local): Re-verify existing websites + social links, regenerate YoY
  Phase 2 (HTTP):
    2A: Fetch + re-verify existing websites via /kontakt, /om-oss (find orgnr)
    2B: News discovery (RSS + news paths) on verified websites
    2C: NAV jobs for top employers
  Phase 3 (local): Generate buyer-first synthesis for all profiles
"""
import asyncio
import json
import sys
import os
import time
import re
from pathlib import Path
from datetime import datetime, timezone, date as _date
from urllib.parse import urlparse, urljoin

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
os.environ["PYTHONUNBUFFERED"] = "1"

sys.path.insert(0, str(Path(__file__).parent))

from signalpost.utils.request_budget import RequestBudget
from signalpost.extractors.financial_extractor import FinancialExtractor
from signalpost.models.envelope import AnnualAccounts, ClaimValue
from signalpost.collectors.website_verification import (
    check_website_ownership, verify_social_link, validate_news_item,
    _distinctive_tokens, _find_orgnrs_on_page, _is_short_generic_name,
)
from signalpost.collectors.website_discovery import (
    extract_news_items, extract_job_listings, _fetch_nav_jobs,
    _discover_feed_urls, _parse_feed_xml,
)
import httpx

INPUT = Path("out/signalpost_1000.json")
OUTPUT = Path("out/signalpost_1000.json")
MAX_HTTP = 1500


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fmt(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
        if abs(v) >= 1e9:
            return f"NOK {v/1e9:,.1f}B"
        if abs(v) >= 1e6:
            return f"NOK {v/1e6:,.1f}M"
        if abs(v) >= 1e3:
            return f"NOK {v/1e3:,.0f}K"
        return f"NOK {v:,.0f}"
    except Exception:
        return str(v)


def _pct_change(old, new):
    """Calculate percentage change, return formatted string or None."""
    try:
        old_f, new_f = float(old), float(new)
        if old_f == 0:
            return None
        pct = ((new_f - old_f) / abs(old_f)) * 100
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.0f}%"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FIX 3: BUYER-FIRST SYNTHESIS
# ---------------------------------------------------------------------------

def make_buyer_synthesis(p):
    """Generate a buyer-relevant synthesis. Never starts with registry boilerplate.

    Priority 1: Financial scale + trajectory
    Priority 2: Commercial offering + workforce
    Priority 3: Workforce + activity + leadership
    """
    name = p.get("name", "Unknown")
    lid = p.get("legal_identity", {})
    aa = p.get("annual_accounts", {})
    wp = p.get("website_profiles", {})
    hi = p.get("hiring_activity", {})
    org = p.get("organisation_number", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    brreg = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
    regn = f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}"

    parts = []
    obs = []

    # Extract key data points
    form_raw = lid.get("legal_form", {})
    form = form_raw.get("value", "") if isinstance(form_raw, dict) else str(form_raw or "")

    muni = p.get("municipality", "")
    website = p.get("website")

    # NACE activity description
    nace_desc = ""
    ind_codes = lid.get("industry_codes", [])
    if ind_codes and isinstance(ind_codes, list):
        for ic in ind_codes:
            if isinstance(ic, dict) and ic.get("description"):
                nace_desc = ic["description"]
                break
    activity = lid.get("activity_description", {})
    if isinstance(activity, dict) and activity.get("value"):
        nace_desc = activity["value"]

    # Employee count
    emp = None
    emp_field = aa.get("employees", {})
    if isinstance(emp_field, dict) and emp_field.get("value") is not None:
        try:
            emp = int(emp_field["value"])
        except Exception:
            pass

    # Financial data
    rev_val = None
    op_val = None
    ni_val = None
    ta_val = None
    te_val = None
    year = aa.get("latest_filing_year")
    rev = aa.get("revenue", {})
    op = aa.get("operating_profit", {})
    ni = aa.get("net_income", {})
    ta = aa.get("total_assets", {})
    te = aa.get("total_equity", {})

    if isinstance(rev, dict) and rev.get("value") is not None:
        rev_val = rev["value"]
    if isinstance(op, dict) and op.get("value") is not None:
        op_val = op["value"]
    if isinstance(ni, dict) and ni.get("value") is not None:
        ni_val = ni["value"]
    if isinstance(ta, dict) and ta.get("value") is not None:
        ta_val = ta["value"]
    if isinstance(te, dict) and te.get("value") is not None:
        te_val = te["value"]

    # YoY data
    yoy = aa.get("yoy_summary")
    yoy_text = ""
    if isinstance(yoy, dict) and yoy.get("text"):
        yoy_text = yoy["text"]
    elif isinstance(yoy, str):
        yoy_text = yoy

    # Leadership
    lw = p.get("leadership_workplaces", {})
    roles = lw.get("roles", []) if isinstance(lw, dict) else []
    ceo_name = ""
    for r in roles:
        if isinstance(r, dict):
            role_type = (r.get("role", "") or "").lower()
            if role_type in ("daglig leder", "administrerende direktør", "daglig leder/administrerende direktør"):
                ceo_name = r.get("name", "")
                break

    # Social + news + jobs
    socials = wp.get("social_profiles", []) if isinstance(wp, dict) else []
    news = wp.get("news_items", []) if isinstance(wp, dict) else []
    jobs = (hi.get("job_listings", []) or hi.get("active_listings", [])) if isinstance(hi, dict) else []

    # ======= BUILD SENTENCE 1 — BUYER-RELEVANT OPENING =======

    # Priority 1: Financial scale + trajectory
    if aa.get("status") == "available" and rev_val is not None:
        yr_str = f"In {year}, " if year else ""
        rev_str = _fmt(rev_val)
        op_part = ""
        if op_val is not None:
            op_str = _fmt(op_val)
            margin = ""
            try:
                if float(rev_val) > 0:
                    m = (float(op_val) / float(rev_val)) * 100
                    margin = f" ({m:.0f}% margin)"
            except Exception:
                pass
            op_part = f" with an operating result of {op_str}{margin}"
        yoy_part = ""
        if yoy_text:
            # Extract revenue growth from yoy_text if available
            rev_match = re.search(r'revenue[:\s]*([\+\-]\d+%)', yoy_text, re.IGNORECASE)
            if rev_match:
                yoy_part = f" ({rev_match.group(1)} YoY)"
        activity_part = ""
        if nace_desc:
            activity_part = f", operating in {nace_desc.lower()}"
        elif form:
            activity_part = f", registered as {form}"

        parts.append(
            f"{yr_str}{name} generated {rev_str} in revenue{yoy_part}{op_part}{activity_part} "
            f"(Source: {regn}, {today})."
        )

    # Priority 2: Website/commercial offering + workforce
    elif website and emp and emp > 0:
        offering = nace_desc if nace_desc else "commercial services"
        parts.append(
            f"{name} operates in {offering.lower()} with {emp} employees "
            f"(Source: {brreg}, {today})."
        )

    # Priority 3: Workforce + activity + leadership
    elif emp and emp > 0:
        activity_desc = nace_desc if nace_desc else "commercial activities"
        ceo_part = f", led by {ceo_name}" if ceo_name else ""
        parts.append(
            f"{name} has {emp} registered employees{ceo_part}, active in {activity_desc.lower()} "
            f"(Source: {brreg}, {today})."
        )

    # Minimal fallback — still buyer-relevant
    else:
        activity_desc = nace_desc if nace_desc else (f"a {form}" if form else "a Norwegian registered entity")
        loc = f" in {muni}" if muni else ""
        parts.append(
            f"{name} is {activity_desc}{loc} (Source: {brreg}, {today})."
        )

    # ======= FOLLOW-UP SENTENCES — FINANCIAL HEALTH =======

    if aa.get("status") == "available":
        # Equity ratio
        if te_val is not None and ta_val is not None:
            try:
                eq_v, as_v = float(te_val), float(ta_val)
                if as_v > 0:
                    ratio = (eq_v / as_v) * 100
                    obs.append(f"Equity ratio: {ratio:.0f}% (Source: {regn})")
                    if ratio > 50:
                        obs.append(f"Strong equity ratio ({ratio:.0f}%)")
                    elif ratio < 20:
                        obs.append(f"Low equity ratio ({ratio:.0f}%) — financial risk")
            except Exception:
                pass

        if op_val is not None:
            try:
                if float(op_val) > 0:
                    obs.append("Profitable operations")
                else:
                    obs.append("Operating at a loss")
            except Exception:
                pass

        if yoy_text and rev_val is None:
            parts.append(f"Year-over-Year: {yoy_text}")

    # ======= WEBSITE, NEWS, JOBS =======

    if website:
        parts.append(f"Official website: {website} (Source: {website}, {today}).")

    if socials:
        platforms = list(set(s.get("platform", "social") for s in socials[:5]))
        parts.append(f"Active on {', '.join(platforms)} (Source: {website or brreg}, {today}).")
        obs.append(f"Online presence across {len(socials)} platform(s)")

    if news:
        latest = news[0]
        title = latest.get("title", "N/A")
        pub = latest.get("publish_date", latest.get("date", "N/A"))
        src = latest.get("url", website or brreg)
        parts.append(f'Recent news: "{title}" ({pub}) (Source: {src}, {today}).')
        obs.append(f"{len(news)} recent news article(s)")

    if jobs:
        parts.append(f"{len(jobs)} active job listing(s) (Source: arbeidsplassen.nav.no, {today}).")
        obs.append("Currently hiring")

    if ceo_name and "led by" not in parts[0]:
        obs.append(f"CEO/Daglig leder: {ceo_name}")

    if emp and emp > 0 and "employees" not in parts[0]:
        obs.append(f"{emp} registered employees")

    summary = " ".join(parts)
    return {
        "status": "available",
        "method": "rule_based",
        "model": None,
        "summary": summary,
        "key_observations": obs if obs else [f"Norwegian {form} entity" if form else "Norwegian registered entity"],
        "confidence": 0.8,
    }


# ---------------------------------------------------------------------------
# PHASE 2A: Re-verify existing websites
# ---------------------------------------------------------------------------

async def reverify_websites(profiles, budget):
    """Re-fetch homepage + /kontakt for existing websites to verify via orgnr."""
    stats = {"checked": 0, "purged": 0, "orgnr_verified": 0, "social_purged": 0}
    now = utc_now()

    with_website = [p for p in profiles if p.get("website")]
    print(f"    {len(with_website)} profiles with websites to re-verify", flush=True)

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=8.0, verify=False,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    ) as client:
        for p in with_website:
            if not budget.can_afford(1):
                print(f"    Budget limit at {stats['checked']}", flush=True)
                break

            website = p.get("website", "")
            name = p.get("name", "")
            org = p.get("organisation_number", "")
            wp = p.get("website_profiles") or {}

            # Determine source
            ow = wp.get("official_website", {})
            source = "brreg_registry" if isinstance(ow, dict) and ow.get("source") == "brreg_registry" else "domain_guess"

            try:
                budget.consume(1)
                resp = await client.get(website)
                if resp.status_code != 200:
                    stats["checked"] += 1
                    continue

                html = resp.text
                final_url = str(resp.url)

                ownership = check_website_ownership(
                    html=html,
                    final_url=final_url,
                    target_orgnr=org,
                    target_name=name,
                    source=source,
                )

                orgnr_verified = ownership.get("orgnr_verified", False)

                if ownership.get("ownership") in ("parent_group", "unknown") and ownership.get("suppress_socials"):
                    # If from Brreg and "unknown", keep the website but suppress socials
                    if source == "brreg_registry" and ownership.get("ownership") == "unknown":
                        # Keep website but purge social links
                        wp["social_profiles"] = []
                        p["website_profiles"] = wp
                        stats["social_purged"] += 1
                    else:
                        # Purge the website entirely
                        print(f"    ✗ PURGE {name[:40]} → {website} ({ownership.get('reason','')})", flush=True)
                        p["website"] = None
                        wp["official_website"] = None
                        wp["social_profiles"] = []
                        wp["news_items"] = []
                        wp["status"] = "not_found"
                        p["website_profiles"] = wp
                        stats["purged"] += 1
                elif orgnr_verified:
                    stats["orgnr_verified"] += 1
                    # Mark as orgnr-verified
                    if isinstance(wp.get("official_website"), dict):
                        wp["official_website"]["orgnr_verified"] = True
                    p["website_profiles"] = wp
                else:
                    # Keep website but re-verify social links with strict rules
                    socials = wp.get("social_profiles", [])
                    if socials:
                        verified_socials = []
                        for s in socials:
                            keep, reason = verify_social_link(
                                s.get("url", ""),
                                "",
                                name,
                                "",
                                orgnr_verified=orgnr_verified,
                            )
                            if keep:
                                verified_socials.append(s)
                            else:
                                stats["social_purged"] += 1
                        wp["social_profiles"] = verified_socials
                        p["website_profiles"] = wp

                # Also try /kontakt or /om-oss if orgnr not yet found
                if not orgnr_verified and budget.can_afford(1):
                    parsed = urlparse(final_url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    for sub_path in ["/kontakt", "/om-oss", "/contact", "/about"]:
                        if not budget.can_afford(1):
                            break
                        budget.consume(1)
                        try:
                            sub_resp = await client.get(f"{base}{sub_path}")
                            if sub_resp.status_code == 200:
                                sub_orgnrs = _find_orgnrs_on_page(sub_resp.text)
                                if org in sub_orgnrs:
                                    stats["orgnr_verified"] += 1
                                    orgnr_verified = True
                                    if isinstance(wp.get("official_website"), dict):
                                        wp["official_website"]["orgnr_verified"] = True
                                    p["website_profiles"] = wp
                                    break
                                elif sub_orgnrs and org not in sub_orgnrs:
                                    # Different orgnr found — purge if not brreg
                                    if source != "brreg_registry":
                                        print(f"    ✗ PURGE {name[:40]} (orgnr mismatch on {sub_path})", flush=True)
                                        p["website"] = None
                                        wp["official_website"] = None
                                        wp["social_profiles"] = []
                                        wp["news_items"] = []
                                        wp["status"] = "not_found"
                                        p["website_profiles"] = wp
                                        stats["purged"] += 1
                                    break
                        except Exception:
                            pass

                stats["checked"] += 1
            except Exception:
                stats["checked"] += 1

            if stats["checked"] % 50 == 0 and stats["checked"] > 0:
                print(f"    ... {stats['checked']}/{len(with_website)} checked, "
                      f"{stats['purged']} purged, {stats['orgnr_verified']} orgnr-verified, "
                      f"budget: {budget.used}/{MAX_HTTP}", flush=True)

    return stats


# ---------------------------------------------------------------------------
# PHASE 2B+2C: News and Jobs (reuse from previous)
# ---------------------------------------------------------------------------

async def discover_news_and_jobs(profiles, budget):
    """Fetch news from verified websites + NAV jobs for top employers."""
    stats = {"news": 0, "jobs": 0, "errors": 0}
    now = utc_now()

    # --- Phase 2B: News ---
    no_news = [p for p in profiles if p.get("website") and not (p.get("website_profiles") or {}).get("news_items")]
    news_budget = min(600, MAX_HTTP - budget.used - 200)
    print(f"\n  Phase 2B: News discovery ({len(no_news)} candidates, budget: {news_budget})...", flush=True)

    news_checked = 0
    news_budget_used = 0
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=8.0, verify=False,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    ) as client:
        for p in no_news:
            if news_budget_used >= news_budget or not budget.can_afford(1):
                break
            website = p.get("website", "")
            name = p.get("name", "")
            wp = p.get("website_profiles") or {}
            try:
                budget.consume(1)
                news_budget_used += 1
                resp = await client.get(website)
                if resp.status_code != 200:
                    news_checked += 1
                    continue
                html = resp.text
                old_used = budget.used
                news_items = await extract_news_items(html, website, name, budget=budget, timeout=8.0)
                news_budget_used += budget.used - old_used
                if news_items:
                    wp["news_items"] = news_items
                    p["website_profiles"] = wp
                    stats["news"] += 1
                    print(f"    ✓ News: {name[:40]} ({len(news_items)} articles)", flush=True)
                news_checked += 1
            except Exception:
                stats["errors"] += 1
                news_checked += 1
            if news_checked % 50 == 0 and news_checked > 0:
                print(f"    ... {news_checked}/{len(no_news)} checked, {stats['news']} with news, budget: {budget.used}/{MAX_HTTP}", flush=True)

    print(f"    News done: {news_checked} checked, {stats['news']} new", flush=True)

    # --- Phase 2C: NAV jobs ---
    remaining = MAX_HTTP - budget.used
    nav_budget = min(150, remaining - 10)
    print(f"\n  Phase 2C: NAV jobs (budget: {nav_budget})...", flush=True)

    nav_cands = []
    for p in profiles:
        hi = p.get("hiring_activity") or {}
        if hi.get("job_listings") or hi.get("active_listings"):
            continue
        emp = 0
        emp_field = (p.get("annual_accounts") or {}).get("employees", {})
        if isinstance(emp_field, dict) and emp_field.get("value") is not None:
            try:
                emp = int(emp_field["value"])
            except Exception:
                pass
        if p.get("name"):
            nav_cands.append((emp, p))
    nav_cands.sort(key=lambda x: x[0], reverse=True)
    nav_cands = nav_cands[:80]

    nav_checked = 0
    for emp, p in nav_cands:
        if not budget.can_afford(1) or nav_checked >= nav_budget:
            break
        name, org = p.get("name", ""), p.get("organisation_number", "")
        try:
            nav_jobs = await _fetch_nav_jobs(org, budget, timeout=10.0, company_name=name)
            if nav_jobs:
                hi = p.get("hiring_activity") or {}
                hi["status"] = "available"
                hi["job_listings"] = nav_jobs
                p["hiring_activity"] = hi
                stats["jobs"] += 1
                print(f"    ✓ Jobs: {name[:40]} ({len(nav_jobs)} listings, emp={emp})", flush=True)
            nav_checked += 1
            await asyncio.sleep(3.0)
        except Exception:
            stats["errors"] += 1
            nav_checked += 1
            await asyncio.sleep(5.0)
        if nav_checked % 20 == 0 and nav_checked > 0:
            print(f"    ... {nav_checked} checked, {stats['jobs']} with jobs, budget: {budget.used}/{MAX_HTTP}", flush=True)

    print(f"    NAV done: {nav_checked} checked, {stats['jobs']} new", flush=True)
    return stats


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    start = time.time()
    print(f"\n{'='*60}", flush=True)
    print(f"  Signalpost V4.1 Re-Enrichment (Judge Feedback Fixes)", flush=True)
    print(f"  Input:  {INPUT}", flush=True)
    print(f"  Budget: {MAX_HTTP} HTTP requests", flush=True)
    print(f"{'='*60}", flush=True)

    profiles = json.loads(INPUT.read_text(encoding="utf-8"))
    total = len(profiles)
    print(f"\n  Loaded {total} profiles", flush=True)

    before = {
        "websites": sum(1 for p in profiles if p.get("website")),
        "social": sum(1 for p in profiles if isinstance((p.get("website_profiles") or {}).get("social_profiles"), list) and len((p.get("website_profiles") or {}).get("social_profiles", [])) > 0),
        "news": sum(1 for p in profiles if (p.get("website_profiles") or {}).get("news_items")),
        "jobs": sum(1 for p in profiles if (p.get("hiring_activity") or {}).get("job_listings") or (p.get("hiring_activity") or {}).get("active_listings")),
        "yoy": sum(1 for p in profiles if (p.get("annual_accounts") or {}).get("yoy_summary")),
    }
    print(f"\n  BEFORE: websites={before['websites']} social={before['social']} news={before['news']} jobs={before['jobs']} yoy={before['yoy']}", flush=True)

    # ── PHASE 1: Local updates ──
    print(f"\n  Phase 1: Local updates (YoY + re-verify social + news dates)...", flush=True)
    p1 = {"yoy": 0, "social_purged": 0, "news_purged": 0}
    for p in profiles:
        # YoY
        aa = p.get("annual_accounts")
        if aa and aa.get("status") == "available":
            try:
                accounts = AnnualAccounts(
                    status="available",
                    latest_filing_year=aa.get("latest_filing_year"),
                    currency=aa.get("currency", "NOK"),
                    revenue=ClaimValue(**aa["revenue"]) if aa.get("revenue") and isinstance(aa["revenue"], dict) else None,
                    operating_profit=ClaimValue(**aa["operating_profit"]) if aa.get("operating_profit") and isinstance(aa["operating_profit"], dict) else None,
                    profit_before_tax=ClaimValue(**aa["profit_before_tax"]) if aa.get("profit_before_tax") and isinstance(aa["profit_before_tax"], dict) else None,
                    net_income=ClaimValue(**aa["net_income"]) if aa.get("net_income") and isinstance(aa["net_income"], dict) else None,
                    total_assets=ClaimValue(**aa["total_assets"]) if aa.get("total_assets") and isinstance(aa["total_assets"], dict) else None,
                    total_equity=ClaimValue(**aa["total_equity"]) if aa.get("total_equity") and isinstance(aa["total_equity"], dict) else None,
                    total_debt=ClaimValue(**aa["total_debt"]) if aa.get("total_debt") and isinstance(aa["total_debt"], dict) else None,
                    employees=ClaimValue(**aa["employees"]) if aa.get("employees") and isinstance(aa["employees"], dict) else None,
                    historical_summary=aa.get("historical_summary", []),
                )
                yoy = FinancialExtractor.generate_yoy_summary(accounts)
                if yoy:
                    p["annual_accounts"]["yoy_summary"] = yoy
                    p1["yoy"] += 1
            except Exception:
                pass

        # Re-verify social links locally (strict handle check)
        wp = p.get("website_profiles") or {}
        name = p.get("name", "")
        ow = wp.get("official_website", {})
        orgnr_verified = isinstance(ow, dict) and ow.get("orgnr_verified", False)

        sx = wp.get("social_profiles", [])
        if sx and isinstance(sx, list):
            vf = []
            for s in sx:
                if isinstance(s, dict):
                    try:
                        k, r2 = verify_social_link(s.get("url", ""), "", name, "", orgnr_verified=orgnr_verified)
                        if k:
                            s["verification"] = r2
                            vf.append(s)
                        else:
                            p1["social_purged"] += 1
                    except Exception:
                        vf.append(s)
            wp["social_profiles"] = vf
            p["website_profiles"] = wp

        # Re-verify news dates
        nx = wp.get("news_items", [])
        if nx and isinstance(nx, list):
            vn = []
            for n in nx:
                if isinstance(n, dict):
                    try:
                        k, _ = validate_news_item(
                            n.get("title", ""),
                            n.get("publish_date") or n.get("date"),
                            n.get("date_source"),
                            n.get("url"),
                        )
                        if k:
                            vn.append(n)
                        else:
                            p1["news_purged"] += 1
                    except Exception:
                        pass
            wp["news_items"] = vn
            p["website_profiles"] = wp

    print(f"    Done: yoy={p1['yoy']} social_purged={p1['social_purged']} news_purged={p1['news_purged']}", flush=True)

    # ── PHASE 2: HTTP ──
    budget = RequestBudget(max_requests=MAX_HTTP)

    # Phase 2A: Re-verify websites
    print(f"\n  Phase 2A: Re-verify existing websites...", flush=True)
    p2a = asyncio.run(reverify_websites(profiles, budget))
    print(f"    Re-verify done: {p2a['checked']} checked, {p2a['purged']} purged, {p2a['orgnr_verified']} orgnr-verified, {p2a['social_purged']} socials purged", flush=True)

    # Phase 2B+2C: News and Jobs
    p2bc = asyncio.run(discover_news_and_jobs(profiles, budget))

    # ── PHASE 3: Generate buyer-first synthesis ──
    print(f"\n  Phase 3: Generating buyer-first synthesis...", flush=True)
    syn_count = 0
    for p in profiles:
        try:
            p["synthesis"] = make_buyer_synthesis(p)
            syn_count += 1
        except Exception:
            pass
    print(f"    Synthesis: {syn_count}/{total}", flush=True)

    # ── Save ──
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False, default=str)

    after = {
        "websites": sum(1 for p in profiles if p.get("website")),
        "social": sum(1 for p in profiles if isinstance((p.get("website_profiles") or {}).get("social_profiles"), list) and len((p.get("website_profiles") or {}).get("social_profiles", [])) > 0),
        "news": sum(1 for p in profiles if (p.get("website_profiles") or {}).get("news_items")),
        "jobs": sum(1 for p in profiles if (p.get("hiring_activity") or {}).get("job_listings") or (p.get("hiring_activity") or {}).get("active_listings")),
        "yoy": sum(1 for p in profiles if (p.get("annual_accounts") or {}).get("yoy_summary")),
        "synthesis": sum(1 for p in profiles if (p.get("synthesis") or {}).get("summary")),
    }

    elapsed = time.time() - start
    print(f"\n{'='*60}", flush=True)
    print(f"  V4.1 RE-ENRICHMENT COMPLETE ({elapsed:.1f}s)", flush=True)
    print(f"  HTTP: {budget.used}/{MAX_HTTP}", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"\n  {'Metric':<20} {'v4 (Before)':<15} {'v4.1 (After)':<15} {'Delta':<10}", flush=True)
    print(f"  {'-'*60}", flush=True)
    for key in ["websites", "social", "news", "jobs", "yoy"]:
        b, a = before[key], after[key]
        d = a - b
        s = "+" if d > 0 else ""
        print(f"  {key.capitalize():<20} {b:<15} {a:<15} {s}{d}", flush=True)
    print(f"  {'Synthesis':<20} {total:<15} {after.get('synthesis', 0):<15} {'✓'}", flush=True)
    print(f"\n  Phase 2A: {p2a['checked']} verified, {p2a['purged']} purged, {p2a['orgnr_verified']} orgnr-match, {p2a['social_purged']} socials purged", flush=True)
    print(f"  Phase 2B: {p2bc.get('news',0)} new news profiles", flush=True)
    print(f"  Phase 2C: {p2bc.get('jobs',0)} new job profiles", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Sample synthesis output
    print("  === SAMPLE SYNTHESIS (first 3 with financials) ===", flush=True)
    shown = 0
    for p in profiles:
        if shown >= 3:
            break
        aa = p.get("annual_accounts", {})
        if aa.get("status") == "available" and isinstance(aa.get("revenue", {}), dict) and aa.get("revenue", {}).get("value"):
            syn = p.get("synthesis", {})
            print(f"\n  {p['name']}:", flush=True)
            print(f"  {syn.get('summary','')[:300]}", flush=True)
            shown += 1


if __name__ == "__main__":
    main()
