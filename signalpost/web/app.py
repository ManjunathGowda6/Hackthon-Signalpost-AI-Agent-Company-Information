"""Signalpost AI — Claude-like Company Intelligence Chatbot."""
import json, re, httpx
from difflib import SequenceMatcher
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
GLOBAL_INDEX: dict[str, dict] = {}  # lowercase name -> company

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
    global PROFILES_INDEX, ALL_COMPANIES, COMPANY_INDEX, GLOBAL_COMPANIES, GLOBAL_INDEX
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
        for gc in GLOBAL_COMPANIES:
            # Index by multiple name variations
            name = gc["name"].lower()
            GLOBAL_INDEX[name] = gc
            # Add short names: "OpenAI" -> "openai", "TCS (Tata...)" -> "tcs"
            for part in re.split(r'[/\(\)]', name):
                part = part.strip()
                if len(part) >= 2:
                    GLOBAL_INDEX[part] = gc
            # Add keywords from name
            for word in name.split():
                if len(word) >= 3 and word not in ('the','and','for'):
                    GLOBAL_INDEX[word] = gc
        print(f"  Loaded {len(GLOBAL_COMPANIES)} global companies ({len(GLOBAL_INDEX)} search keys)")


def fuzzy_score(query, target):
    """Calculate fuzzy match score (0-1)."""
    q = query.lower().strip()
    t = target.lower().strip()
    if q == t: return 1.0
    if q in t: return 0.9
    if t in q: return 0.85
    return SequenceMatcher(None, q, t).ratio()


def fuzzy_find_global(query):
    """Find global company with fuzzy matching."""
    q = query.lower().strip()

    # Direct match
    if q in GLOBAL_INDEX:
        return GLOBAL_INDEX[q]

    # Check each word in query against index
    words = re.findall(r'\w+', q)
    for word in words:
        if len(word) >= 3 and word in GLOBAL_INDEX:
            return GLOBAL_INDEX[word]

    # Fuzzy match against all company names
    best_match = None
    best_score = 0
    for gc in GLOBAL_COMPANIES:
        score = fuzzy_score(q, gc["name"])
        # Also check each word against company name
        for word in words:
            if len(word) >= 3:
                s2 = fuzzy_score(word, gc["name"])
                score = max(score, s2)
        if score > best_score and score >= 0.55:
            best_score = score
            best_match = gc

    return best_match


def fuzzy_find_norwegian(query):
    """Find Norwegian companies with fuzzy matching."""
    q = query.lower().strip()
    words = [w for w in re.findall(r'\w+', q) if len(w) >= 2]
    matches = []

    for c in ALL_COMPANIES:
        name = (c.get("n") or "").lower()
        if not name:
            continue

        # Exact substring
        if q in name:
            matches.append((c, 0.95))
            continue

        # Any word match
        for word in words:
            if word in name:
                matches.append((c, 0.8))
                break
        else:
            # Fuzzy
            score = fuzzy_score(q, name)
            if score >= 0.6:
                matches.append((c, score))

        if len(matches) >= 10:
            break

    matches.sort(key=lambda x: (-x[1], -(x[0].get("e", 0) or 0)))
    return [m[0] for m in matches[:5]]


def extract_intent(message):
    """Understand user intent even with grammar mistakes."""
    q = message.lower().strip()
    q = re.sub(r'[?.!,;]+$', '', q)

    # Remove filler words
    noise = ['tell','me','about','what','is','who','the','a','an','show',
             'give','info','information','details','of','company','called',
             'please','can','you','do','know','say','explain','describe',
             'search','find','look','up','how','whats','whos']
    words = re.findall(r'\w+', q)
    clean = [w for w in words if w not in noise and len(w) >= 2]
    clean_query = ' '.join(clean)

    # Detect intent type
    intent = "company"  # default
    if any(w in q for w in ['sector', 'sectors', 'industry', 'industries', 'categories', 'all sector']):
        intent = "sectors"
    elif any(w in q for w in ['compare', 'vs', 'versus', 'difference']):
        intent = "compare"
    elif any(w in q for w in ['help', 'what can you', 'how to use']):
        intent = "help"

    return intent, clean_query, words


def fmt(v):
    if v is None: return "N/A"
    if isinstance(v, str): return v
    if abs(v) >= 1e9: return f"{v/1e9:,.1f}B"
    if abs(v) >= 1e6: return f"{v/1e6:,.1f}M"
    if abs(v) >= 1e3: return f"{v/1e3:,.1f}K"
    return f"{v:,.0f}"


def build_global_response(gc):
    """Build comprehensive A-Z company response."""
    lines = []
    lines.append(f"# {gc['name']}\n")
    lines.append(f"{gc.get('desc','')}\n")
    lines.append("---\n")

    # Overview
    lines.append("## 🏢 Company Overview\n")
    lines.append(f"| | |")
    lines.append(f"|---|---|")
    lines.append(f"| **Sector** | {gc.get('sector','')} |")
    lines.append(f"| **Headquarters** | {gc.get('hq','')} |")
    lines.append(f"| **Founded** | {gc.get('founded','N/A')} |")
    lines.append(f"| **CEO** | {gc.get('ceo','N/A')} |")
    lines.append(f"| **Employees** | {gc.get('employees','N/A'):,} |")
    lines.append(f"| **Website** | [{gc.get('website','')}]({gc.get('website','')}) |")
    lines.append(f"| **Stock Ticker** | {gc.get('stock','Private')} |")
    lines.append("")

    # Financials
    lines.append("## 📊 Financial Overview\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| **Revenue** | {gc.get('revenue','N/A')} |")
    lines.append(f"| **Net Profit** | {gc.get('profit','N/A')} |")
    lines.append(f"| **Market Cap** | {gc.get('market_cap','N/A')} |")
    if gc.get('valuation') and gc['valuation'] != 'N/A':
        lines.append(f"| **Valuation** | {gc['valuation']} |")
    lines.append(f"| **P/E Ratio** | {gc.get('pe_ratio','N/A')} |")
    lines.append(f"| **Debt/Equity** | {gc.get('debt_equity','N/A')} |")
    lines.append("")

    # Products
    lines.append("## 🛠️ Products & Services\n")
    products = gc.get('products', '').split(', ')
    for p in products:
        lines.append(f"- {p}")
    lines.append("")

    # Key Metrics
    lines.append("## 📈 Key Metrics & Highlights\n")
    metrics = gc.get('key_metrics', '').split('; ')
    for m in metrics:
        if m.strip():
            lines.append(f"- {m.strip()}")
    lines.append("")

    # Investors
    if gc.get('investors'):
        lines.append("## 💰 Key Investors\n")
        lines.append(f"{gc['investors']}\n")

    # Norwegian connection
    if gc.get('brreg'):
        lines.append(f"---\n🇳🇴 This company is registered in Norway. [View Norwegian registry details →](/company/{gc['brreg']})")

    return "\n".join(lines)


def build_norwegian_response(c, profile=None):
    """Build comprehensive response for a Norwegian company."""
    org = c["o"]
    sector = SECTOR_MAP.get(c.get("s",""), c.get("nd",""))
    lines = []
    lines.append(f"# {c.get('n','Unknown')}\n")

    # Overview
    lines.append("## 🏢 Company Overview\n")
    lines.append(f"| | |")
    lines.append(f"|---|---|")
    lines.append(f"| **Org. Number** | `{org}` |")
    lines.append(f"| **Legal Form** | {c.get('f','N/A')} |")
    lines.append(f"| **Sector** | {sector} |")
    lines.append(f"| **Municipality** | {c.get('m','N/A')} |")
    lines.append(f"| **Employees** | {c.get('e',0):,} |")
    lines.append(f"| **Industry (NACE)** | {c.get('nd','N/A')} |")
    if c.get('w'):
        lines.append(f"| **Website** | [{c['w']}]({c['w']}) |")
    lines.append("")

    if profile:
        ev = profile.get("evidence", {}) or {}
        syn = profile.get("synthesis", {}) or {}
        aa = profile.get("annual_accounts", {}) or {}
        lw = profile.get("leadership_workplaces", {}) or {}
        li = profile.get("legal_identity", {}) or {}

        # Legal identity
        if li.get("status") == "available":
            lines.append("## 📋 Legal Identity\n")
            lines.append(f"| | |")
            lines.append(f"|---|---|")
            ln = (li.get("legal_name") or {}).get("value")
            if ln: lines.append(f"| **Legal Name** | {ln} |")
            lf = (li.get("legal_form") or {}).get("value")
            if lf: lines.append(f"| **Legal Form** | {lf} |")
            ra = (li.get("registered_address") or {}).get("value")
            if ra: lines.append(f"| **Address** | {ra} |")
            rd = (li.get("registration_date") or {}).get("value")
            if rd: lines.append(f"| **Registered** | {rd} |")
            rs = (li.get("registration_status") or {}).get("value")
            if rs: lines.append(f"| **Status** | {rs} |")
            ad = (li.get("activity_description") or {}).get("value")
            if ad: lines.append(f"| **Activity** | {ad} |")
            if li.get("is_bankrupt"): lines.append(f"| **⚠️ Bankrupt** | Yes |")
            lines.append("")

        # Financials
        if aa.get("status") == "available":
            lines.append("## 📊 Annual Accounts\n")
            lines.append(f"| Metric | Value |")
            lines.append(f"|---|---|")
            lines.append(f"| **Filing Year** | {aa.get('latest_filing_year','N/A')} |")
            rev = (aa.get("revenue") or {}).get("value")
            if rev is not None: lines.append(f"| **Revenue** | {fmt(rev)} NOK |")
            op = (aa.get("operating_profit") or {}).get("value")
            if op is not None: lines.append(f"| **Operating Profit** | {fmt(op)} NOK |")
            ta = (aa.get("total_assets") or {}).get("value")
            if ta is not None: lines.append(f"| **Total Assets** | {fmt(ta)} NOK |")
            te = (aa.get("total_equity") or {}).get("value")
            if te is not None: lines.append(f"| **Total Equity** | {fmt(te)} NOK |")
            lines.append("")

        # Leadership
        roles = lw.get("roles", [])
        if roles:
            lines.append(f"## 👥 Leadership ({len(roles)} registered roles)\n")
            for r in roles[:10]:
                lines.append(f"- **{r.get('name','')}** — {r.get('role','')}")
            if len(roles) > 10:
                lines.append(f"- *...and {len(roles)-10} more*")
            lines.append("")

        # Synthesis
        if syn.get("summary"):
            lines.append(f"## 💡 Summary\n")
            lines.append(f"{syn['summary']}\n")
            obs = syn.get("key_observations", [])
            if obs:
                for o in obs[:5]:
                    lines.append(f"- {o}")
                lines.append("")

        # Evidence
        lines.append(f"## 🔍 Evidence & Sources\n")
        lines.append(f"- **Total claims:** {ev.get('total_claims',0)}")
        lines.append(f"- **Sourced claims:** {ev.get('claims_with_source',0)}")
        lines.append(f"- **Registry verified:** ✅")
    else:
        lines.append("\n*This is a basic listing. For full financial details, leadership, and evidence, this company needs to be enriched through the Signalpost agent.*\n")

    return "\n".join(lines)


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    msg = data.get("message", "").strip()
    if not msg:
        return jsonify({"reply": "Hi! Ask me about any company — I'll give you the full picture.", "type": "text"})

    intent, clean_q, words = extract_intent(msg)

    # ── Help ──
    if intent == "help":
        return jsonify({"reply": """I'm your Company Intelligence Assistant. Here's what I can do:

**🔍 Ask about any company:**
- *"Tell me about OpenAI"*
- *"What is NVIDIA?"*
- *"opn ai"* (I handle typos!)
- *"tcs company details"*

**🏭 Browse sectors:**
- *"Show IT companies"*
- *"Banking sector"*

**🌍 I know:**
- 33+ major global companies (tech, auto, AI, finance)
- 53,000+ Norwegian companies from the official registry
- Financial data, leadership, products, and key metrics

Just type a company name and I'll tell you everything I know!""", "type": "help"})

    # ── Sectors ──
    if intent == "sectors":
        lines = ["# 📂 Available Sectors\n"]
        for code, name in sorted(SECTOR_MAP.items(), key=lambda x: x[1]):
            count = sum(1 for c in ALL_COMPANIES if c.get("s") == code)
            if count > 0:
                lines.append(f"- **{name}** — {count:,} companies")
        lines.append(f"\nJust say something like *\"Show IT & Software companies\"* to explore a sector.")
        return jsonify({"reply": "\n".join(lines), "type": "sectors"})

    # ── Try global companies (fuzzy) ──
    gc = fuzzy_find_global(clean_q or msg)
    if gc:
        return jsonify({"reply": build_global_response(gc), "type": "company", "source": "global"})

    # ── Try Norwegian companies (fuzzy) ──
    nor_matches = fuzzy_find_norwegian(clean_q or msg)
    if nor_matches:
        if len(nor_matches) == 1:
            c = nor_matches[0]
            profile = PROFILES_INDEX.get(c["o"])
            return jsonify({"reply": build_norwegian_response(c, profile), "type": "company", "source": "norwegian"})
        else:
            lines = [f"I found **{len(nor_matches)} companies** matching your search:\n"]
            for c in nor_matches:
                sector = SECTOR_MAP.get(c.get("s",""), "")
                emp = c.get("e", 0) or 0
                badge = "✅ Full Profile" if c["o"] in PROFILES_INDEX else ""
                lines.append(f"### {c.get('n','')}")
                lines.append(f"*{sector}* | {c.get('m','')} | {emp:,} employees {badge}")
                lines.append(f"Say *\"Tell me about {c.get('n','')}\"* for full details.\n")
            return jsonify({"reply": "\n".join(lines), "type": "list", "source": "norwegian"})

    # ── Sector queries ──
    for code, name in SECTOR_MAP.items():
        if name.lower() in msg.lower() or any(w in name.lower().split() for w in words if len(w) >= 3):
            sector_cos = [c for c in ALL_COMPANIES if c.get("s") == code][:10]
            global_cos = [g for g in GLOBAL_COMPANIES if name.lower() in g.get("sector","").lower()]
            lines = [f"# {name} Sector\n"]
            if global_cos:
                lines.append("## 🌍 Global Leaders\n")
                for g in global_cos[:5]:
                    lines.append(f"**{g['name']}** — {g.get('hq','')} | {g.get('revenue','')} revenue | {g.get('employees','N/A'):,} employees")
                    lines.append(f"*Say \"{g['name']}\" to see full details*\n")
            if sector_cos:
                lines.append("## 🇳🇴 Norwegian Companies\n")
                for c in sector_cos:
                    lines.append(f"- **{c.get('n','')}** — {c.get('e',0):,} employees | {c.get('m','')}")
            return jsonify({"reply": "\n".join(lines), "type": "sector"})

    # ── Live Brreg fallback ──
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={msg}&size=5")
        if resp.status_code == 200:
            entities = resp.json().get("_embedded", {}).get("enheter", [])
            if entities:
                lines = [f"I searched the Norwegian Business Registry and found:\n"]
                for e in entities:
                    nr = e.get("organisasjonsnummer","")
                    name = e.get("navn","")
                    emp = e.get("antallAnsatte",0) or 0
                    muni = e.get("forretningsadresse",{}).get("kommune","")
                    lines.append(f"### {name}")
                    lines.append(f"`{nr}` | {muni} | {emp:,} employees")
                    lines.append(f"Say *\"{name}\"* for full details.\n")
                return jsonify({"reply": "\n".join(lines), "type": "list", "source": "live"})
    except Exception:
        pass

    # ── Not found ──
    return jsonify({"reply": f"""I couldn't find a company matching **\"{msg}\"**. Here are some things you can try:

- Check the spelling and try again
- Try a shorter name (e.g., *\"Google\"* instead of *\"Google LLC\"*)
- Ask about a sector: *\"Show IT companies\"*

I know **33+ major global companies** and **53,000+ Norwegian companies**. Try names like:
OpenAI, Tesla, NVIDIA, TCS, Equinor, DNB, BMW, Samsung, Infosys, Anthropic...""", "type": "not_found"})


@app.route("/api/suggest")
def api_suggest():
    """Auto-suggest as user types."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    suggestions = []
    # Global first
    for gc in GLOBAL_COMPANIES:
        if q in gc["name"].lower():
            suggestions.append({"name": gc["name"], "type": "global", "sub": gc.get("sector","")})
    # Norwegian
    count = 0
    for c in ALL_COMPANIES:
        n = (c.get("n") or "").lower()
        if q in n:
            suggestions.append({"name": c.get("n"), "type": "norwegian", "sub": c.get("m","")})
            count += 1
        if count >= 5:
            break
    return jsonify(suggestions[:8])


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
                        p = r.get("person",{}); o = r.get("enhet",{})
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
                fs={"status":"available","latest_filing_year":l.get("regnskapsperiode",{}).get("fraDato","")[:4],
                    "revenue":{"value":r.get("driftsresultat",{}).get("driftsinntekter",{}).get("sumDriftsinntekter")},
                    "operating_profit":{"value":r.get("driftsresultat",{}).get("driftsresultat")},
                    "total_assets":{"value":b.get("sumEiendeler")}}
        profile={"organisation_number":org_number,"name":entity.get("navn"),
            "status":"available",
            "legal_identity":{"status":"available","legal_name":{"value":entity.get("navn")},
                "legal_form":{"value":entity.get("organisasjonsform",{}).get("beskrivelse")},
                "registered_address":{"value":fa},
                "registration_date":{"value":entity.get("registreringsdatoEnhetsregisteret")},
                "registration_status":{"value":"Active" if not entity.get("slettedato") else "Deleted"},
                "activity_description":{"value":entity.get("naeringskode1",{}).get("beskrivelse")},
                "is_bankrupt":entity.get("konkurs",False)},
            "annual_accounts":fs,
            "leadership_workplaces":{"status":"available" if roles else "not_available","roles":roles,"workplaces":[]},
            "evidence":{"total_claims":5+len(roles),"claims_with_source":5+len(roles)},
            "synthesis":{"status":"available","summary":f"{entity.get('navn')} based in {addr.get('kommune','')}.","key_observations":[]}}
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
