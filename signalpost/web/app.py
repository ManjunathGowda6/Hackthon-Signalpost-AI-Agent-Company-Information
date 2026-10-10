"""Signalpost Web Dashboard — browse and search company profiles."""
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

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
        print(f"  Warning: {path} not found. Run the pipeline first.")


@app.route("/")
def index():
    return render_template("index.html", total=len(PROFILES))


@app.route("/api/profiles")
def api_profiles():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search = request.args.get("q", "").strip().lower()
    form_filter = request.args.get("form", "").strip().upper()
    muni_filter = request.args.get("municipality", "").strip().upper()

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
    if muni_filter:
        filtered = [p for p in filtered if muni_filter in (p.get("municipality") or "").upper()]

    total = len(filtered)
    start = (page - 1) * per_page
    end = start + per_page
    items = filtered[start:end]

    # Slim down for list view
    slim = []
    for p in items:
        ev = p.get("evidence", {})
        slim.append({
            "organisation_number": p.get("organisation_number"),
            "name": p.get("name"),
            "legal_form": p.get("legal_form"),
            "municipality": p.get("municipality"),
            "status": p.get("status"),
            "has_financials": ev.get("financials", {}).get("status") == "available",
            "has_roles": ev.get("roles", {}).get("status") == "available",
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
    fin = sum(1 for p in PROFILES if p.get("evidence", {}).get("financials", {}).get("status") == "available")
    roles = sum(1 for p in PROFILES if p.get("evidence", {}).get("roles", {}).get("status") == "available")
    web = sum(1 for p in PROFILES if p.get("website"))
    claims = sum(p.get("evidence", {}).get("total_claims", 0) for p in PROFILES)
    sourced = sum(p.get("evidence", {}).get("claims_with_source", 0) for p in PROFILES)

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


@app.route("/company/<org_number>")
def company_detail(org_number):
    profile = PROFILES_INDEX.get(org_number)
    if not profile:
        return render_template("404.html"), 404
    return render_template("company.html", profile=profile, org=org_number)


@app.route("/search")
def search_page():
    return render_template("search.html")


def create_app(profiles_path="out/signalpost_final.json"):
    load_profiles(profiles_path)
    return app
