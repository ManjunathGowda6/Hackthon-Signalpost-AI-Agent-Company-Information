"""Signalpost Web Dashboard -- with real-time Brreg search."""
import json
import httpx
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

PROFILES: list[dict] = []
PROFILES_INDEX: dict[str, dict] = {}


def load_profiles(path: str = "out/signalpost_final.json"):
    global PROFILES, PROFILES_INDEX
    p = Path(path)
    if p.exists():
        PROFILES = json.loads(p.read_text(encoding="utf-8"))
        PROFILES_INDEX = {pr["organisation_number"]: pr for pr in PROFILES}
        print(f"  Loaded {len(PROFILES)} profiles from {path}")
    else:
        print(f"  Warning: {path} not found.")


@app.route("/")
def index():
    return render_template("index.html", total=len(PROFILES))


@app.route("/api/profiles")
def api_profiles():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search = request.args.get("q", "").strip().lower()
    form_filter = request.args.get("form", "").strip().upper()

    filtered = PROFILES
    if search:
        filtered = [
            p for p in filtered
            if search in (p.get("name") or "").lower()
            or search in (p.get("organisation_number") or "")
            or search in (p.get("municipality") or "").lower()
        ]
    if form_filter:
        filtered = [p for p in filtered if (p.get("legal_form") or "") == form_filter]

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start:start + per_page]

    slim = []
    for p in items:
        ev = p.get("evidence") or {}
        slim.append({
            "organisation_number": p.get("organisation_number"),
            "name": p.get("name"),
            "legal_form": p.get("legal_form"),
            "municipality": p.get("municipality"),
            "status": p.get("status"),
            "has_financials": (ev.get("financials") or {}).get("status") == "available",
            "has_roles": (ev.get("roles") or {}).get("status") == "available",
            "has_website": bool(p.get("website")),
            "total_claims": ev.get("total_claims", 0),
        })
    return jsonify({"total": total, "page": page, "per_page": per_page, "items": slim})


@app.route("/api/profiles/<org_number>")
def api_profile_detail(org_number):
    profile = PROFILES_INDEX.get(org_number)
    if not profile:
        return jsonify({"error": "Not found"}), 404
    return jsonify(profile)


@app.route("/api/stats")
def api_stats():
    n = len(PROFILES)
    if n == 0:
        return jsonify({})
    avail = sum(1 for p in PROFILES if p.get("status") == "available")
    fin = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("financials", {}).get("status") == "available")
    roles = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("roles", {}).get("status") == "available")
    web = sum(1 for p in PROFILES if p.get("website"))
    claims = sum((p.get("evidence") or {}).get("total_claims", 0) for p in PROFILES)
    sourced = sum((p.get("evidence") or {}).get("claims_with_source", 0) for p in PROFILES)

    forms = {}
    munis = {}
    for p in PROFILES:
        f = p.get("legal_form", "Unknown")
        forms[f] = forms.get(f, 0) + 1
        m = p.get("municipality", "Unknown")
        munis[m] = munis.get(m, 0) + 1

    top_munis = sorted(munis.items(), key=lambda x: -x[1])[:15]
    top_forms = sorted(forms.items(), key=lambda x: -x[1])[:10]

    return jsonify({
        "total": n, "available": avail,
        "with_financials": fin, "with_roles": roles, "with_website": web,
        "total_claims": claims, "claims_sourced": sourced,
        "top_municipalities": top_munis, "top_legal_forms": top_forms,
    })


@app.route("/api/search-live")
def api_search_live():
    """Search Brreg API in real-time for ANY Norwegian company."""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify({"results": [], "source": "brreg_live"})

    try:
        url = f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={q}&size=30"
        with httpx.Client(timeout=10) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return jsonify({"results": [], "error": f"Brreg returned {resp.status_code}"})

        data = resp.json()
        entities = data.get("_embedded", {}).get("enheter", [])
        results = []
        for e in entities:
            nr = e.get("organisasjonsnummer", "")
            addr = e.get("forretningsadresse", {})
            results.append({
                "organisation_number": nr,
                "name": e.get("navn"),
                "legal_form": e.get("organisasjonsform", {}).get("kode"),
                "legal_form_desc": e.get("organisasjonsform", {}).get("beskrivelse"),
                "municipality": addr.get("kommune"),
                "address": ", ".join(addr.get("adresse", [])),
                "postcode": addr.get("postnummer"),
                "city": addr.get("poststed"),
                "employees": e.get("antallAnsatte"),
                "website": e.get("hjemmeside"),
                "nace": e.get("naeringskode1", {}).get("beskrivelse"),
                "nace_code": e.get("naeringskode1", {}).get("kode"),
                "registered": e.get("registreringsdatoEnhetsregisteret"),
                "has_profile": nr in PROFILES_INDEX,
            })
        return jsonify({"results": results, "total": len(results), "source": "brreg_live"})
    except Exception as ex:
        return jsonify({"results": [], "error": str(ex)})


@app.route("/api/lookup/<org_number>")
def api_lookup(org_number):
    """Lookup a single company from Brreg in real-time and build a basic profile."""
    # Check pre-loaded first
    if org_number in PROFILES_INDEX:
        return jsonify(PROFILES_INDEX[org_number])

    try:
        with httpx.Client(timeout=10) as client:
            # Fetch entity
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}")
            if resp.status_code != 200:
                return jsonify({"error": f"Company {org_number} not found", "status": "not_available"}), 404
            entity = resp.json()

            # Fetch financials
            fin_data = None
            fin_resp = client.get(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}")
            if fin_resp.status_code == 200:
                fin_data = fin_resp.json()

            # Fetch roles
            roles = []
            roles_resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller")
            if roles_resp.status_code == 200:
                roles_data = roles_resp.json()
                for group in roles_data.get("rollegrupper", []):
                    role_type = group.get("type", {}).get("beskrivelse", "")
                    for role in group.get("roller", []):
                        person = role.get("person", {})
                        org = role.get("enhet", {})
                        name = ""
                        if person:
                            name = f"{person.get('navn', {}).get('fornavn', '')} {person.get('navn', {}).get('etternavn', '')}".strip()
                        elif org:
                            name = org.get("navn", "")
                        if name:
                            roles.append({
                                "name": name,
                                "role": role_type,
                                "source": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller",
                            })

        # Build profile on-the-fly
        addr = entity.get("forretningsadresse", {})
        addr_parts = addr.get("adresse", [])
        full_addr = ", ".join(addr_parts) + f", {addr.get('postnummer', '')} {addr.get('poststed', '')}" if addr_parts else None

        nace_codes = []
        for key in ["naeringskode1", "naeringskode2", "naeringskode3"]:
            nace = entity.get(key)
            if nace:
                nace_codes.append({"code": nace.get("kode"), "description": nace.get("beskrivelse"), "system": "NACE"})

        # Parse financials
        fin_section = {"status": "not_available"}
        if fin_data:
            items = fin_data if isinstance(fin_data, list) else [fin_data]
            if items:
                latest = items[0]
                res = latest.get("resultatregnskapResultat", {})
                bal = latest.get("eiendeler", {})
                eq = latest.get("egenkapitalGjeld", {})
                fin_section = {
                    "status": "available",
                    "latest_filing_year": latest.get("regnskapsperiode", {}).get("fraDato", "")[:4],
                    "currency": "NOK",
                    "revenue": {"value": res.get("driftsresultat", {}).get("driftsinntekter", {}).get("sumDriftsinntekter"), "status": "available"},
                    "operating_profit": {"value": res.get("driftsresultat", {}).get("driftsresultat"), "status": "available"},
                    "total_assets": {"value": bal.get("sumEiendeler"), "status": "available"},
                }

        profile = {
            "organisation_number": org_number,
            "name": entity.get("navn"),
            "legal_form": entity.get("organisasjonsform", {}).get("kode"),
            "municipality": addr.get("kommune"),
            "website": entity.get("hjemmeside"),
            "status": "available",
            "source": "real_time_lookup",
            "legal_identity": {
                "status": "available",
                "legal_name": {"value": entity.get("navn"), "source": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"},
                "legal_form": {"value": entity.get("organisasjonsform", {}).get("beskrivelse")},
                "registered_address": {"value": full_addr},
                "registration_date": {"value": entity.get("registreringsdatoEnhetsregisteret")},
                "registration_status": {"value": "Active" if not entity.get("slettedato") else "Deleted"},
                "activity_description": {"value": entity.get("naeringskode1", {}).get("beskrivelse")},
                "industry_codes": nace_codes,
                "is_bankrupt": entity.get("konkurs", False),
                "is_in_liquidation": entity.get("underAvvikling", False),
            },
            "annual_accounts": fin_section,
            "leadership_workplaces": {
                "status": "available" if roles else "not_available",
                "roles": roles,
                "workplaces": [],
            },
            "website_profiles": {"status": "available" if entity.get("hjemmeside") else "not_available"},
            "evidence": {
                "total_claims": 5 + len(nace_codes) + len(roles),
                "claims_with_source": 5 + len(nace_codes) + len(roles),
                "registry_live": {"status": "verified", "value": {"organisation_number": org_number}},
                "financials": fin_section,
                "roles": {"status": "available" if roles else "not_available", "count": len(roles)},
                "locations": {"status": "not_available"},
                "website": {"status": "available" if entity.get("hjemmeside") else "not_available"},
            },
            "synthesis": {
                "status": "available",
                "method": "real_time",
                "summary": f"{entity.get('navn')} is a {entity.get('organisasjonsform', {}).get('beskrivelse', 'company')} based in {addr.get('kommune', 'Norway')}.",
                "key_observations": [],
                "confidence": 0.9,
            },
        }
        return jsonify(profile)

    except Exception as ex:
        return jsonify({"error": str(ex), "status": "failed"}), 500


@app.route("/company/<org_number>")
def company_detail(org_number):
    profile = PROFILES_INDEX.get(org_number)
    if not profile:
        # Try real-time lookup for the template
        return render_template("company_live.html", org=org_number)
    return render_template("company.html", profile=profile, org=org_number)


@app.route("/search")
def search_page():
    return render_template("search.html")


def create_app(profiles_path="out/signalpost_final.json"):
    load_profiles(profiles_path)
    return app
