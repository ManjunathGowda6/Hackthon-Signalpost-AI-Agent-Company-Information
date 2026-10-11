"""Signalpost Web Dashboard — unified smart search."""
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
ALL_COMPANIES: list[dict] = []
COMPANY_INDEX: dict[str, dict] = {}


def load_profiles(path: str = "out/signalpost_final.json"):
    global PROFILES, PROFILES_INDEX
    p = Path(path)
    if p.exists():
        PROFILES = json.loads(p.read_text(encoding="utf-8"))
        PROFILES_INDEX = {pr["organisation_number"]: pr for pr in PROFILES}
        print(f"  Loaded {len(PROFILES)} enriched profiles")


def load_company_database(path: str = "data/all_companies.json"):
    global ALL_COMPANIES, COMPANY_INDEX
    p = Path(path)
    if p.exists():
        ALL_COMPANIES = json.loads(p.read_text(encoding="utf-8"))
        COMPANY_INDEX = {c["o"]: c for c in ALL_COMPANIES}
        print(f"  Loaded {len(ALL_COMPANIES)} companies from all sectors")
    else:
        print(f"  Warning: {path} not found. Run sector download first.")


@app.route("/")
def index():
    return render_template("index.html",
                          total_companies=len(ALL_COMPANIES),
                          total_profiles=len(PROFILES))


@app.route("/api/search")
def api_search():
    """Unified search: preloaded companies first, then live Brreg fallback."""
    q = request.args.get("q", "").strip().lower()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    sector = request.args.get("sector", "").strip()

    if not q and not sector:
        # Show top companies by employee count
        filtered = ALL_COMPANIES[:per_page * page]
    else:
        filtered = []
        for c in ALL_COMPANIES:
            if sector and not str(c.get("nc", "")).startswith(sector):
                continue
            if q:
                name_match = q in (c.get("n") or "").lower()
                org_match = q in (c.get("o") or "")
                muni_match = q in (c.get("m") or "").lower()
                nace_match = q in (c.get("nd") or "").lower()
                if not (name_match or org_match or muni_match or nace_match):
                    continue
            filtered.append(c)

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start:start + per_page]

    results = []
    for c in items:
        org = c["o"]
        has_profile = org in PROFILES_INDEX
        results.append({
            "organisation_number": org,
            "name": c.get("n"),
            "legal_form": c.get("f"),
            "municipality": c.get("m"),
            "employees": c.get("e", 0),
            "nace_code": c.get("nc"),
            "nace_description": c.get("nd"),
            "website": c.get("w"),
            "sector": c.get("s"),
            "has_full_profile": has_profile,
        })

    # If local results < 10 and query exists, also search Brreg live
    live_results = []
    if q and len(q) >= 2 and total < 10:
        try:
            url = f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={q}&size=20"
            with httpx.Client(timeout=8) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                entities = data.get("_embedded", {}).get("enheter", [])
                seen = set(c["o"] for c in filtered)
                for e in entities:
                    nr = e.get("organisasjonsnummer", "")
                    if nr in seen:
                        continue
                    seen.add(nr)
                    addr = e.get("forretningsadresse", {})
                    live_results.append({
                        "organisation_number": nr,
                        "name": e.get("navn"),
                        "legal_form": e.get("organisasjonsform", {}).get("kode"),
                        "municipality": addr.get("kommune"),
                        "employees": e.get("antallAnsatte", 0) or 0,
                        "nace_code": e.get("naeringskode1", {}).get("kode"),
                        "nace_description": e.get("naeringskode1", {}).get("beskrivelse"),
                        "website": e.get("hjemmeside"),
                        "sector": "live",
                        "has_full_profile": nr in PROFILES_INDEX,
                        "source": "live_brreg",
                    })
        except Exception:
            pass

    return jsonify({
        "total": total + len(live_results),
        "local_count": total,
        "live_count": len(live_results),
        "page": page,
        "per_page": per_page,
        "items": results + live_results,
    })


@app.route("/api/profiles/<org_number>")
def api_profile_detail(org_number):
    profile = PROFILES_INDEX.get(org_number)
    if not profile:
        return jsonify({"error": "Not found"}), 404
    return jsonify(profile)


@app.route("/api/stats")
def api_stats():
    n = len(ALL_COMPANIES)
    np = len(PROFILES)
    if n == 0:
        return jsonify({})

    # Sector breakdown
    sectors = {}
    for c in ALL_COMPANIES:
        s = c.get("s", "??")
        sectors[s] = sectors.get(s, 0) + 1
    top_sectors = sorted(sectors.items(), key=lambda x: -x[1])[:20]

    # Municipality breakdown
    munis = {}
    for c in ALL_COMPANIES:
        m = c.get("m", "Unknown")
        if m:
            munis[m] = munis.get(m, 0) + 1
    top_munis = sorted(munis.items(), key=lambda x: -x[1])[:15]

    # Profile stats
    fin = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("financials", {}).get("status") == "available")
    roles = sum(1 for p in PROFILES if (p.get("evidence") or {}).get("roles", {}).get("status") == "available")
    claims = sum((p.get("evidence") or {}).get("total_claims", 0) for p in PROFILES)

    return jsonify({
        "total_companies": n,
        "total_profiles": np,
        "with_financials": fin,
        "with_roles": roles,
        "total_claims": claims,
        "top_sectors": top_sectors,
        "top_municipalities": top_munis,
        "sectors_count": len(sectors),
    })


@app.route("/api/sectors")
def api_sectors():
    """List all available sectors."""
    from collections import Counter
    sector_counts = Counter()
    sector_names = {}
    for c in ALL_COMPANIES:
        s = c.get("s", "")
        sector_counts[s] += 1
        if s not in sector_names and c.get("nd"):
            sector_names[s] = c["nd"]
    result = [{"code": s, "name": sector_names.get(s, s), "count": cnt}
              for s, cnt in sector_counts.most_common()]
    return jsonify(result)


@app.route("/api/lookup/<org_number>")
def api_lookup(org_number):
    """Lookup: check profiles → check company db → live Brreg."""
    if org_number in PROFILES_INDEX:
        return jsonify(PROFILES_INDEX[org_number])

    # Build from company database or live
    basic = COMPANY_INDEX.get(org_number)

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}")
            if resp.status_code != 200:
                return jsonify({"error": "Not found", "status": "not_available"}), 404
            entity = resp.json()

            fin_data = None
            fr = client.get(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}")
            if fr.status_code == 200:
                fin_data = fr.json()

            roles = []
            rr = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller")
            if rr.status_code == 200:
                rd = rr.json()
                for group in rd.get("rollegrupper", []):
                    rt = group.get("type", {}).get("beskrivelse", "")
                    for role in group.get("roller", []):
                        person = role.get("person", {})
                        org = role.get("enhet", {})
                        name = ""
                        if person:
                            pn = person.get("navn", {})
                            name = f"{pn.get('fornavn', '')} {pn.get('etternavn', '')}".strip()
                        elif org:
                            name = org.get("navn", "")
                        if name:
                            roles.append({"name": name, "role": rt,
                                         "source": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller"})

        addr = entity.get("forretningsadresse", {})
        ap = addr.get("adresse", [])
        full_addr = ", ".join(ap) + f", {addr.get('postnummer', '')} {addr.get('poststed', '')}" if ap else None

        nace_codes = []
        for key in ["naeringskode1", "naeringskode2", "naeringskode3"]:
            nace = entity.get(key)
            if nace:
                nace_codes.append({"code": nace.get("kode"), "description": nace.get("beskrivelse"), "system": "NACE"})

        fin_section = {"status": "not_available"}
        if fin_data:
            items = fin_data if isinstance(fin_data, list) else [fin_data]
            if items:
                latest = items[0]
                res = latest.get("resultatregnskapResultat", {})
                bal = latest.get("eiendeler", {})
                fin_section = {
                    "status": "available",
                    "latest_filing_year": latest.get("regnskapsperiode", {}).get("fraDato", "")[:4],
                    "currency": "NOK",
                    "revenue": {"value": res.get("driftsresultat", {}).get("driftsinntekter", {}).get("sumDriftsinntekter")},
                    "operating_profit": {"value": res.get("driftsresultat", {}).get("driftsresultat")},
                    "total_assets": {"value": bal.get("sumEiendeler")},
                }

        emp = entity.get("antallAnsatte")
        form_desc = entity.get("organisasjonsform", {}).get("beskrivelse", "")
        muni = addr.get("kommune", "")
        nace_desc = entity.get("naeringskode1", {}).get("beskrivelse", "")

        parts = [f"{entity.get('navn')} is a {form_desc} based in {muni}."]
        if nace_desc:
            parts.append(f"Activity: {nace_desc}.")
        if emp:
            parts.append(f"{emp} employee(s).")
        obs = []
        if fin_section["status"] == "available":
            obs.append(f"Financial data on file for {fin_section.get('latest_filing_year', '?')}")
        if roles:
            obs.append(f"{len(roles)} registered leadership role(s)")
        if entity.get("konkurs"):
            obs.append("WARNING: Registered as bankrupt")

        profile = {
            "organisation_number": org_number,
            "name": entity.get("navn"),
            "legal_form": entity.get("organisasjonsform", {}).get("kode"),
            "municipality": muni,
            "website": entity.get("hjemmeside"),
            "status": "available",
            "source": "real_time_lookup",
            "legal_identity": {
                "status": "available",
                "legal_name": {"value": entity.get("navn"), "source": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"},
                "legal_form": {"value": form_desc},
                "registered_address": {"value": full_addr},
                "registration_date": {"value": entity.get("registreringsdatoEnhetsregisteret")},
                "registration_status": {"value": "Active" if not entity.get("slettedato") else "Deleted"},
                "activity_description": {"value": nace_desc},
                "industry_codes": nace_codes,
                "is_bankrupt": entity.get("konkurs", False),
                "is_in_liquidation": entity.get("underAvvikling", False),
            },
            "annual_accounts": fin_section,
            "leadership_workplaces": {"status": "available" if roles else "not_available", "roles": roles, "workplaces": []},
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
                "status": "available", "method": "real_time",
                "summary": " ".join(parts), "key_observations": obs, "confidence": 0.9,
            },
        }
        return jsonify(profile)
    except Exception as ex:
        return jsonify({"error": str(ex), "status": "failed"}), 500


@app.route("/company/<org_number>")
def company_detail(org_number):
    profile = PROFILES_INDEX.get(org_number)
    if profile:
        return render_template("company.html", profile=profile, org=org_number)
    return render_template("company_live.html", org=org_number)


@app.route("/search")
def search_page():
    return render_template("search.html", total=len(ALL_COMPANIES))


def create_app(profiles_path="out/signalpost_final.json"):
    load_profiles(profiles_path)
    load_company_database()
    return app
