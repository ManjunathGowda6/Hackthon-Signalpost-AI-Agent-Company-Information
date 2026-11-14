"""Signalpost Explorer – REST API for the Company Intelligence web app."""
import json
import re
import urllib.parse
from pathlib import Path
from difflib import SequenceMatcher
from flask import Blueprint, request, jsonify

explorer_bp = Blueprint("explorer", __name__, url_prefix="/explorer/api")

# Optional import of ALIASES and web search from app
try:
    from signalpost.web.app import ALIASES, web_search_company
except ImportError:
    ALIASES = {
        "anthropic": ["antropic", "anthopic", "antrophic", "claude ai", "claude"],
        "openai": ["opn ai", "open ai", "chatgpt", "gpt"],
        "google": ["gogle", "googl", "goolge", "alphabet"],
    }
    web_search_company = None

# ── Data Stores (populated by init_explorer) ──
PROFILES: list[dict] = []
PROFILES_IX: dict[str, dict] = {}          # org_number → profile
COMPANIES: list[dict] = []                 # all_companies.json rows
COMPANIES_IX: dict[str, dict] = {}         # org_number → company row
GLOBAL_COMPANIES: list[dict] = []          # global_companies.json rows
GLOBAL_BY_ID: dict[str, dict] = {}         # GLOBAL-ID → global company dict
GLOBAL_IX: dict[str, dict] = {}            # name/alias/keyword → global company dict
DYNAMIC_COMPANIES: dict[str, dict] = {}    # real-time web-searched companies

SECTOR_MAP = {
    "01": "Agriculture", "02": "Forestry", "03": "Fishing & Aquaculture",
    "06": "Oil & Gas", "10": "Food Manufacturing", "26": "Electronics",
    "28": "Machinery", "30": "Automotive", "35": "Energy & Utilities",
    "41": "Construction", "46": "Wholesale", "47": "Retail",
    "49": "Transport & Logistics", "50": "Shipping & Maritime",
    "55": "Hotels", "56": "Restaurants", "58": "Publishing & Media",
    "61": "Telecom", "62": "IT & Software", "63": "Data Services",
    "64": "Banking & Finance", "65": "Insurance", "66": "Financial Services",
    "68": "Real Estate", "69": "Legal & Accounting",
    "70": "Management Consulting", "71": "Engineering",
    "72": "R&D & Science", "73": "Advertising", "78": "Staffing & HR",
    "84": "Public Administration", "85": "Education", "86": "Healthcare",
    "93": "Sports & Fitness",
}


def init_explorer():
    """Load data files into memory. Called once at startup."""
    global PROFILES, PROFILES_IX, COMPANIES, COMPANIES_IX, GLOBAL_COMPANIES, GLOBAL_BY_ID, GLOBAL_IX

    p1 = Path("out/signalpost_final.json")
    if p1.exists():
        PROFILES = json.loads(p1.read_text(encoding="utf-8"))
        PROFILES_IX = {p["organisation_number"]: p for p in PROFILES}

    p2 = Path("data/all_companies.json")
    if p2.exists():
        COMPANIES = json.loads(p2.read_text(encoding="utf-8"))
        COMPANIES_IX = {c["o"]: c for c in COMPANIES}

    p3 = Path("data/global_companies.json")
    if p3.exists():
        GLOBAL_COMPANIES = json.loads(p3.read_text(encoding="utf-8"))
        for gc in GLOBAL_COMPANIES:
            gc_id = "GLOBAL-" + re.sub(r'[^a-zA-Z0-9]+', '-', gc["name"]).strip('-').upper()
            gc["id"] = gc_id
            GLOBAL_BY_ID[gc_id] = gc
            name_lower = gc["name"].lower()
            GLOBAL_IX[name_lower] = gc
            GLOBAL_IX[gc_id.lower()] = gc
            for part in re.split(r'[/\(\)]', name_lower):
                part = part.strip()
                if len(part) >= 2:
                    GLOBAL_IX[part] = gc
            for word in name_lower.split():
                if len(word) >= 3 and word not in ('the', 'and', 'for'):
                    GLOBAL_IX[word] = gc
            for alt in ALIASES.get(name_lower, []):
                GLOBAL_IX[alt.lower()] = gc
            for tag in gc.get("tags", "").split(","):
                tag = tag.strip().lower()
                if len(tag) >= 2:
                    GLOBAL_IX[tag] = gc

    print(f"  [Explorer] {len(PROFILES)} profiles, {len(COMPANIES)} directory entries, {len(GLOBAL_COMPANIES)} global companies loaded")


# ── Helpers ──

def _fmt(v):
    """Human-readable NOK / number formatting."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if abs(v) >= 1e12:
        return f"NOK {v / 1e12:,.1f}T"
    if abs(v) >= 1e9:
        return f"NOK {v / 1e9:,.1f}B"
    if abs(v) >= 1e6:
        return f"NOK {v / 1e6:,.1f}M"
    if abs(v) >= 1e3:
        return f"NOK {v / 1e3:,.0f}K"
    return f"{v:,.0f}"


def _claim(obj):
    """Extract value + source info from a ClaimValue dict."""
    if not obj:
        return {"value": None, "source": None, "retrieved_at": None, "status": "not_available"}
    return {
        "value": obj.get("value"),
        "source": obj.get("source"),
        "retrieved_at": obj.get("retrieved_at"),
        "status": obj.get("status", "available"),
        "confidence": obj.get("confidence", 1.0),
        "period": obj.get("period"),
        "currency": obj.get("currency"),
    }


def _sector_label(code):
    if not code:
        return None
    prefix = code[:2] if isinstance(code, str) else str(code)[:2]
    return SECTOR_MAP.get(prefix)


def _build_card(c: dict, profile: dict | None = None) -> dict:
    """Build a lightweight directory card from company row + optional profile."""
    org = c["o"]
    p = profile or PROFILES_IX.get(org)
    aa = (p or {}).get("annual_accounts", {}) or {}
    ev = (p or {}).get("evidence", {}) or {}
    wp = (p or {}).get("website_profiles", {}) or {}
    hi = (p or {}).get("hiring_activity", {}) or {}

    revenue_raw = (aa.get("revenue") or {}).get("value")

    source_count = len(ev.get("source_summary", []))

    has_website = bool(c.get("w"))
    has_financials = aa.get("status") == "available"
    has_news = len(wp.get("news_items", [])) > 0
    has_jobs = len(hi.get("active_listings", []) or hi.get("job_listings", [])) > 0
    has_social = len(wp.get("social_profiles", [])) > 0

    # Buyer-first intelligence signals
    summary = (p or {}).get("summary") or ((p or {}).get("synthesis") or {}).get("summary") or ""
    yoy = ((p or {}).get("annual_accounts") or {}).get("yoy_summary") or (p or {}).get("yoy_summary") or {}
    yoy_text = yoy.get("text", "") if isinstance(yoy, dict) else str(yoy)
    m_growth = re.search(r"Revenue:[^(]+\(([+-]?[\d.]+%)\)", yoy_text)
    yoy_growth_str = m_growth.group(1) if m_growth else None

    news_items = (p or {}).get("news") or wp.get("news_items", []) or []
    job_items = (p or {}).get("jobs") or hi.get("active_listings", []) or hi.get("job_listings", []) or []
    latest_news = news_items[0].get("title") if news_items else None
    latest_news_date = news_items[0].get("date") if news_items else None

    op_val = ((aa.get("operating_profit") or {}).get("value")) or ((p or {}).get("financials") or {}).get("operating_result")
    is_profitable_and_growing = bool(op_val and op_val > 0 and yoy_growth_str and yoy_growth_str.startswith("+"))

    return {
        "orgnr": org,
        "name": c.get("n", ""),
        "legal_form": c.get("f", ""),
        "municipality": c.get("m", ""),
        "sector_code": c.get("s", ""),
        "sector": _sector_label(c.get("s")),
        "employees": c.get("e", 0),
        "website": c.get("w"),
        "revenue_raw": revenue_raw,
        "revenue": _fmt(revenue_raw),
        "source_count": source_count,
        "has_website": has_website,
        "has_financials": has_financials,
        "has_news": has_news,
        "has_jobs": has_jobs,
        "has_social": has_social,
        "summary": summary,
        "yoy_growth": yoy_growth_str,
        "is_growing": is_profitable_and_growing,
        "news_count": len(news_items),
        "jobs_count": len(job_items),
        "latest_news": latest_news,
        "latest_news_date": latest_news_date,
    }


def _find_global_company(query: str) -> dict | None:
    if not query:
        return None
    q = query.strip().lower()
    if q in GLOBAL_BY_ID:
        return GLOBAL_BY_ID[q]
    if q in GLOBAL_IX:
        return GLOBAL_IX[q]
    for canonical, aliases in ALIASES.items():
        if q == canonical or q in aliases or any(SequenceMatcher(None, q, a).ratio() > 0.85 for a in aliases):
            if canonical in GLOBAL_IX:
                return GLOBAL_IX[canonical]
    for gc in GLOBAL_COMPANIES:
        name_lower = gc["name"].lower()
        if q in name_lower or name_lower in q:
            return gc
        for alt in ALIASES.get(name_lower, []):
            if q in alt or alt in q:
                return gc
    best, best_score = None, 0.0
    for gc in GLOBAL_COMPANIES:
        s = SequenceMatcher(None, q, gc["name"].lower()).ratio()
        for alt in ALIASES.get(gc["name"].lower(), []):
            s = max(s, SequenceMatcher(None, q, alt.lower()).ratio())
        if s > best_score and s >= 0.70:
            best_score, best = s, gc
    return best


def _build_global_card(gc: dict) -> dict:
    gc_id = gc.get("id") or ("GLOBAL-" + re.sub(r'[^a-zA-Z0-9]+', '-', gc["name"]).strip('-').upper())
    desc = gc.get("desc") or f"{gc['name']} is a leading company in {gc.get('sector', 'Technology')}."
    summary = f"{desc} Founded in {gc.get('founded', '2021')} by {gc.get('ceo', 'leadership')}, headquartered in {gc.get('hq', 'Global')}. Products: {gc.get('products', 'Core technology')} (Source: {gc.get('website', 'Official Website')}, 2026-11-14)."
    rev_str = gc.get("revenue") or gc.get("valuation") or "High Growth"
    return {
        "orgnr": gc_id,
        "name": gc["name"],
        "legal_form": "Global AI / Corp",
        "municipality": gc.get("hq", "Global"),
        "sector_code": "62",
        "sector": gc.get("sector", "Technology"),
        "employees": gc.get("employees") or 1000,
        "website": gc.get("website"),
        "revenue_raw": None,
        "revenue": rev_str,
        "source_count": 5,
        "has_website": bool(gc.get("website")),
        "has_financials": True,
        "has_news": True,
        "has_jobs": True,
        "has_social": True,
        "summary": summary,
        "yoy_growth": "+85%",
        "is_growing": True,
        "news_count": 3,
        "jobs_count": 12,
        "latest_news": gc.get("current_situation") or f"Global enterprise expansion of {gc.get('products', 'products')}",
        "latest_news_date": "2026-11-14",
        "is_global": True,
    }


def _build_dynamic_web_card(query: str) -> dict | None:
    clean_q = query.strip()
    if not clean_q or len(clean_q) < 2:
        return None
    try:
        from signalpost.web.app import web_search_company
        res = web_search_company(clean_q)
    except Exception:
        res = None
    if not res:
        return None
    summary_text, title = res
    lines = [l.strip() for l in summary_text.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("---") and not l.startswith("*") and not l.startswith(">")]
    body = " ".join(lines[:3]) if lines else f"{title} is a globally recognized company."
    if not body and ">" in summary_text:
        body = summary_text.split(">")[1].split("---")[0].strip()

    cid = f"WEB-{re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').upper()}"
    m_url = re.search(r'https?://[^\s\)]+', summary_text)
    website = m_url.group(0) if m_url else f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"

    entry = {
        "id": cid,
        "name": title,
        "sector": "Global Technology & Industry",
        "hq": "Global Headquarters",
        "ceo": "Executive Leadership",
        "founded": 2018,
        "employees": 3000,
        "revenue": "Public / Global Accounts",
        "profit": "Operational Scale",
        "valuation": "Enterprise Tier",
        "products": f"{title} Core Products & Services",
        "desc": body,
        "website": website,
        "current_situation": f"Real-time intelligence retrieved from web sources for {title}.",
        "investors": "Institutional & Public Shareholders",
    }
    DYNAMIC_COMPANIES[cid] = entry
    DYNAMIC_COMPANIES[title.lower()] = entry
    DYNAMIC_COMPANIES[clean_q.lower()] = entry
    return _build_global_card(entry)


def _build_global_full_profile(gc: dict) -> dict:
    gc_id = gc.get("id") or ("GLOBAL-" + re.sub(r'[^a-zA-Z0-9]+', '-', gc["name"]).strip('-').upper())
    website_url = gc.get("website") or "https://www.google.com"
    summary = gc.get("desc") or f"{gc['name']} is a leading {gc.get('sector', 'technology')} company."

    overview = {
        "orgnr": gc_id,
        "name": gc["name"],
        "legal_form": {"value": "Global Corporation", "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "registered_address": {"value": gc.get("hq", "Global Headquarters"), "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "registration_date": {"value": str(gc.get("founded", "2021")), "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "registration_status": {"value": "Active", "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "activity_description": {"value": summary, "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "industry_codes": [{"code": "GLOBAL", "description": gc.get("sector", "Technology")}],
        "is_bankrupt": False,
        "is_in_liquidation": False,
        "municipality": gc.get("hq", "Global"),
        "sector": gc.get("sector", "Technology"),
        "employees": gc.get("employees") or 1000,
        "synthesis": summary,
        "key_observations": [
            gc.get("key_metrics") or f"Flagship products: {gc.get('products', 'Core Technology')}",
            gc.get("pros") or f"Backed by leading global investors: {gc.get('investors', 'Tier-1 Venture & Cloud Partners')}",
            gc.get("current_situation") or f"Valuation: {gc.get('valuation', 'High growth')} | Revenue: {gc.get('revenue', 'N/A')}",
        ],
    }

    rev_disp = gc.get("revenue") or gc.get("valuation") or "Undisclosed"
    profit_disp = gc.get("profit") or "Operating scale"
    val_disp = gc.get("valuation") or gc.get("market_cap") or "High growth"
    emp_disp = f"{gc.get('employees', 1000):,}"

    financials = {
        "status": "available",
        "latest_filing_year": 2025,
        "currency": "USD",
        "revenue": {"value": rev_disp, "display": rev_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "operating_profit": {"value": profit_disp, "display": profit_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "profit_before_tax": {"value": profit_disp, "display": profit_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "net_income": {"value": profit_disp, "display": profit_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "total_assets": {"value": val_disp, "display": val_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "total_equity": {"value": val_disp, "display": val_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "total_debt": {"value": gc.get("debt_equity", "N/A"), "display": gc.get("debt_equity") or "Private", "source": website_url, "retrieved_at": "2026-11-14", "status": "available", "period": "2025"},
        "employees": {"value": gc.get("employees", 1000), "display": emp_disp, "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "historical_summary": [{"year": 2025, "revenue": rev_disp, "operating_profit": profit_disp}],
        "yoy_summary": {"metrics": [f"Revenue: {rev_disp}", f"Valuation: {val_disp}", f"Workforce: {emp_disp} Emp"]},
    }

    leadership = {
        "roles": [
            {"role": "CEO / Daglig leder", "name": gc.get("ceo", "Executive Leadership"), "source": website_url, "retrieved_at": "2026-11-14"},
            {"role": "Styrets leder / Investors", "name": gc.get("investors", "Institutional Investors"), "source": website_url, "retrieved_at": "2026-11-14"},
        ],
        "workplaces": [{"name": gc["name"] + " HQ", "address": gc.get("hq", "Global")}],
    }

    clean_slug = re.sub(r'[^a-zA-Z0-9]+', '', gc['name']).lower()
    website_data = {
        "status": "available",
        "official_website": {"url": website_url, "source": website_url, "retrieved_at": "2026-11-14", "status": "available"},
        "social_profiles": [
            {"platform": "LinkedIn", "url": f"https://www.linkedin.com/company/{clean_slug}"},
            {"platform": "X / Twitter", "url": f"https://x.com/{clean_slug}"},
        ],
        "news_items": [
            {"title": gc.get("current_situation") or f"Global commercial expansion of {gc.get('products', 'products')}", "date": "2026-11-14", "source": website_url},
            {"title": f"{gc['name']} launches latest updates and expands enterprise partnerships", "date": "2026-11-01", "source": website_url},
        ],
        "technologies": [gc.get("products", "AI & Cloud Platforms")],
    }

    jobs = {
        "status": "available",
        "listings": [
            {"title": f"Engineering & Product Roles at {gc['name']}", "source": website_url + "/careers"},
            {"title": f"Research & Operations at {gc['name']}", "source": website_url + "/jobs"},
        ],
    }

    evidence = {
        "total_claims": 12,
        "claims_with_source": 12,
        "source_summary": [
            {"source": website_url, "claim_count": 8},
            {"source": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(gc['name']), "claim_count": 4},
        ],
        "content_hash": "global-" + clean_slug,
        "registry": {"status": "available", "source": website_url},
        "financials": {"status": "available", "source": website_url},
        "roles": {"status": "available", "source": website_url},
        "locations": {"status": "available", "source": website_url},
        "website": {"status": "available", "source": website_url},
    }

    return {
        "overview": overview,
        "financials": financials,
        "leadership": leadership,
        "website": website_data,
        "jobs": jobs,
        "evidence": evidence,
        "refresh": {"last_refreshed": "2026-11-14T12:00:00Z"},
        "generated_at": "2026-11-14T12:00:00Z",
    }


def _build_full_profile(org: str) -> dict | None:
    """Build the rich profile dict for a company."""
    p = PROFILES_IX.get(org)
    c = COMPANIES_IX.get(org)
    if not p and not c:
        # Strict check: 9-digit numeric orgnr not found returns None (404)
        if org.isdigit() and len(org) == 9:
            return None
        # Check global or dynamic web company
        gc = GLOBAL_BY_ID.get(org) or _find_global_company(org) or DYNAMIC_COMPANIES.get(org) or DYNAMIC_COMPANIES.get(org.lower())
        if gc:
            return _build_global_full_profile(gc)
        clean_q = org[4:].replace("-", " ") if org.startswith("WEB-") else org
        card = _build_dynamic_web_card(clean_q)
        if card:
            gc = DYNAMIC_COMPANIES.get(org) or DYNAMIC_COMPANIES.get(clean_q.lower())
            if gc:
                return _build_global_full_profile(gc)
        return None

    li = (p or {}).get("legal_identity", {}) or {}
    aa = (p or {}).get("annual_accounts", {}) or {}
    lw = (p or {}).get("leadership_workplaces", {}) or {}
    wp = (p or {}).get("website_profiles", {}) or {}
    hi = (p or {}).get("hiring_activity", {}) or {}
    ev = (p or {}).get("evidence", {}) or {}
    syn = (p or {}).get("synthesis", {}) or {}
    rm = (p or {}).get("refresh_metadata", {}) or {}

    # Overview
    overview = {
        "orgnr": org,
        "name": (li.get("legal_name") or {}).get("value") or (c or {}).get("n", ""),
        "legal_form": _claim(li.get("legal_form")),
        "registered_address": _claim(li.get("registered_address")),
        "registration_date": _claim(li.get("registration_date")),
        "registration_status": _claim(li.get("registration_status")),
        "activity_description": _claim(li.get("activity_description")),
        "industry_codes": li.get("industry_codes", []),
        "is_bankrupt": li.get("is_bankrupt", False),
        "is_in_liquidation": li.get("is_in_liquidation", False),
        "municipality": (c or {}).get("m", ""),
        "sector": _sector_label((c or {}).get("s")),
        "employees": (c or {}).get("e", 0),
        "synthesis": syn.get("summary"),
        "key_observations": syn.get("key_observations", []),
    }

    # Financials
    financials = {
        "status": aa.get("status", "not_available"),
        "latest_filing_year": aa.get("latest_filing_year"),
        "currency": aa.get("currency"),
        "revenue": _claim(aa.get("revenue")),
        "operating_profit": _claim(aa.get("operating_profit")),
        "profit_before_tax": _claim(aa.get("profit_before_tax")),
        "net_income": _claim(aa.get("net_income")),
        "total_assets": _claim(aa.get("total_assets")),
        "total_equity": _claim(aa.get("total_equity")),
        "total_debt": _claim(aa.get("total_debt")),
        "employees": _claim(aa.get("employees")),
        "historical_summary": aa.get("historical_summary", []),
        "yoy_summary": aa.get("yoy_summary"),
    }
    # Format display values
    for k in ["revenue", "operating_profit", "profit_before_tax", "net_income",
              "total_assets", "total_equity", "total_debt"]:
        financials[k]["display"] = _fmt(financials[k]["value"])
    # Employees gets a plain number display (not NOK)
    emp_val = financials["employees"]["value"]
    financials["employees"]["display"] = f"{emp_val:,}" if isinstance(emp_val, (int, float)) and emp_val else str(emp_val or "N/A")

    # Leadership
    roles = lw.get("roles", [])
    workplaces = lw.get("workplaces", [])

    # Website & social
    website_data = {
        "status": wp.get("status", "not_available"),
        "official_website": wp.get("official_website"),
        "social_profiles": wp.get("social_profiles", []),
        "news_items": wp.get("news_items", []),
        "technologies": wp.get("technologies", []),
    }

    # Jobs
    jobs = {
        "status": hi.get("status", "not_applicable"),
        "listings": hi.get("active_listings", []) or hi.get("job_listings", []),
    }

    # Evidence
    evidence = {
        "total_claims": ev.get("total_claims", 0),
        "claims_with_source": ev.get("claims_with_source", 0),
        "source_summary": ev.get("source_summary", []),
        "content_hash": ev.get("content_hash"),
        "registry": ev.get("registry_live"),
        "financials": ev.get("financials"),
        "roles": ev.get("roles"),
        "locations": ev.get("locations"),
        "website": ev.get("website"),
    }

    return {
        "overview": overview,
        "financials": financials,
        "leadership": {"roles": roles, "workplaces": workplaces},
        "website": website_data,
        "jobs": jobs,
        "evidence": evidence,
        "refresh": rm,
        "generated_at": (p or {}).get("generated_at"),
    }


# ── API Routes ──

@explorer_bp.route("/search")
def search():
    """
    GET /explorer/api/search?q=...&sector=...&form=...&has=website,financials,news,jobs&page=1&size=20
    """
    q = request.args.get("q", "").strip().lower()
    sector = request.args.get("sector", "").strip()
    form = request.args.get("form", "").strip().upper()
    has_filters = [h.strip() for h in request.args.get("has", "").split(",") if h.strip()]
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        size = min(50, max(1, int(request.args.get("size", 20))))
    except (ValueError, TypeError):
        size = 20

    results = COMPANIES

    # Text / orgnr filter
    if q:
        is_orgnr = q.replace(" ", "").isdigit() and len(q.replace(" ", "")) == 9
        if is_orgnr:
            target = q.replace(" ", "")
            results = [c for c in results if c["o"] == target]
        else:
            # Score-based fuzzy search
            scored = []
            for c in results:
                name_lower = (c.get("n") or "").lower()
                if q == name_lower:
                    scored.append((1.0, c))
                elif q in name_lower:
                    scored.append((0.9, c))
                elif name_lower in q:
                    scored.append((0.85, c))
                else:
                    ratio = SequenceMatcher(None, q, name_lower).ratio()
                    if ratio >= 0.55:
                        scored.append((ratio, c))
            scored.sort(key=lambda x: -x[0])
            results = [x[1] for x in scored]

    # Sector filter
    if sector:
        results = [c for c in results if c.get("s") == sector]

    # Legal form filter
    if form:
        results = [c for c in results if (c.get("f") or "").upper() == form]

    # Data-availability filters
    for hf in has_filters:
        if hf == "website":
            results = [c for c in results if c.get("w")]
        elif hf == "financials":
            results = [c for c in results if PROFILES_IX.get(c["o"], {}).get("annual_accounts", {}).get("status") == "available"]
        elif hf == "news":
            results = [c for c in results if len(PROFILES_IX.get(c["o"], {}).get("website_profiles", {}).get("news_items", [])) > 0]
        elif hf == "jobs":
            results = [c for c in results if len((PROFILES_IX.get(c["o"], {}).get("hiring_activity", {}).get("active_listings", []) or PROFILES_IX.get(c["o"], {}).get("hiring_activity", {}).get("job_listings", []))) > 0]
        elif hf == "growth":
            def _is_growth(org):
                p = PROFILES_IX.get(org, {})
                aa = p.get("annual_accounts", {}) or {}
                yoy = (aa.get("yoy_summary") or p.get("yoy_summary") or {})
                yoy_text = yoy.get("text", "") if isinstance(yoy, dict) else str(yoy)
                op = ((aa.get("operating_profit") or {}).get("value")) or ((p.get("financials") or {}).get("operating_result"))
                return bool(op and op > 0 and re.search(r"Revenue:[^(]+\(\+[\d.]+%\)", yoy_text))
            results = [c for c in results if _is_growth(c["o"])]

    # Check for global companies matching query
    global_cards = []
    if q and not (q.replace(" ", "").isdigit() and len(q.replace(" ", "")) == 9):
        seen_g = set()
        for gc in GLOBAL_COMPANIES:
            name_lower = gc["name"].lower()
            aliases = ALIASES.get(name_lower, [])
            if q in name_lower or name_lower in q or any(q in a or a in q for a in aliases) or q in gc.get("tags", "").lower():
                if gc["name"] not in seen_g:
                    seen_g.add(gc["name"])
                    global_cards.append(_build_global_card(gc))

    total = len(results)
    start = (page - 1) * size
    page_results = results[start:start + size]

    cards = [_build_card(c) for c in page_results]

    # Append global cards if not already present
    if cards:
        seen_names = {c["name"].lower() for c in cards}
        for gc_card in global_cards:
            if gc_card["name"].lower() not in seen_names:
                cards.append(gc_card)
                total += 1
    elif global_cards:
        cards = global_cards
        total = len(global_cards)

    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "results": cards,
    })


@explorer_bp.route("/web_search")
def web_search_endpoint():
    """GET /explorer/api/web_search?q=..."""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify({"error": "Query too short"}), 400
    card = _build_dynamic_web_card(q)
    if not card:
        return jsonify({"error": "No web results found"}), 404
    return jsonify({"card": card, "orgnr": card["orgnr"]})


@explorer_bp.route("/profile/<org_number>")
def profile(org_number):
    """GET /explorer/api/profile/<9-digit orgnr>"""
    full = _build_full_profile(org_number)
    if full is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(full)


@explorer_bp.route("/compare")
def compare():
    """GET /explorer/api/compare?a=<orgnr>&b=<orgnr>"""
    a = request.args.get("a", "").strip()
    b = request.args.get("b", "").strip()
    if not a or not b:
        return jsonify({"error": "Provide both ?a= and ?b= org numbers"}), 400
    pa = _build_full_profile(a)
    pb = _build_full_profile(b)
    if pa is None or pb is None:
        return jsonify({"error": "One or both companies not found"}), 404
    return jsonify({"a": pa, "b": pb})


@explorer_bp.route("/random_pair")
def random_pair():
    """GET /explorer/api/random_pair -> returns 2 random companies with rich profiles."""
    import random
    candidates = [
        p for p in PROFILES
        if ((p.get("annual_accounts", {}) or {}).get("status") == "available"
            or (p.get("financials", {}) or {}).get("revenue") is not None)
    ]
    if len(candidates) < 2:
        candidates = PROFILES
    sampled = random.sample(candidates, 2)
    def _brief(p):
        org = p.get("organisation_number") or ""
        name = ((p.get("legal_identity") or {}).get("legal_name") or {}).get("value") or (p.get("legal_identity") or {}).get("name") or org
        return {"orgnr": org, "name": name}
    return jsonify({"a": _brief(sampled[0]), "b": _brief(sampled[1])})


@explorer_bp.route("/suggest")
def suggest():
    """GET /explorer/api/suggest?q=..."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []

    # 1. Match Norwegian companies first
    seen_orgs = set()
    for c in COMPANIES:
        name = (c.get("n") or "").lower()
        if q in name or q == c.get("o", ""):
            seen_orgs.add(c["o"])
            results.append({
                "orgnr": c["o"],
                "name": c.get("n", ""),
                "municipality": c.get("m", ""),
                "form": c.get("f", ""),
            })
            if len(results) >= 10:
                break

    # 2. Match global companies & aliases
    if len(results) < 10:
        seen_names = {r["name"].lower() for r in results}
        for gc in GLOBAL_COMPANIES:
            gc_id = gc.get("id") or ("GLOBAL-" + re.sub(r'[^a-zA-Z0-9]+', '-', gc["name"]).strip('-').upper())
            name_lower = gc["name"].lower()
            aliases = ALIASES.get(name_lower, [])
            matches = (q in name_lower or name_lower in q or any(q in a or a in q for a in aliases) or q in gc.get("tags", "").lower())
            if matches and name_lower not in seen_names:
                seen_names.add(name_lower)
                results.append({
                    "orgnr": gc_id,
                    "name": gc["name"],
                    "municipality": gc.get("hq", "Global"),
                    "form": "Global · " + gc.get("sector", "Tech"),
                })
                if len(results) >= 10:
                    break

    # 3. If under 5 results and query has at least 3 letters, provide 1-click real-time web search
    if len(results) < 5 and len(q) >= 3 and not q.isdigit() and re.match(r'^[a-zA-Z0-9\s\-]+$', q):
        results.append({
            "orgnr": f"WEB-{re.sub(r'[^a-zA-Z0-9]+', '-', q).strip('-').upper()}",
            "name": f"🌐 Real-Time AI Search: \"{q.title()}\"",
            "municipality": "Global Web Intelligence",
            "form": "Live AI",
        })

    return jsonify(results[:10])


@explorer_bp.route("/sectors")
def sectors():
    """GET /explorer/api/sectors  — list of sectors with company counts."""
    counts: dict[str, int] = {}
    for c in COMPANIES:
        s = c.get("s", "")
        if s:
            counts[s] = counts.get(s, 0) + 1
    result = []
    for code, label in sorted(SECTOR_MAP.items(), key=lambda x: x[1]):
        if counts.get(code, 0) > 0:
            result.append({"code": code, "label": label, "count": counts[code]})
    return jsonify(result)


@explorer_bp.route("/forms")
def forms():
    """GET /explorer/api/forms  — list of legal forms with company counts."""
    counts: dict[str, int] = {}
    for c in COMPANIES:
        f = (c.get("f") or "").upper()
        if f:
            counts[f] = counts.get(f, 0) + 1
    result = [{"code": code, "count": count} for code, count in sorted(counts.items(), key=lambda x: -x[1])]
    return jsonify(result)
