import os

# Load .env file for API keys
import os as _os
_env_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '.env')
if _os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                _os.environ.setdefault(_k.strip(), _v.strip())
"""Signalpost AI — Context-aware Company Intelligence Chatbot."""
import json, re, httpx
from difflib import SequenceMatcher
from pathlib import Path
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from signalpost.web.users import register_user, login_user, find_user

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)
app.secret_key = "signalpost-ai-2026"
app.permanent_session_lifetime = timedelta(days=30)

PROFILES_INDEX: dict[str, dict] = {}
ALL_COMPANIES: list[dict] = []
COMPANY_INDEX: dict[str, dict] = {}
GLOBAL_COMPANIES: list[dict] = []
GLOBAL_INDEX: dict[str, dict] = {}

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

ALIASES = {
    "google":["gogle","googl","goolge","alphabet"],"microsoft":["microsfot","microsft","msft"],
    "apple":["aapl"],"amazon":["amzn","amazone"],"nvidia":["nvdia","nvda","nvidea"],
    "tesla":["tsla","tesle"],"meta":["facebook","fb","facbook"],
    "samsung":["samsng"],"openai":["opn ai","open ai","chatgpt","gpt"],
    "anthropic":["antropic","anthopic","claude ai","claude"],
    "deepmind":["deep mind","google deepmind"],"mistral":["mistral ai"],
    "tcs":["tata consultancy","tata consulting"],"tata motors":["tatamotors","tata motor"],
    "infosys":["infy","infosis","infosys ltd","infosys limited"],"wipro":["wipro ltd"],
    "hcltech":["hcl tech","hcl"],"toyota":["toyata"],
    "bmw":["bayerische"],"equinor":["equnor","statoil"],
    "telenor":["telner"],"dnb":["dnb bank"],
    "kahoot":["kahot","kahoot!"],"stripe":["strip"],
    "salesforce":["salesfore","sfdc","crm"],"oracle":["orcle","orcl"],
    "xai":["x ai","grok","x.ai"],"hugging face":["huggingface","hugging"],
    "stability ai":["stable diffusion","stability"],
    "cohere":["coher"],"volkswagen":["vw"],
    "mercedes-benz":["mercedes","benz","daimler"],
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
            name = gc["name"].lower()
            GLOBAL_INDEX[name] = gc
            for part in re.split(r'[/\(\)]', name):
                part = part.strip()
                if len(part) >= 2: GLOBAL_INDEX[part] = gc
            for word in name.split():
                if len(word) >= 3 and word not in ('the','and','for'): GLOBAL_INDEX[word] = gc
            for key, alt_list in ALIASES.items():
                if key in name:
                    for alt in alt_list: GLOBAL_INDEX[alt] = gc
            # Index by tags too
            for tag in gc.get("tags","").split(","):
                tag = tag.strip()
                if len(tag) >= 2: GLOBAL_INDEX[tag] = gc
        print(f"  Loaded {len(GLOBAL_COMPANIES)} global companies ({len(GLOBAL_INDEX)} search keys)")


def fuzzy_score(q, t):
    q, t = q.lower().strip(), t.lower().strip()
    if q == t: return 1.0
    if q in t: return 0.9
    if t in q: return 0.85
    return SequenceMatcher(None, q, t).ratio()


def fuzzy_find_global(query):
    q = query.lower().strip()
    # 1. Exact full query match
    if q in GLOBAL_INDEX: return GLOBAL_INDEX[q]
    # 2. Try full query as fuzzy match against company names FIRST (priority)
    best_full, best_full_s = None, 0
    for gc in GLOBAL_COMPANIES:
        s = fuzzy_score(q, gc["name"])
        if s > best_full_s: best_full_s, best_full = s, gc
    if best_full_s > 0.75: return best_full
    # 3. Try multi-word combinations
    words = re.findall(r'\w+', q)
    if len(words) >= 2:
        for i in range(len(words)):
            for j in range(i+1, len(words)+1):
                phrase = ' '.join(words[i:j])
                if phrase in GLOBAL_INDEX: return GLOBAL_INDEX[phrase]
    # 4. Single word index lookup (last resort)
    for w in words:
        if len(w) >= 4 and w in GLOBAL_INDEX: return GLOBAL_INDEX[w]
    best, best_s = None, 0
    for gc in GLOBAL_COMPANIES:
        s = fuzzy_score(q, gc["name"])
        # Match against tags but with higher threshold (0.7) to avoid false positives
        for tag in gc.get('tags','').split(','):
            tag = tag.strip()
            if len(tag) >= 4:
                ts = fuzzy_score(q, tag)
                if ts >= 0.9: s = max(s, ts)
        # Match individual words against company name (strict)
        for w in words:
            if len(w) >= 4:
                ws = fuzzy_score(w, gc['name'])
                if ws > 0.8: s = max(s, ws)
        if s > best_s and s > 0.7: best_s, best = s, gc
    return best


def fuzzy_find_norwegian(query):
    """Find Norwegian companies — stricter matching to avoid false positives."""
    q = query.lower().strip()
    if not q or len(q) < 2:
        return None
    # Exact match by org number
    if q.isdigit() and len(q) == 9:
        for c in ALL_COMPANIES:
            if str(c.get("o","")) == q:
                return [c]
    # Exact name match
    exact = [c for c in ALL_COMPANIES if c.get("n","").lower() == q]
    if exact:
        return exact[:5]
    # Fuzzy match — require high score (0.7+) to avoid false positives
    from difflib import SequenceMatcher
    scored = []
    for c in ALL_COMPANIES:
        name = c.get("n","").lower()
        s = SequenceMatcher(None, q, name).ratio()
        if s >= 0.7:
            scored.append((s, c))
    if scored:
        scored.sort(key=lambda x: -x[0])
        return [x[1] for x in scored[:5]]
    # Substring match — name contains query or query contains name
    contains = [c for c in ALL_COMPANIES if q in c.get("n","").lower() or c.get("n","").lower() in q]
    if contains:
        return contains[:5]
    return None


def extract_intent(msg):
    q = msg.lower().strip()
    q = re.sub(r'[?.!,;]+$', '', q)
    noise = ['tell','me','about','what','is','who','the','a','an','show','give',
             'info','information','details','of','company','called','please','can',
             'you','do','know','say','explain','describe','search','find','look','up',
             'how','whats','whos','i','want','to','need','get','more','complete',
             'full','everything','all']
    words = re.findall(r'\w+', q)
    clean = [w for w in words if w not in noise and len(w) >= 2]
    clean_query = ' '.join(clean)

    # Detect context references
    context_refs = ['this','it','that','same','above','previous','its','their',
                    'them','he','she','his','her','the company','this company',
                    'that company','same company','more about','more details',
                    'complete info','full details','everything about']
    is_followup = any(ref in q for ref in context_refs)

    intent = "company"
    if any(w in q for w in ['sector','sectors','industry','industries','categories']): intent = "sectors"
    elif any(w in q for w in ['compare','vs','versus']): intent = "compare"
    elif any(w in q for w in ['help','what can you','how to use']): intent = "help"

    return intent, clean_query, words, is_followup


def fmt(v):
    if v is None: return "N/A"
    if isinstance(v, str): return v
    if abs(v) >= 1e9: return f"NOK {v/1e9:,.1f}B"
    if abs(v) >= 1e6: return f"NOK {v/1e6:,.1f}M"
    if abs(v) >= 1e3: return f"NOK {v/1e3:,.1f}K"
    return f"{v:,.0f}"


def build_global_deep(gc):
    """Build COMPREHENSIVE A-Z response."""
    lines = []
    lines.append(f"# {gc['name']}\n")
    lines.append(f"> {gc.get('desc','')}\n")
    lines.append("---\n")

    lines.append("## \U0001f3e2 Company Profile\n")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Full Name** | {gc['name']} |")
    lines.append(f"| **Sector** | {gc.get('sector','')} |")
    lines.append(f"| **Headquarters** | {gc.get('hq','')} |")
    lines.append(f"| **Founded** | {gc.get('founded','N/A')} |")
    lines.append(f"| **CEO / Leader** | {gc.get('ceo','N/A')} |")
    lines.append(f"| **Employees** | {gc.get('employees','N/A'):,} |")
    lines.append(f"| **Website** | [{gc.get('website','')}]({gc.get('website','')}) |")
    lines.append(f"| **Stock Ticker** | {gc.get('stock','Private')} |")
    lines.append(f"| **Type** | {'Publicly Traded' if gc.get('stock','Private') != 'Private' else 'Private Company'} |")
    if gc.get('founded'):
        lines.append(f"| **Company Age** | {2026 - gc['founded']} years |")
    lines.append("")

    lines.append("## \U0001f4ca Financial Overview\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Annual Revenue** | {gc.get('revenue','N/A')} |")
    lines.append(f"| **Net Profit** | {gc.get('profit','N/A')} |")
    lines.append(f"| **Market Capitalization** | {gc.get('market_cap','N/A')} |")
    v = gc.get('valuation','N/A')
    if v and v != 'N/A':
        lines.append(f"| **Private Valuation** | {v} |")
    lines.append(f"| **P/E Ratio** | {gc.get('pe_ratio','N/A')} |")
    lines.append(f"| **Debt/Equity** | {gc.get('debt_equity','N/A')} |")
    pr = gc.get('profit','')
    is_prof = pr.startswith('$') and 'loss' not in pr.lower()
    lines.append(f"| **Profitable?** | {'\u2705 Yes' if is_prof else '\u274c No / Pre-profit'} |")
    lines.append("")

    lines.append("## \U0001f6e0\ufe0f Products & Services\n")
    for p in gc.get('products','').split(', '):
        lines.append(f"- **{p}**")
    lines.append("")

    lines.append("## \U0001f4c8 Key Metrics\n")
    for m in gc.get('key_metrics','').split('; '):
        if m.strip():
            lines.append(f"- {m.strip()}")
    lines.append("")

    # Pros
    pros = gc.get('pros','')
    if pros:
        lines.append("## \u2705 Strengths (Pros)\n")
        for p in pros.split('; '):
            if p.strip():
                lines.append(f"- \u2705 {p.strip()}")
        lines.append("")

    # Cons
    cons = gc.get('cons','')
    if cons:
        lines.append("## \u26a0\ufe0f Weaknesses (Cons)\n")
        for c in cons.split('; '):
            if c.strip():
                lines.append(f"- \u26a0\ufe0f {c.strip()}")
        lines.append("")

    # History
    hist = gc.get('history','')
    if hist:
        lines.append("## \U0001f4dc History & Timeline\n")
        for h in hist.split('. '):
            h = h.strip().rstrip('.')
            if h:
                lines.append(f"- {h}")
        lines.append("")

    # Current Situation
    cur = gc.get('current_situation','')
    if cur:
        lines.append("## \U0001f52e Current Situation & Outlook\n")
        lines.append(f"{cur}\n")

    # Competitors
    comp = gc.get('competitors','')
    if comp:
        lines.append("## \U0001f3c1 Key Competitors\n")
        for c in comp.split(', '):
            lines.append(f"- {c.strip()}")
        lines.append("")

    # Investors
    inv = gc.get('investors','')
    if inv:
        lines.append("## \U0001f4b0 Key Investors\n")
        lines.append(f"{inv}\n")

    brreg = gc.get('brreg','')
    if brreg:
        lines.append(f"---\n\U0001f1f3\U0001f1f4 **Norwegian Registry:** [View Brreg details \u2192](/company/{brreg})\n")

    lines.append(f"---\n*Data reflects latest publicly available information. Ask me anything else about {gc['name']}!*")
    return "\n".join(lines)


def build_norwegian_deep(c, profile=None):
    """Build comprehensive response for Norwegian company."""
    org = c["o"]
    sector = SECTOR_MAP.get(c.get("s",""), c.get("nd",""))
    lines = []
    lines.append(f"# {c.get('n','Unknown')}\n")

    lines.append("## 🏢 Company Profile\n")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Organisation Number** | `{org}` |")
    lines.append(f"| **Legal Form** | {c.get('f','N/A')} |")
    lines.append(f"| **Sector** | {sector} |")
    lines.append(f"| **Municipality** | {c.get('m','N/A')} |")
    lines.append(f"| **Employees** | {c.get('e',0):,} |")
    lines.append(f"| **Industry (NACE)** | {c.get('nd','N/A')} |")
    if c.get('w'): lines.append(f"| **Website** | [{c['w']}]({c['w']}) |")
    lines.append(f"| **Source** | [Brreg Registry](https://data.brreg.no/enhetsregisteret/api/enheter/{org}) |")
    lines.append("")

    if profile:
        ev = profile.get("evidence",{}) or {}
        syn = profile.get("synthesis",{}) or {}
        aa = profile.get("annual_accounts",{}) or {}
        lw = profile.get("leadership_workplaces",{}) or {}
        li = profile.get("legal_identity",{}) or {}

        if li.get("status") == "available":
            lines.append("## 📋 Legal Identity\n")
            lines.append("| | |")
            lines.append("|---|---|")
            for key, label in [("legal_name","Legal Name"),("legal_form","Legal Form"),
                               ("registered_address","Address"),("registration_date","Registered"),
                               ("registration_status","Status"),("activity_description","Activity")]:
                val = (li.get(key) or {}).get("value")
                if val: lines.append(f"| **{label}** | {val} |")
            if li.get("is_bankrupt"): lines.append(f"| **⚠️ Bankrupt** | Yes |")
            lines.append("")

        if aa.get("status") == "available":
            lines.append("## 📊 Annual Accounts (Financial Data)\n")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            lines.append(f"| **Filing Year** | {aa.get('latest_filing_year','N/A')} |")
            for key, label in [("revenue","Revenue"),("operating_profit","Operating Profit"),
                               ("total_assets","Total Assets"),("total_equity","Total Equity")]:
                val = (aa.get(key) or {}).get("value")
                if val is not None: lines.append(f"| **{label}** | {fmt(val)} |")
            lines.append("")

        roles = lw.get("roles",[])
        if roles:
            lines.append(f"## 👥 Leadership & Management ({len(roles)} roles)\n")
            for r in roles[:12]:
                lines.append(f"- **{r.get('name','')}** — {r.get('role','')}")
            if len(roles) > 12: lines.append(f"- *...and {len(roles)-12} more registered roles*")
            lines.append("")

        if syn.get("summary"):
            lines.append("## 💡 AI Summary\n")
            lines.append(f"{syn['summary']}\n")
            obs = syn.get("key_observations",[])
            if obs:
                for o in obs[:6]: lines.append(f"- {o}")
            lines.append("")

        lines.append("## 🔍 Evidence & Verification\n")
        lines.append(f"- **Total claims:** {ev.get('total_claims',0)}")
        lines.append(f"- **Sourced claims:** {ev.get('claims_with_source',0)}")
        lines.append(f"- **Registry verified:** ✅ Data from official Brreg")
        ch = profile.get("content_hash")
        if ch: lines.append(f"- **Content hash:** `{ch[:16]}...`")
    else:
        lines.append("\n> This is a basic listing from the registry. I can fetch live details — just ask!\n")

    lines.append(f"\n---\n*Source: Norwegian Business Registry (Brreg). Ask me anything else about this company!*")
    return "\n".join(lines)


def enrich_live(org_number):
    """Fetch real-time data from Brreg for any org number."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}")
            if resp.status_code != 200: return None
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
                        p,o = r.get("person",{}), r.get("enhet",{})
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
        return {"organisation_number":org_number,"name":entity.get("navn"),
            "status":"available","source":"real_time",
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
            "synthesis":{"status":"available",
                "summary":f"{entity.get('navn')} is a {entity.get('organisasjonsform',{}).get('beskrivelse','')} based in {addr.get('kommune','')}.",
                "key_observations":[]}}
    except: return None



# ── Web Enrichment for Detail Queries ──
import urllib.request, urllib.parse

def web_enrich_company(company_name):
    """Fetch extra info from Wikipedia for deeper detail."""
    try:
        wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(company_name)}"
        req = urllib.request.Request(wiki_url, headers={"User-Agent": "SignalpostBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("type") == "standard":
                return data.get("extract", "")
    except Exception:
        pass
    return ""



def gemini_enrich_company(gc):
    """Use Gemini AI to generate real-time enriched info for a known company."""
    import urllib.request, urllib.parse
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return None

    prompt = f"""Generate a detailed company profile for {gc['name']} ({gc.get('sector','')}, HQ: {gc.get('hq','')}, CEO: {gc.get('ceo','')}, Founded: {gc.get('founded','')}, Revenue: {gc.get('revenue','')}).

Use markdown. Include these sections with emojis:
# {gc['name']}
[1-line description]
## Company Profile (table: Name, Sector, HQ, Founded, CEO, Employees, Website, Stock, Type)
## Financial Overview (table: Revenue, Profit, Market Cap, P/E, Profitable?)
## Products & Services (bullet list)
## Key Metrics (bullet list)
## Strengths/Pros (5 items with checkmark)
## Weaknesses/Cons (4 items with warning)
## History & Timeline (key milestones with years)
## Current Situation & Outlook (2-3 sentences)
## Key Competitors (list)
End with: *Generated in real-time by Signalpost AI using Gemini.*"""

    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096}
        })
        req = urllib.request.Request(api_url, data=payload.encode("utf-8"),
                                    headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            candidates = result.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text and len(text) > 200:
                    return text
    except Exception:
        pass
    return None


def gemini_ai_generate_company(query):
    """Use Google Gemini AI + Wikipedia to generate real-time company profiles."""
    import urllib.request, urllib.parse

    # Step 1: Gather context from Wikipedia
    wiki_context = ""
    wiki_title = query.title()
    try:
        # Search Wikipedia for the company
        search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query + ' company')}&format=json&srlimit=3"
        req = urllib.request.Request(search_url, headers={"User-Agent": "SignalpostBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("query", {}).get("search", [])
            if results:
                wiki_title = results[0]["title"]
                # Get full summary
                surl = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(wiki_title)}"
                req2 = urllib.request.Request(surl, headers={"User-Agent": "SignalpostBot/1.0"})
                with urllib.request.urlopen(req2, timeout=5) as resp2:
                    sdata = json.loads(resp2.read().decode())
                    if sdata.get("type") == "standard":
                        wiki_context = sdata.get("extract", "")
                        wiki_title = sdata.get("title", wiki_title)
    except Exception:
        pass

    # Step 2: Call Gemini AI to generate structured company profile
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    prompt = f"""You are a company intelligence analyst. Generate a comprehensive company profile for "{query}" using the following format. If you have information from the context below, use it. Otherwise use your knowledge.

Context from Wikipedia: {wiki_context[:1000] if wiki_context else "No Wikipedia article found."}

Generate the profile in this EXACT markdown format (fill ALL sections):

# [Company Name]

[One-line description of the company]

## Company Profile
| Field | Value |
|---|---|
| Full Name | [name] |
| Sector | [sector] |
| Headquarters | [city, country] |
| Founded | [year] |
| CEO / Leader | [name] |
| Employees | [number] |
| Website | [url] |
| Stock Ticker | [ticker or Private] |
| Type | [Public/Private] |

## Financial Overview
| Metric | Value |
|---|---|
| Annual Revenue | [amount] |
| Net Profit | [amount] |
| Market Cap | [amount or Private] |
| Profitable? | [Yes/No] |

## Products & Services
[List key products/services as bullet points]

## Key Metrics
[4-5 important metrics as bullet points]

## Strengths (Pros)
[5-6 strengths as bullet points with checkmark emoji]

## Weaknesses (Cons)
[4-5 weaknesses as bullet points with warning emoji]

## History & Timeline
[Key milestones as bullet points with years]

## Current Situation & Outlook
[2-3 sentences about current state and future]

## Key Competitors
[List 5-6 competitors]

---
*Generated in real-time by Signalpost AI using Gemini. Data may not be 100% current.*
"""

    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096}
        })
        req = urllib.request.Request(
            api_url,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            candidates = result.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text and len(text) > 100:
                    return text, wiki_title
    except Exception as e:
        # Gemini failed — fall back to Wikipedia-only response
        pass

    # Fallback: Wikipedia-only response (no Gemini)
    if wiki_context:
        lines = []
        lines.append(f"# {wiki_title}")
        lines.append("")
        lines.append(f"> {wiki_context[:500]}")
        lines.append("")
        lines.append("---")
        lines.append(f"*Wikipedia summary. Gemini AI generation unavailable.*")
        return "\n".join(lines), wiki_title

    return None


def web_search_company(query):
    """Search web for unknown companies: Wikipedia + DuckDuckGo Lite (httpx)."""
    import urllib.request, urllib.parse, re as regex

    q = query.strip()
    if not q or len(q) < 2:
        return None

    # ── Layer 1: Wikipedia Search ──
    wiki_summary = ""
    wiki_title = q.title()
    try:
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(q + ' company')}&format=json&srlimit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "SignalpostBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("query", {}).get("search", [])
            if results:
                best = results[0]["title"]
                surl = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(best)}"
                req2 = urllib.request.Request(surl, headers={"User-Agent": "SignalpostBot/1.0"})
                with urllib.request.urlopen(req2, timeout=5) as resp2:
                    sdata = json.loads(resp2.read().decode())
                    if sdata.get("type") == "standard":
                        wiki_summary = sdata.get("extract", "")
                        wiki_title = sdata.get("title", best)
    except Exception:
        pass

    # ── Layer 2: DuckDuckGo Lite via httpx (bypasses bot detection) ──
    ddg_results = []
    try:
        search_q = urllib.parse.quote(q + " company")
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(
                f"https://lite.duckduckgo.com/lite/?q={search_q}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            if resp.status_code == 200:
                html = resp.text
                # Parse DDG Lite HTML — links contain uddg= redirect URLs
                link_pattern = regex.compile(
                    r'<a[^>]*href="[^"]*uddg=([^"&]+)[^"]*"[^>]*>(.*?)</a>',
                    regex.DOTALL
                )
                snippet_pattern = regex.compile(
                    r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
                    regex.DOTALL
                )
                links = link_pattern.findall(html)
                snippets = snippet_pattern.findall(html)

                for i, (url_enc, title_html) in enumerate(links[:5]):
                    clean_title = regex.sub(r'<[^>]+>', '', title_html).strip()
                    clean_url = urllib.parse.unquote(url_enc)
                    clean_snippet = ""
                    if i < len(snippets):
                        clean_snippet = regex.sub(r'<[^>]+>', '', snippets[i]).strip()
                    if clean_title:
                        ddg_results.append({
                            "title": clean_title, "snippet": clean_snippet, "url": clean_url
                        })
                        if not wiki_summary and clean_snippet:
                            wiki_summary = clean_snippet
                            wiki_title = clean_title
    except Exception:
        pass

    # ── Layer 3: DuckDuckGo Instant Answers API ──
    if not wiki_summary and not ddg_results:
        try:
            ddg_api = f"https://api.duckduckgo.com/?q={urllib.parse.quote(q)}&format=json&no_html=1"
            req = urllib.request.Request(ddg_api, headers={"User-Agent": "SignalpostBot/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                abstract = data.get("AbstractText", "")
                if abstract:
                    wiki_summary = abstract
                    wiki_title = data.get("Heading", q.title())
        except Exception:
            pass

    if not wiki_summary and not ddg_results:
        return None

    # Build response
    lines = []
    lines.append(f"# {wiki_title}")
    lines.append("")
    if wiki_summary:
        lines.append(f"> {wiki_summary[:500]}")
        lines.append("")
        lines.append("---")
        lines.append("")
    if ddg_results:
        lines.append("## \U0001f310 Web Search Results")
        lines.append("")
        for i, r in enumerate(ddg_results[:5]):
            lines.append(f"**{i+1}. {r['title']}**")
            if r["snippet"]:
                lines.append(f"{r['snippet'][:200]}")
            if r.get("url"):
                lines.append(f"[Source]({r['url']})")
            lines.append("")
    lines.append("---")
    lines.append(f"*\U0001f50d Real-time web search. Not in our database of **{len(GLOBAL_COMPANIES)} indexed companies**.*")
    return "\n".join(lines), wiki_title


@app.route("/")
def index():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for("login"))
    return render_template("chat.html", user_email=user_email)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_email"):
        return redirect(url_for("index"))
    
    error = None
    email_val = request.args.get("email", "").strip()
    
    if request.method == "POST":
        email_val = request.form.get("email", "").strip().lower()
        success, msg, user = login_user(email_val)
        if success and user:
            session.permanent = True
            session["user_email"] = user["email"]
            return redirect(url_for("index"))
        else:
            error = msg
            
    return render_template("login.html", error=error, email=email_val)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_email"):
        return redirect(url_for("index"))
        
    error = None
    email_val = request.args.get("email", "").strip()
    
    if request.method == "POST":
        email_val = request.form.get("email", "").strip().lower()
        success, msg, user = register_user(email_val)
        if success and user:
            session.permanent = True
            session["user_email"] = user["email"]
            return redirect(url_for("index"))
        else:
            error = msg
            
    return render_template("register.html", error=error, email=email_val)


@app.route("/logout")
def logout():
    session.pop("user_email", None)
    return redirect(url_for("login"))



# Product-to-company aliases (ChatGPT → OpenAI, etc.)
PRODUCT_ALIASES = {
    "chatgpt": ("OpenAI", "ChatGPT is a product of **OpenAI**"),
    "gpt": ("OpenAI", "GPT models are built by **OpenAI**"),
    "gpt4": ("OpenAI", "GPT-4 is built by **OpenAI**"),
    "gpt-4": ("OpenAI", "GPT-4 is built by **OpenAI**"),
    "gpt4o": ("OpenAI", "GPT-4o is built by **OpenAI**"),
    "dall-e": ("OpenAI", "DALL-E is created by **OpenAI**"),
    "dalle": ("OpenAI", "DALL-E is created by **OpenAI**"),
    "sora": ("OpenAI", "Sora is created by **OpenAI**"),
    "copilot": ("Microsoft", "Copilot is a product of **Microsoft**"),
    "github copilot": ("Microsoft", "GitHub Copilot is powered by **Microsoft** and OpenAI"),
    "gemini": ("Google DeepMind", "Gemini AI is built by **Google DeepMind**"),
    "bard": ("Google DeepMind", "Bard (now Gemini) is built by **Google DeepMind**"),
    "claude": ("Anthropic", "Claude is built by **Anthropic**"),
    "alexa": ("Amazon", "Alexa is a product of **Amazon**"),
    "siri": ("Apple", "Siri is a product of **Apple**"),
    "android": ("Google", "Android is developed by **Google**"),
    "iphone": ("Apple", "iPhone is made by **Apple**"),
    "xbox": ("Microsoft", "Xbox is made by **Microsoft**"),
    "playstation": ("Sony", "PlayStation is made by **Sony**"),
    "windows": ("Microsoft", "Windows is made by **Microsoft**"),
    "activa": ("Honda", "Activa is made by **Honda**"),
    "apache": ("TVS Motor", "Apache is made by **TVS Motor**"),
    "jupiter": ("TVS Motor", "Jupiter is made by **TVS Motor**"),
    "pulsar": ("Bajaj Auto", "Pulsar is made by **Bajaj Auto**"),
    "bullet": ("Royal Enfield", "Bullet is made by **Royal Enfield**"),
    "nexon": ("Tata Motors", "Nexon is made by **Tata Motors**"),
    "seltos": ("Kia", "Seltos is made by **Kia**"),
    "creta": ("Hyundai", "Creta is made by **Hyundai**"),
}

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    msg = data.get("message","").strip()
    context = data.get("context", {})  # Last company discussed, sent from frontend
    last_company_name = context.get("last_company", "")

    if not msg:
        return jsonify({"reply":"Hi! Ask me about any company.","type":"text","company":""})

    intent, clean_q, words, is_followup = extract_intent(msg)

    # ── Follow-up: user is asking about the SAME company ──
    if is_followup and last_company_name:
        # Re-search the last company
        gc = fuzzy_find_global(last_company_name)
        if gc:
            reply = build_global_deep(gc)
            detail_words = ['detail','more','explain','everything','complete','full','depth','elaborate','deep','all about']
            if any(dw in msg.lower() for dw in detail_words):
                wiki = web_enrich_company(gc["name"])
                if wiki:
                    reply += "\n\n## 🌐 Additional Context (Live Web)\n\n" + wiki + "\n"
            return jsonify({"reply": reply, "type":"company", "source":"global", "company":gc["name"]})
        nor = fuzzy_find_norwegian(last_company_name)
        if nor:
            c = nor[0]
            profile = PROFILES_INDEX.get(c["o"]) or enrich_live(c["o"])
            return jsonify({"reply": build_norwegian_deep(c, profile), "type":"company", "source":"norwegian", "company":c.get("n","")})

    # ── Help ──
    if intent == "help":
        return jsonify({"reply":"""I'm your Company Intelligence Assistant. Here's what I can do:\n
**🔍 Ask about any company:**
- *"Tell me about OpenAI"* or *"opn ai"* (I handle typos!)
- *"TCS company details"* or *"chatgpt"* (I know aliases!)
- Then ask *"give me more details"* and I'll know you mean the same company

**🏭 Browse sectors:** *"Show IT companies"*, *"Banking sector"*

**🌍 I know:** 33+ global companies and 53,000+ Norwegian companies with real-time Brreg data.

Just type any company name!""","type":"help","company":""})

    # ── Sectors ──
    if intent == "sectors":
        lines = ["# 📂 Available Sectors\n"]
        for code, name in sorted(SECTOR_MAP.items(), key=lambda x: x[1]):
            count = sum(1 for c in ALL_COMPANIES if c.get("s") == code)
            if count > 0: lines.append(f"- **{name}** — {count:,} companies")
        lines.append(f"\nJust say *\"Show IT & Software companies\"* to explore.")
        return jsonify({"reply":"\n".join(lines),"type":"sectors","company":""})

    
    # ── Product alias check (ChatGPT → OpenAI, etc.) ──
    product_note = ""
    for alias, (company_name, note) in PRODUCT_ALIASES.items():
        if alias in msg.lower():
            gc = fuzzy_find_global(company_name)
            if gc:
                product_note = f"> *{note}*\n\n"
                reply = product_note + build_global_deep(gc)
                return jsonify({"reply": reply, "type":"company", "source":"global", "company":gc["name"]})


    # ── Global company (fuzzy) ──
    gc = fuzzy_find_global(clean_q or msg)
    if gc:
        # Try Gemini AI for real-time enriched company info
        enriched = gemini_enrich_company(gc)
        if enriched:
            return jsonify({"reply": enriched, "type":"company", "source":"gemini_enriched", "company":gc["name"]})
        # Fallback to database if Gemini unavailable
        reply = build_global_deep(gc)
        return jsonify({"reply": reply, "type":"company", "source":"global", "company":gc["name"]})

    # ── Gemini AI RAG: Real-time company info generation ──
    ai_result = gemini_ai_generate_company(clean_q or msg)
    if ai_result:
        reply, found_name = ai_result
        return jsonify({"reply": reply, "type":"ai_generated", "source":"gemini_ai", "company": found_name})

    # ── Web Search fallback ──
    web_result = web_search_company(clean_q or msg)
    if web_result:
        reply, found_name = web_result
        return jsonify({"reply": reply, "type":"web", "source":"web_search", "company": found_name})

    # ── Norwegian company (fuzzy) ──
    nor = fuzzy_find_norwegian(clean_q or msg)
    if nor:
        if len(nor) == 1:
            c = nor[0]
            profile = PROFILES_INDEX.get(c["o"]) or enrich_live(c["o"])
            return jsonify({"reply": build_norwegian_deep(c, profile), "type":"company", "source":"norwegian", "company":c.get("n","")})
        else:
            lines = [f"I found **{len(nor)} companies** matching your search:\n"]
            for c in nor:
                sector = SECTOR_MAP.get(c.get("s",""),"")
                lines.append(f"### {c.get('n','')}")
                lines.append(f"*{sector}* | {c.get('m','')} | {c.get('e',0):,} employees")
                lines.append(f"Say *\"{c.get('n','')}\"* for full details.\n")
            return jsonify({"reply":"\n".join(lines),"type":"list","source":"norwegian","company":""})

    # ── Sector search ──
    for code, name in SECTOR_MAP.items():
        if name.lower() in msg.lower() or any(w in name.lower().split() for w in words if len(w) >= 3):
            sector_cos = [c for c in ALL_COMPANIES if c.get("s") == code][:10]
            global_cos = [g for g in GLOBAL_COMPANIES if name.lower() in g.get("sector","").lower()]
            lines = [f"# {name} Sector\n"]
            if global_cos:
                lines.append("## 🌍 Global Leaders\n")
                for g in global_cos[:5]:
                    lines.append(f"**{g['name']}** — {g.get('hq','')} | {g.get('revenue','')} revenue | {g.get('employees','N/A'):,} employees\n")
            if sector_cos:
                lines.append("## 🇳🇴 Norwegian Companies\n")
                for c in sector_cos:
                    lines.append(f"- **{c.get('n','')}** — {c.get('e',0):,} employees | {c.get('m','')}")
            return jsonify({"reply":"\n".join(lines),"type":"sector","company":""})

    # ── Live Brreg ──
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={msg}&size=5")
        if resp.status_code == 200:
            entities = resp.json().get("_embedded",{}).get("enheter",[])
            if entities:
                lines = ["I searched the Norwegian Business Registry live:\n"]
                for e in entities:
                    lines.append(f"### {e.get('navn','')}")
                    lines.append(f"`{e.get('organisasjonsnummer','')}` | {e.get('forretningsadresse',{}).get('kommune','')} | {e.get('antallAnsatte',0) or 0:,} employees")
                    lines.append(f"Say *\"{e.get('navn','')}\"* for complete info.\n")
                return jsonify({"reply":"\n".join(lines),"type":"list","source":"live","company":""})
    except: pass

    return jsonify({"reply":f"""I couldn't find **\"{msg}\"**. Try:
- Check spelling or use a shorter name
- Ask: *\"Show all sectors\"*
- I know: OpenAI, Tesla, NVIDIA, TCS, Equinor, DNB, BMW, Samsung, Anthropic...""","type":"not_found","company":""})


@app.route("/api/suggest")
def api_suggest():
    q = request.args.get("q","").strip().lower()
    if len(q) < 2: return jsonify([])
    suggestions = []
    for gc in GLOBAL_COMPANIES:
        if q in gc["name"].lower():
            suggestions.append({"name":gc["name"],"type":"global","sub":gc.get("sector","")})
    count = 0
    for c in ALL_COMPANIES:
        if q in (c.get("n") or "").lower():
            suggestions.append({"name":c.get("n"),"type":"norwegian","sub":c.get("m","")})
            count += 1
        if count >= 5: break
    return jsonify(suggestions[:8])


@app.route("/api/lookup/<org_number>")
def api_lookup(org_number):
    if org_number in PROFILES_INDEX: return jsonify(PROFILES_INDEX[org_number])
    result = enrich_live(org_number)
    if result: return jsonify(result)
    return jsonify({"error":"Not found"}), 404


@app.route("/company/<org_number>")
def company_detail(org_number):
    if org_number in PROFILES_INDEX:
        return render_template("company.html", profile=PROFILES_INDEX[org_number], org=org_number)
    return render_template("company_live.html", org=org_number)


def create_app(profiles_path="out/signalpost_final.json"):
    load_all()
    return app
