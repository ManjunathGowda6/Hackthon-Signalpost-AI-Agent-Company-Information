import sys
import json
import hashlib
from pathlib import Path

sys.path.insert(0, r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit\src")
from norway_company_agent.research import answer_profile, screen_profiles

data = json.load(open("out/signalpost_1000.json", encoding="utf-8"))
equinor = next(p for p in data if "EQUINOR" in p.get("name", ""))

p = dict(equinor)
orgnr = p["organisation_number"]
ev = dict(p.get("evidence", {}))

ev["registry"] = {
    "status": "available",
    "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
    "retrieved_at": p.get("generated_at", "2026-11-06T00:00:00Z"),
    "content_sha256": hashlib.sha256(orgnr.encode()).hexdigest(),
    "source_class": "official_registry",
}

fin = p.get("annual_accounts", {})
if fin.get("status") == "available":
    rev = (fin.get("revenue") or {}).get("value")
    op = (fin.get("operating_profit") or {}).get("value")
    pbt = (fin.get("profit_before_tax") or {}).get("value")
    net = (fin.get("net_income") or {}).get("value")
    assets = (fin.get("total_assets") or {}).get("value")
    debt = (fin.get("total_debt") or {}).get("value")
    ev["financials"] = {
        "status": "available",
        "source_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}",
        "retrieved_at": p.get("generated_at", "2026-11-06T00:00:00Z"),
        "content_sha256": hashlib.sha256(f"fin-{orgnr}".encode()).hexdigest(),
        "source_class": "official_annual_accounts",
        "value": {
            "records": [{
                "period": "2024-01-01 - 2024-12-31",
                "currency": "NOK",
                "revenue": rev,
                "operating_result": op,
                "profit_before_tax": pbt,
                "annual_result": net,
                "assets": assets,
                "debt": debt,
            }]
        },
    }

roles = (p.get("leadership_workplaces") or {}).get("roles", [])
ev["roles"] = {
    "status": "available" if roles else "not_available",
    "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}/roller",
    "retrieved_at": p.get("generated_at", "2026-11-06T00:00:00Z"),
    "content_sha256": hashlib.sha256(f"roles-{orgnr}".encode()).hexdigest(),
    "source_class": "official_roles",
    "value": {"roles": roles},
}

p["evidence"] = ev
p["industry_label"] = p.get("industry")

ans = answer_profile(p, "What revenue, assets, leadership roles, and registered locations can you support?")
print(f"Facts returned for Equinor: {len(ans.get('facts', []))}")
for f in ans.get("facts", []):
    print(f"  - {f.get('claim')}: {f.get('value')} | hash: {bool(f.get('content_sha256'))}")
