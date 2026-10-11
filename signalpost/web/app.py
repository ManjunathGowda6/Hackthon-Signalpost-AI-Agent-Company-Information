"""Signalpost AI Chatbot — Company Intelligence Assistant."""
import json, httpx
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

PROFILES_INDEX: dict[str, dict] = {}
ALL_COMPANIES: list[dict] = []
COMPANY_INDEX: dict[str, dict] = {}
GLOBAL_COMPANIES: list[dict] = []

SECTOR_MAP = {
    "01":"Agriculture","02":"Forestry","03":"Fishing & Aquaculture","06":"Oil & Gas",
    "10":"Food Manufacturing","26":"Electronics","28":"Machinery","30":"Automotive",
    "35":"Energy & Utilities","41":"Construction","46":"Wholesale","47":"Retail",
    "49":"Transport & Logistics","50":"Shipping & Maritime","55":"Hotels","56":"Restaurants",
    "58":"Publishing & Media","61":"Telecom","62":"IT & Software","63":"Data Services",
    "64":"Banking & Finance","65":"Insurance","66":"Financial Services","68":"Real Estate",
    "69":"Legal & Accounting","70":"Management Consulting","71":"Engineering",
    "72":"R&D & Science","73":"Advertising","78":"Staffing & HR","85":"Education",
    "86":"Healthcare","93":"Sports & Fitness",
}


def load_all():
    global PROFILES_INDEX, ALL_COMPANIES, COMPANY_INDEX, GLOBAL_COMPANIES
    p = Path("out/signalpost_final.json")
    if p.exists():
        profiles = json.loads(p.read_text(encoding="utf-8"))
        PROFILES_INDEX = {pr["organisation_number"]: pr for pr in profiles}
        print(f"  Loaded {len(profiles)} enriched profiles")
    p2 = Path("data/all_companies.json")
    if p2.exists():
        ALL_COMPANIES = json.loads(p2.read_text(encoding="utf-8"))
        COMPANY_INDEX = {c["o"]: c for c in ALL_COMPANIES}
        print(f"  Loaded {len(ALL_COMPANIES)} Norwegian companies")
    p3 = Path("data/global_companies.json")
    if p3.exists():
        GLOBAL_COMPANIES = json.loads(p3.read_text(encoding="utf-8"))
        print(f"  Loaded {len(GLOBAL_COMPANIES)} global companies")


def fmt_num(v):
    if v is None: return "N/A"
    if isinstance(v, str): return v
    if abs(v) >= 1e9: return f"{v/1e9:,.1f}B"
    if abs(v) >= 1e6: return f"{v/1e6:,.1f}M"
    return f"{v:,.0f}"


def build_screener_card(gc):
    """Build rich screener-style output for a global company."""
    lines = []
    lines.append(f"# {gc['name']}")
    lines.append(f"**{gc.get('sector','')}** | {gc.get('hq','')}\n")
    lines.append(f"---")
    lines.append(f"📊 **Key Financials**")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Revenue | {gc.get('revenue','N/A')} |")
    lines.append(f"| Profit | {gc.get('profit','N/A')} |")
    lines.append(f"| Market Cap | {gc.get('market_cap','N/A')} |")
    if gc.get('valuation') and gc['valuation'] != 'N/A':
        lines.append(f"| Valuation | {gc['valuation']} |")
    lines.append(f"| P/E Ratio | {gc.get('pe_ratio','N/A')} |")
    lines.append(f"| D/E Ratio | {gc.get('debt_equity','N/A')} |")
    lines.append(f"| Stock | {gc.get('stock','Private')} |")
    lines.append("")
    lines.append(f"👤 **Leadership**")
    lines.append(f"- **CEO:** {gc.get('ceo','N/A')}")
    lines.append(f"- **Founded:** {gc.get('founded','N/A')}")
    lines.append(f"- **Employees:** {gc.get('employees','N/A'):,}")
    lines.append("")
    lines.append(f"🏭 **Products & Services**")
    lines.append(f"{gc.get('products','N/A')}")
    lines.append("")
    lines.append(f"💡 **About**")
    lines.append(f"{gc.get('desc','')}")
    lines.append("")
    lines.append(f"📈 **Key Metrics**")
    lines.append(f"{gc.get('key_metrics','N/A')}")
    lines.append("")
    if gc.get('investors'):
        lines.append(f"💰 **Investors:** {gc['investors']}")
    lines.append(f"🌐 [{gc.get('website','')}]({gc.get('website','')})")
    if gc.get('brreg'):
        lines.append(f"\n🇳🇴 [View Norwegian Registry Details →](/company/{gc['brreg']})")
    return "\n".join(lines)


def build_norwegian_card(c, profile=None):
    """Build screener-style output for a Norwegian company."""
    org = c["o"]
    sector = SECTOR_MAP.get(c.get("s",""), c.get("nd",""))
    lines = []
    lines.append(f"# {c.get('n','Unknown')}")
    lines.append(f"**{sector}** | {c.get('m','Norway')} | `{org}`\n")
    lines.append("---")
    lines.append("📊 **Company Overview**")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Legal Form | {c.get('f','N/A')} |")
    lines.append(f"| Municipality | {c.get('m','N/A')} |")
    lines.append(f"| Employees | {c.get('e',0):,} |")
    lines.append(f"| Sector | {sector} |")
    lines.append(f"| Industry (NACE) | {c.get('nd','N/A')} |")
    if c.get('w'):
        lines.append(f"| Website | [{c['w']}]({c['w']}) |")

    if profile:
        ev = profile.get("evidence", {}) or {}
        syn = profile.get("synthesis", {}) or {}
        aa = profile.get("annual_accounts", {}) or {}
        lw = profile.get("leadership_workplaces", {}) or {}

        if aa.get("status") == "available":
            lines.append("")
            lines.append("💰 **Annual Accounts**")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            lines.append(f"| Filing Year | {aa.get('latest_filing_year','N/A')} |")
            rev = (aa.get("revenue") or {}).get("value")
            if rev is not None: lines.append(f"| Revenue | {fmt_num(rev)} NOK |")
            op = (aa.get("operating_profit") or {}).get("value")
            if op is not None: lines.append(f"| Operating Profit | {fmt_num(op)} NOK |")
            ta = (aa.get("total_assets") or {}).get("value")
            if ta is not None: lines.append(f"| Total Assets | {fmt_num(ta)} NOK |")
            te = (aa.get("total_equity") or {}).get("value")
            if te is not None: lines.append(f"| Total Equity | {fmt_num(te)} NOK |")
            td = (aa.get("total_debt") or {}).get("value")
            if td is not None: lines.append(f"| Total Debt | {fmt_num(td)} NOK |")

        roles = lw.get("roles", [])
        if roles:
            lines.append("")
            lines.append(f"👥 **Leadership** ({len(roles)} roles)")
            for r in roles[:8]:
                lines.append(f"- **{r.get('name','')}** — {r.get('role','')}")

        if syn.get("summary"):
            lines.append("")
            lines.append(f"💡 **Summary**")
            lines.append(syn["summary"])
            obs = syn.get("key_observations", [])
            if obs:
                lines.append("")
                for o in obs[:5]:
                    lines.append(f"- {o}")

        lines.append("")
        lines.append(f"📊 **Evidence:** {ev.get('total_claims',0)} claims, {ev.get('claims_with_source',0)} sourced")
    else:
        lines.append("")
        lines.append("*Basic listing — click below for full real-time details*")

    lines.append(f"\n[View Full Profile →](/company/{org})")
    return "\n".join(lines)


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    msg = data.get("message", "").strip()
    if not msg:
        return jsonify({"reply": "Ask me about any company!", "type": "text"})

    q = msg.lower()

    # ── Check global companies first ──
    for gc in GLOBAL_COMPANIES:
        name_l = gc["name"].lower()
        words = [w for w in name_l.replace("/"," ").replace("("," ").replace(")"," ").split() if len(w) > 2]
        if name_l in q or any(w in q for w in words):
            return jsonify({"reply": build_screener_card(gc), "type": "company", "source": "global"})

    # ── Check Norwegian companies ──
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
            profile = PROFILES_INDEX.get(c["o"])
            return jsonify({"reply": build_norwegian_card(c, profile), "type": "company", "source": "norwegian"})
        else:
            lines = [f"Found **{len(matches)}** Norwegian companies:\n"]
            for c in matches[:5]:
                sector = SECTOR_MAP.get(c.get("s",""), "")
                emp = c.get("e",0)
                badge = "✅" if c["o"] in PROFILES_INDEX else "📋"
                lines.append(f"- **{c.get('n')}** — {sector} | {emp:,} employees {badge}")
                lines.append(f"  *Ask: \"Tell me about {c.get('n')}\"*")
            return jsonify({"reply": "\n".join(lines), "type": "list", "source": "norwegian"})

    # ── Live Brreg search ──
    if len(q) >= 2:
        try:
            with httpx.Client(timeout=8) as client:
                resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={msg}&size=5")
            if resp.status_code == 200:
                entities = resp.json().get("_embedded", {}).get("enheter", [])
                if entities:
                    lines = [f"⚡ Found **{len(entities)}** companies from live Brreg search:\n"]
                    for e in entities:
                        nr = e.get("organisasjonsnummer","")
                        emp = e.get("antallAnsatte",0) or 0
                        lines.append(f"- **{e.get('navn')}** (`{nr}`) — {e.get('forretningsadresse',{}).get('kommune','')} | {emp:,} employees")
                        lines.append(f"  [View Full Profile →](/company/{nr})")
                    return jsonify({"reply": "\n".join(lines), "type": "list", "source": "live"})
        except Exception:
            pass

    # ── Sector queries ──
    for code, name in SECTOR_MAP.items():
        if name.lower() in q:
            sector_cos = [c for c in ALL_COMPANIES if c.get("s") == code][:10]
            global_cos = [g for g in GLOBAL_COMPANIES if name.lower() in g.get("sector","").lower()]
            lines = [f"# {name} Sector\n"]
            if global_cos:
                lines.append("## 🌍 Global Leaders")
                for g in global_cos[:5]:
                    lines.append(f"- **{g['name']}** — {g.get('revenue','')} revenue | {g.get('employees',''):,} employees")
                lines.append("")
            if sector_cos:
                lines.append("## 🇳🇴 Norwegian Companies")
                for c in sector_cos:
                    lines.append(f"- **{c.get('n')}** — {c.get('e',0):,} employees | {c.get('m','')}")
            return jsonify({"reply": "\n".join(lines), "type": "sector"})

    # ── List sectors ──
    if any(w in q for w in ["sector", "sectors", "categories", "industries", "list"]):
        lines = ["# Available Sectors\n"]
        for code, name in sorted(SECTOR_MAP.items(), key=lambda x: x[1]):
            count = sum(1 for c in ALL_COMPANIES if c.get("s") == code)
            lines.append(f"- **{name}** ({count:,} companies)")
        lines.append(f"\n*Ask: \"Show IT & Software companies\" or \"Tell me about Banking sector\"*")
        return jsonify({"reply": "\n".join(lines), "type": "list"})

    # ── Help ──
    return jsonify({"reply": """I didn't find a match. Try:

🔍 **Company names:** "OpenAI", "TCS", "Equinor", "Tesla", "NVIDIA"
🏭 **Sectors:** "IT & Software sector", "Banking sector", "Healthcare"
📋 **Browse:** "Show all sectors"

I know **""" + str(len(GLOBAL_COMPANIES)) + """+ global companies** and **""" + str(len(ALL_COMPANIES)) + """+ Norwegian companies**.""", "type": "help"})


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
            fin = None
            fr = client.get(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}")
            if fr.status_code == 200: fin = fr.json()
            roles = []
            rr = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller")
            if rr.status_code == 200:
                for g in rr.json().get("rollegrupper",[]):
                    rt = g.get("type",{}).get("beskrivelse","")
                    for r in g.get("roller",[]):
                        p = r.get("person",{})
                        o = r.get("enhet",{})
                        nm = ""
                        if p: nm = f"{p.get('navn',{}).get('fornavn','')} {p.get('navn',{}).get('etternavn','')}".strip()
                        elif o: nm = o.get("navn","")
                        if nm: roles.append({"name":nm,"role":rt})
        addr = entity.get("forretningsadresse",{})
        ap = addr.get("adresse",[])
        fa = (", ".join(ap)+f", {addr.get('postnummer','')} {addr.get('poststed','')}") if ap else None
        fs = {"status":"not_available"}
        if fin:
            items = fin if isinstance(fin,list) else [fin]
            if items:
                l=items[0]; r=l.get("resultatregnskapResultat",{}); b=l.get("eiendeler",{})
                fs={"status":"available","latest_filing_year":l.get("regnskapsperiode",{}).get("fraDato","")[:4],"currency":"NOK",
                    "revenue":{"value":r.get("driftsresultat",{}).get("driftsinntekter",{}).get("sumDriftsinntekter")},
                    "operating_profit":{"value":r.get("driftsresultat",{}).get("driftsresultat")},
                    "total_assets":{"value":b.get("sumEiendeler")}}
        profile={"organisation_number":org_number,"name":entity.get("navn"),"legal_form":entity.get("organisasjonsform",{}).get("kode"),
            "municipality":addr.get("kommune"),"website":entity.get("hjemmeside"),"status":"available",
            "legal_identity":{"status":"available","legal_name":{"value":entity.get("navn")},"legal_form":{"value":entity.get("organisasjonsform",{}).get("beskrivelse")},
                "registered_address":{"value":fa},"registration_date":{"value":entity.get("registreringsdatoEnhetsregisteret")},
                "registration_status":{"value":"Active" if not entity.get("slettedato") else "Deleted"},
                "activity_description":{"value":entity.get("naeringskode1",{}).get("beskrivelse")},"is_bankrupt":entity.get("konkurs",False)},
            "annual_accounts":fs,"leadership_workplaces":{"status":"available" if roles else "not_available","roles":roles,"workplaces":[]},
            "evidence":{"total_claims":5+len(roles),"claims_with_source":5+len(roles),"registry_live":{"status":"verified"},
                "financials":fs,"roles":{"status":"available" if roles else "not_available","count":len(roles)}},
            "synthesis":{"status":"available","summary":f"{entity.get('navn')} is a {entity.get('organisasjonsform',{}).get('beskrivelse','')} based in {addr.get('kommune','')}."}}
        return jsonify(profile)
    except Exception as ex:
        return jsonify({"error":str(ex)}), 500


@app.route("/company/<org_number>")
def company_detail(org_number):
    if org_number in PROFILES_INDEX:
        return render_template("company.html", profile=PROFILES_INDEX[org_number], org=org_number)
    return render_template("company_live.html", org=org_number)


def create_app(profiles_path="out/signalpost_final.json"):
    load_all()
    return app
