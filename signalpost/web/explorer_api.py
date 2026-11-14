"""Signalpost Explorer – REST API for the Company Intelligence web app."""
import json
import re
from pathlib import Path
from difflib import SequenceMatcher
from flask import Blueprint, request, jsonify

explorer_bp = Blueprint("explorer", __name__, url_prefix="/explorer/api")

# ── Data Stores (populated by init_explorer) ──
PROFILES: list[dict] = []
PROFILES_IX: dict[str, dict] = {}          # org_number → profile
COMPANIES: list[dict] = []                 # all_companies.json rows
COMPANIES_IX: dict[str, dict] = {}         # org_number → company row

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
    """Load data files into memory.  Called once at startup."""
    global PROFILES, PROFILES_IX, COMPANIES, COMPANIES_IX

    p1 = Path("out/signalpost_final.json")
    if p1.exists():
        PROFILES = json.loads(p1.read_text(encoding="utf-8"))
        PROFILES_IX = {p["organisation_number"]: p for p in PROFILES}

    p2 = Path("data/all_companies.json")
    if p2.exists():
        COMPANIES = json.loads(p2.read_text(encoding="utf-8"))
        COMPANIES_IX = {c["o"]: c for c in COMPANIES}

    print(f"  [Explorer] {len(PROFILES)} profiles, {len(COMPANIES)} directory entries loaded")


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


def _build_full_profile(org: str) -> dict | None:
    """Build the rich profile dict for a company."""
    p = PROFILES_IX.get(org)
    c = COMPANIES_IX.get(org)
    if not p and not c:
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

    total = len(results)
    start = (page - 1) * size
    page_results = results[start:start + size]

    cards = [_build_card(c) for c in page_results]

    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "results": cards,
    })


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


@explorer_bp.route("/suggest")
def suggest():
    """GET /explorer/api/suggest?q=..."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []
    for c in COMPANIES:
        name = (c.get("n") or "").lower()
        if q in name or q == c.get("o", ""):
            results.append({
                "orgnr": c["o"],
                "name": c.get("n", ""),
                "municipality": c.get("m", ""),
                "form": c.get("f", ""),
            })
            if len(results) >= 10:
                break
    return jsonify(results)


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
