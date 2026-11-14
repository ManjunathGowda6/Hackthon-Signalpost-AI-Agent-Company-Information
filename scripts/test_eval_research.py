import json
import sys
from pathlib import Path

STARTER_KIT = Path(r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit")
sys.path.insert(0, str(STARTER_KIT / "src"))
from norway_company_agent.research import answer_profile, screen_profiles

rows = [json.loads(line) for line in Path("out/profiles.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"Total rows: {len(rows)}")

# Test single company QA on Equinor (923609016)
eq = [r for r in rows if r["organisation_number"] == "923609016"][0]
ans = answer_profile(eq, "Who leads this company and what financial facts and locations are available?")
print(f"Equinor QA facts count: {len(ans['facts'])}")
for f in ans["facts"][:5]:
    print(f"  - {f['claim']}: {f['value']} (src: {f['source_url']})")

# Check all citations have source_url, retrieved_at, content_sha256
all_valid = all(
    item.get("source_url") and item.get("retrieved_at") and item.get("content_sha256")
    for item in ans["facts"]
)
print(f"All facts have source_url, retrieved_at, content_sha256: {all_valid}")

# Test screen queries
q1 = "companies in Oslo with more than 5 employees and revenue over 1 million top 5 by revenue"
res1 = screen_profiles(rows, q1)
print(f"Query 1: {q1} -> results: {len(res1['results'])}, abstained: {res1['abstained']}")
for r in res1["results"][:3]:
    print(f"  - {r['organisation_number']}: {r['name']}, rev={r['revenue']}, emp={r['employees']}")

q2 = "top 5 by revenue"
res2 = screen_profiles(rows, q2)
print(f"Query 2: {q2} -> results: {len(res2['results'])}, abstained: {res2['abstained']}")
for r in res2["results"]:
    print(f"  - {r['organisation_number']}: {r['name']}, rev={r['revenue']}")

q_unsupp = "companies in Oslo with positive Glassdoor sentiment"
res_unsupp = screen_profiles(rows, q_unsupp)
print(f"Unsupported query -> abstained: {res_unsupp['abstained']}, reason: {res_unsupp.get('reason')}")
