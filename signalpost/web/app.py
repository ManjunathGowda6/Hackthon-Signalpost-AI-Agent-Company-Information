"""Signalpost Dashboard — Chatbot + Smart Search + Global Companies."""
import json, re, httpx
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

PROFILES: list[dict] = []
PROFILES_INDEX: dict[str, dict] = {}
ALL_COMPANIES: list[dict] = []
COMPANY_INDEX: dict[str, dict] = {}
GLOBAL_COMPANIES: list[dict] = []

SECTOR_MAP = {
    "01": "Agriculture", "02": "Forestry", "03": "Fishing & Aquaculture",
    "05": "Mining", "06": "Oil & Gas", "09": "Mining Services",
    "10": "Food Manufacturing", "13": "Textiles & Fashion",
    "16": "Wood & Paper", "20": "Chemicals & Pharma",
    "22": "Rubber & Plastics", "24": "Metals & Steel",
    "25": "Metal Products", "26": "Electronics & Semiconductors",
    "27": "Electrical Equipment", "28": "Machinery & Industrial",
    "30": "Automotive & Transport", "33": "Repair & Maintenance",
    "35": "Energy & Utilities", "41": "Construction",
    "42": "Civil Engineering", "43": "Specialized Construction",
    "45": "Auto Dealerships", "46": "Wholesale Trade",
    "47": "Retail", "49": "Land Transport & Logistics",
    "50": "Shipping & Maritime", "51": "Airlines & Aviation",
    "52": "Warehousing & Logistics", "55": "Hotels & Accommodation",
    "56": "Restaurants & Food Service", "58": "Publishing & Media",
    "59": "Film & Entertainment", "61": "Telecom",
    "62": "IT & Software", "63": "Data & Information Services",
    "64": "Banking & Finance", "65": "Insurance",
    "66": "Financial Services", "68": "Real Estate",
    "69": "Legal & Accounting", "70": "Management Consulting",
    "71": "Architecture & Engineering", "72": "R&D & Science",
    "73": "Advertising & Marketing", "74": "Design & Creative",
    "77": "Rental & Leasing", "78": "Staffing & HR",
    "79": "Travel & Tourism", "80": "Security Services",
    "81": "Facility Management", "82": "Business Support",
    "84": "Government & Public Sector", "85": "Education",
    "86": "Healthcare", "87": "Elderly & Residential Care",
    "88": "Social Services", "90": "Arts & Culture",
    "91": "Museums & Libraries", "92": "Gambling & Gaming",
    "93": "Sports & Fitness", "94": "NGOs & Associations",
    "95": "Computer Repair", "96": "Personal Services",
}


def load_profiles(path="out/signalpost_final.json"):
    global PROFILES, PROFILES_INDEX
    p = Path(path)
    if p.exists():
        PROFILES = json.loads(p.read_text(encoding="utf-8"))
        PROFILES_INDEX = {pr["organisation_number"]: pr for pr in PROFILES}
        print(f"  Loaded {len(PROFILES)} enriched profiles")


def load_company_database(path="data/all_companies.json"):
    global ALL_COMPANIES, COMPANY_INDEX
    p = Path(path)
    if p.exists():
        ALL_COMPANIES = json.loads(p.read_text(encoding="utf-8"))
        COMPANY_INDEX = {c["o"]: c for c in ALL_COMPANIES}
        print(f"  Loaded {len(ALL_COMPANIES)} companies from all sectors")


def load_global_companies():
    global GLOBAL_COMPANIES
    p = Path("data/global_companies.json")
    if p.exists():
        GLOBAL_COMPANIES = json.loads(p.read_text(encoding="utf-8"))
    print(f"  Loaded {len(GLOBAL_COMPANIES)} global companies")


def get_sector_name(code):
    return SECTOR_MAP.get(str(code), str(code))


@app.route("/")
def index():
    return render_template("index.html",
                          total_companies=len(ALL_COMPANIES),
                          total_profiles=len(PROFILES),
                          total_global=len(GLOBAL_COMPANIES))


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chatbot endpoint — answer questions about companies."""
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"reply": "Please ask me about a company!", "type": "text"})

    q = message.lower()

    # Check if asking about a global company
    for gc in GLOBAL_COMPANIES:
        name_lower = gc["name"].lower()
        if name_lower in q or any(w in q for w in name_lower.split() if len(w) > 2):
            brreg_link = ""
            if gc.get("brreg"):
                brreg_link = f'\n\n🇳🇴 **Norwegian registry**: [View in Brreg](/company/{gc["brreg"]})'
            reply = f"""## {gc['name']}
**Sector:** {gc['sector']}  
**HQ:** {gc['hq']}  
**Founded:** {gc.get('founded', 'N/A')}  
**Employees:** {gc.get('employees', 'N/A'):,}  
**Revenue:** {gc.get('revenue', 'N/A')}  
**Website:** [{gc['website']}]({gc['website']})

{gc['desc']}{brreg_link}"""
            return jsonify({"reply": reply, "type": "company", "source": "global"})

    # Check Norwegian companies
    matches = []
    for c in ALL_COMPANIES:
        n = (c.get("n") or "").lower()
        if q in n or any(w in n for w in q.split() if len(w) > 2):
            matches.append(c)
        if len(matches) >= 5:
            break

    if matches:
        if len(matches) == 1:
            c = matches[0]
            org = c["o"]
            sector = get_sector_name(c.get("s", ""))
            has_profile = org in PROFILES_INDEX
            profile_info = ""
            if has_profile:
                p = PROFILES_INDEX[org]
                ev = p.get("evidence", {}) or {}
                syn = p.get("synthesis", {}) or {}
                profile_info = f"""
**Evidence:** {ev.get('total_claims', 0)} claims ({ev.get('claims_with_source', 0)} sourced)  
**Summary:** {syn.get('summary', 'N/A')}"""
                obs = syn.get('key_observations', [])
                if obs:
                    profile_info += "\n**Observations:**\n" + "\n".join(f"- {o}" for o in obs[:5])

            reply = f"""## {c.get('n', 'Unknown')}
**Org Number:** `{org}`  
**Sector:** {sector}  
**Municipality:** {c.get('m', 'N/A')}  
**Employees:** {c.get('e', 0):,}  
**Industry:** {c.get('nd', 'N/A')}  
**Website:** {c.get('w') or 'N/A'}  
**Profile:** {'✅ Full Profile' if has_profile else '📋 Basic'}  
{profile_info}

[View Full Details →](/company/{org})"""
            return jsonify({"reply": reply, "type": "company", "source": "norwegian"})
        else:
            lines = ["I found these Norwegian companies:\n"]
            for c in matches:
                sector = get_sector_name(c.get("s", ""))
                badge = "✅" if c["o"] in PROFILES_INDEX else "📋"
                lines.append(f"- **{c.get('n')}** ({c['o']}) — {sector}, {c.get('e', 0)} employees {badge} [View](/company/{c['o']})")
            return jsonify({"reply": "\n".join(lines), "type": "list", "source": "norwegian"})

    # Try live Brreg search
    if len(q) >= 2:
        try:
            url = f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={message}&size=5"
            with httpx.Client(timeout=8) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                entities = resp.json().get("_embedded", {}).get("enheter", [])
                if entities:
                    lines = [f"Live search found {len(entities)} results:\n"]
                    for e in entities:
                        nr = e.get("organisasjonsnummer", "")
                        lines.append(f"- **{e.get('navn')}** ({nr}) — {e.get('forretningsadresse', {}).get('kommune', '')} [View](/company/{nr})")
                    return jsonify({"reply": "\n".join(lines), "type": "list", "source": "live_brreg"})
        except Exception:
            pass

    # Sector queries
    for code, name in SECTOR_MAP.items():
        if name.lower() in q:
            sector_companies = [c for c in ALL_COMPANIES if c.get("s") == code][:10]
            if sector_companies:
                lines = [f"## Top companies in **{name}**:\n"]
                for c in sector_companies:
                    badge = "✅" if c["o"] in PROFILES_INDEX else "📋"
                    lines.append(f"- **{c.get('n')}** — {c.get('e', 0)} employees {badge}")
                return jsonify({"reply": "\n".join(lines), "type": "sector", "source": "norwegian"})

    # Help
    reply = """I can help you with:
- 🔍 **Search any company** — "Tell me about Equinor" or "OpenAI"
- 🏢 **Sector browsing** — "Show IT companies" or "Banking sector"
- 🇳🇴 **Norwegian companies** — 53,000+ from the Brreg registry
- 🌍 **Global companies** — Major tech, AI, automotive companies
- 📊 **Company details** — financials, leadership, evidence

Try asking: *"What is Anthropic?"* or *"Show me IT companies"*"""
    return jsonify({"reply": reply, "type": "help"})


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip().lower()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    sector = request.args.get("sector", "").strip()

    if not q and not sector:
        filtered = ALL_COMPANIES[:per_page * page]
    else:
        filtered = []
        for c in ALL_COMPANIES:
            if sector and c.get("s") != sector:
                continue
            if q:
                if not (q in (c.get("n") or "").lower() or q in (c.get("o") or "")
                        or q in (c.get("m") or "").lower() or q in (c.get("nd") or "").lower()):
                    continue
            filtered.append(c)

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start:start + per_page]

    results = []
    for c in items:
        results.append({
            "organisation_number": c["o"],
            "name": c.get("n"),
            "legal_form": c.get("f"),
            "municipality": c.get("m"),
            "employees": c.get("e", 0),
            "nace_description": c.get("nd"),
            "sector": get_sector_name(c.get("s", "")),
            "website": c.get("w"),
            "has_full_profile": c["o"] in PROFILES_INDEX,
        })

    # Live fallback
    live_results = []
    if q and len(q) >= 2 and total < 10:
        try:
            with httpx.Client(timeout=8) as client:
                resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={q}&size=20")
            if resp.status_code == 200:
                seen = set(c["o"] for c in filtered)
                for e in resp.json().get("_embedded", {}).get("enheter", []):
                    nr = e.get("organisasjonsnummer", "")
                    if nr not in seen:
                        seen.add(nr)
                        live_results.append({
                            "organisation_number": nr,
                            "name": e.get("navn"),
                            "legal_form": e.get("organisasjonsform", {}).get("kode"),
                            "municipality": e.get("forretningsadresse", {}).get("kommune"),
                            "employees": e.get("antallAnsatte", 0) or 0,
                            "nace_description": e.get("naeringskode1", {}).get("beskrivelse"),
                            "sector": "Live",
                            "website": e.get("hjemmeside"),
                            "has_full_profile": False,
                            "source": "live",
                        })
        except Exception:
            pass

    return jsonify({"total": total + len(live_results), "local_count": total,
                    "live_count": len(live_results), "page": page, "per_page": per_page,
                    "items": results + live_results})


@app.route("/api/stats")
def api_stats():
    n = len(ALL_COMPANIES)
    sectors = {}
    for c in ALL_COMPANIES:
        s = get_sector_name(c.get("s", "??"))
        sectors[s] = sectors.get(s, 0) + 1
    top_sectors = sorted(sectors.items(), key=lambda x: -x[1])[:20]

    munis = {}
    for c in ALL_COMPANIES:
        m = c.get("m")
        if m:
            munis[m] = munis.get(m, 0) + 1
    top_munis = sorted(munis.items(), key=lambda x: -x[1])[:15]

    fin = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("financials", {}).get("status") == "available")
    roles = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("roles", {}).get("status") == "available")
    claims = sum((p.get("evidence") or {}).get("total_claims", 0) for p in PROFILES)

    return jsonify({
        "total_companies": n, "total_profiles": len(PROFILES), "total_global": len(GLOBAL_COMPANIES),
        "with_financials": fin, "with_roles": roles, "total_claims": claims,
        "top_sectors": top_sectors, "top_municipalities": top_munis,
        "sectors_count": len(sectors),
    })


@app.route("/api/sectors")
def api_sectors():
    from collections import Counter
    counts = Counter()
    for c in ALL_COMPANIES:
        s = c.get("s", "")
        counts[s] += 1
    result = [{"code": s, "name": get_sector_name(s), "count": cnt}
              for s, cnt in counts.most_common()]
    return jsonify(result)


@app.route("/api/lookup/<org_number>")
def api_lookup(org_number):
    if org_number in PROFILES_INDEX:
        return jsonify(PROFILES_INDEX[org_number])
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}")
            if resp.status_code != 200:
                return jsonify({"error": "Not found"}), 404
            entity = resp.json()
            fin_data = None
            fr = client.get(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}")
            if fr.status_code == 200:
                fin_data = fr.json()
            roles = []
            rr = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller")
            if rr.status_code == 200:
                for g in rr.json().get("rollegrupper", []):
                    rt = g.get("type", {}).get("beskrivelse", "")
                    for r in g.get("roller", []):
                        p = r.get("person", {})
                        o = r.get("enhet", {})
                        nm = ""
                        if p:
                            nm = f"{p.get('navn',{}).get('fornavn','')} {p.get('navn',{}).get('etternavn','')}".strip()
                        elif o:
                            nm = o.get("navn", "")
                        if nm:
                            roles.append({"name": nm, "role": rt})
        addr = entity.get("forretningsadresse", {})
        ap = addr.get("adresse", [])
        fa = (", ".join(ap) + f", {addr.get('postnummer','')} {addr.get('poststed','')}") if ap else None
        nace_codes = []
        for k in ["naeringskode1", "naeringskode2", "naeringskode3"]:
            n = entity.get(k)
            if n:
                nace_codes.append({"code": n["kode"], "description": n["beskrivelse"], "system": "NACE"})
        fs = {"status": "not_available"}
        if fin_data:
            items = fin_data if isinstance(fin_data, list) else [fin_data]
            if items:
                l = items[0]
                r = l.get("resultatregnskapResultat", {})
                b = l.get("eiendeler", {})
                fs = {"status": "available", "latest_filing_year": l.get("regnskapsperiode",{}).get("fraDato","")[:4],
                      "currency": "NOK",
                      "revenue": {"value": r.get("driftsresultat",{}).get("driftsinntekter",{}).get("sumDriftsinntekter")},
                      "operating_profit": {"value": r.get("driftsresultat",{}).get("driftsresultat")},
                      "total_assets": {"value": b.get("sumEiendeler")}}
        profile = {
            "organisation_number": org_number, "name": entity.get("navn"),
            "legal_form": entity.get("organisasjonsform",{}).get("kode"),
            "municipality": addr.get("kommune"), "website": entity.get("hjemmeside"),
            "status": "available", "source": "real_time",
            "legal_identity": {"status": "available", "legal_name": {"value": entity.get("navn")},
                "legal_form": {"value": entity.get("organisasjonsform",{}).get("beskrivelse")},
                "registered_address": {"value": fa},
                "registration_date": {"value": entity.get("registreringsdatoEnhetsregisteret")},
                "registration_status": {"value": "Active" if not entity.get("slettedato") else "Deleted"},
                "activity_description": {"value": entity.get("naeringskode1",{}).get("beskrivelse")},
                "industry_codes": nace_codes, "is_bankrupt": entity.get("konkurs", False)},
            "annual_accounts": fs,
            "leadership_workplaces": {"status": "available" if roles else "not_available", "roles": roles, "workplaces": []},
            "evidence": {"total_claims": 5+len(roles), "claims_with_source": 5+len(roles),
                "registry_live": {"status": "verified"}, "financials": fs,
                "roles": {"status": "available" if roles else "not_available", "count": len(roles)},
                "locations": {"status": "not_available"},
                "website": {"status": "available" if entity.get("hjemmeside") else "not_available"}},
            "synthesis": {"status": "available", "method": "real_time",
                "summary": f"{entity.get('navn')} is a {entity.get('organisasjonsform',{}).get('beskrivelse','')} based in {addr.get('kommune','')}.",
                "key_observations": [], "confidence": 0.9},
        }
        return jsonify(profile)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/company/<org_number>")
def company_detail(org_number):
    if org_number in PROFILES_INDEX:
        return render_template("company.html", profile=PROFILES_INDEX[org_number], org=org_number)
    return render_template("company_live.html", org=org_number)


@app.route("/search")
def search_page():
    return render_template("search.html", total=len(ALL_COMPANIES))


def create_app(profiles_path="out/signalpost_final.json"):
    load_profiles(profiles_path)
    load_company_database()
    load_global_companies()
    return app
