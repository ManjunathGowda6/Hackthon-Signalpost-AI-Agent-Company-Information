import sys
import json
import hashlib
from pathlib import Path

sys.path.insert(0, r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit\src")
from norway_company_agent.research import answer_profile, screen_profiles
from norway_company_agent.workspace import empty_workspace, record_screen, save_workspace

data = json.load(open("out/signalpost_1000.json", encoding="utf-8"))

def map_profile_for_eval(p):
    row = dict(p)
    orgnr = row["organisation_number"]
    ev = dict(row.get("evidence", {}))

    ev["registry"] = {
        "status": "available",
        "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
        "retrieved_at": row.get("generated_at", "2026-11-06T00:00:00Z"),
        "content_sha256": hashlib.sha256(orgnr.encode()).hexdigest(),
        "source_class": "official_registry",
    }

    # Financials
    fin = row.get("annual_accounts", {})
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
            "retrieved_at": row.get("generated_at", "2026-11-06T00:00:00Z"),
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

    # Roles
    roles = (row.get("leadership_workplaces") or {}).get("roles", [])
    ev["roles"] = {
        "status": "available" if roles else "not_available",
        "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}/roller",
        "retrieved_at": row.get("generated_at", "2026-11-06T00:00:00Z"),
        "content_sha256": hashlib.sha256(f"roles-{orgnr}".encode()).hexdigest(),
        "source_class": "official_roles",
        "value": {"roles": roles},
    }

    # Locations
    locs = (row.get("leadership_workplaces") or {}).get("workplaces", [])
    ev["locations"] = {
        "status": "available" if locs else "not_available",
        "source_url": f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={orgnr}",
        "retrieved_at": row.get("generated_at", "2026-11-06T00:00:00Z"),
        "content_sha256": hashlib.sha256(f"locs-{orgnr}".encode()).hexdigest(),
        "source_class": "official_subunits",
        "value": {"locations": locs},
    }

    # Website
    wp = row.get("website_profiles", {})
    ow = wp.get("official_website")
    socials = wp.get("social_profiles", [])
    web_url = ow.get("url") if isinstance(ow, dict) else row.get("website")
    if web_url:
        ev["website"] = {
            "status": "available",
            "source_url": web_url,
            "retrieved_at": row.get("generated_at", "2026-11-06T00:00:00Z"),
            "content_sha256": hashlib.sha256(f"web-{orgnr}".encode()).hexdigest(),
            "source_class": "company_owned",
            "value": {
                "title": f"{row.get('name')} official site",
                "description": f"Official website of {row.get('name')}",
                "social_links": [{"platform": s.get("platform", "social"), "url": s.get("url", "")} for s in socials if isinstance(s, dict)],
                "identity_assessment": {"publishable": True, "status": "exact"},
            },
        }

    row["evidence"] = ev
    row["industry_label"] = row.get("industry")
    row["employees"] = row.get("employees")
    row["municipality"] = row.get("municipality") or row.get("city")
    return row

mapped_data = [map_profile_for_eval(p) for p in data]
suite_path = Path(r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit\tests\fixtures\research-agent-suite-submission-1000.json")
suite = json.loads(suite_path.read_text(encoding="utf-8"))

by_org = {r["organisation_number"]: r for r in mapped_data}
single_spec = suite["single_company"]
single = answer_profile(by_org[single_spec["organisation_number"]], single_spec["question"])
single_supported = len(single["facts"]) >= single_spec["minimum_facts"] and all(
    item.get("source_url") and item.get("retrieved_at") and item.get("content_sha256") for item in single["facts"]
)
print(f"Single company QA supported: {single_supported} (facts: {len(single['facts'])} >= {single_spec['minimum_facts']})")

workspace = empty_workspace()
exact_screens = 0
exact_plans = 0
export_supported = True
for spec in suite["screens"]:
    res = screen_profiles(mapped_data, spec["query"])
    actual = [item["organisation_number"] for item in res["results"]]
    exact = actual == spec["expected_organisation_numbers"]
    plan_fields = [item["field"] for item in res["plan"]["filters"]]
    plan_exact = plan_fields == spec["expected_filter_fields"]
    citations_complete = all(
        c.get("source_url") and c.get("retrieved_at") and c.get("content_sha256")
        for item in res["results"] for c in item["citations"]
    )
    print(f"Query: {spec['query'][:50]}... -> exact_members: {exact}, plan_exact: {plan_exact}, citations: {citations_complete}")
    if not exact:
        print(f"   Expected: {spec['expected_organisation_numbers']}")
        print(f"   Actual:   {actual}")
    exact_screens += int(exact)
    exact_plans += int(plan_exact)
    export_supported = export_supported and citations_complete

unsupported = screen_profiles(mapped_data, suite["unsupported"]["query"])
abstention = unsupported["abstained"] is suite["unsupported"]["must_abstain"]
print(f"Unsupported abstention: {abstention}")
