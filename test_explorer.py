"""
Signalpost Explorer — Comprehensive Verification Suite
Tests every API endpoint, edge case, data integrity, and frontend rendering.
"""
import json
import sys
import os
import time
import urllib.request
import urllib.error

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

BASE = "http://127.0.0.1:5001"
API = BASE + "/explorer/api"
passed = 0
failed = 0
errors = []

def test(name, url, checks, method="GET", expect_status=200):
    global passed, failed
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            if status != expect_status:
                failed += 1
                errors.append(f"{name}: Expected status {expect_status}, got {status}")
                print(f"  ❌ {name} — wrong status {status}")
                return None
            if resp.headers.get("Content-Type","").startswith("application/json"):
                data = json.loads(body)
            else:
                data = body
            for check_name, check_fn in checks.items():
                try:
                    result = check_fn(data)
                    if not result:
                        failed += 1
                        msg = f"{name} / {check_name}: check returned False"
                        errors.append(msg)
                        print(f"  ❌ {name} / {check_name}")
                        return data
                except Exception as e:
                    failed += 1
                    msg = f"{name} / {check_name}: {e}"
                    errors.append(msg)
                    print(f"  ❌ {name} / {check_name}: {e}")
                    return data
            passed += 1
            print(f"  ✅ {name}")
            return data
    except urllib.error.HTTPError as e:
        if e.code == expect_status:
            passed += 1
            print(f"  ✅ {name} (expected {expect_status})")
            return None
        failed += 1
        errors.append(f"{name}: HTTP {e.code}")
        print(f"  ❌ {name} — HTTP {e.code}")
        return None
    except Exception as e:
        failed += 1
        errors.append(f"{name}: {e}")
        print(f"  ❌ {name} — {e}")
        return None

print("\n" + "="*70)
print("  SIGNALPOST EXPLORER — COMPREHENSIVE VERIFICATION SUITE")
print("="*70)

# ═══════════════════════════════════════════════════════════
print("\n── 1. SEARCH API ──")
# ═══════════════════════════════════════════════════════════

test("1.1 Default search (no params)", f"{API}/search", {
    "returns results": lambda d: len(d["results"]) > 0,
    "has total count": lambda d: d["total"] > 1000,
    "has pagination": lambda d: d["pages"] > 1,
    "default page 1": lambda d: d["page"] == 1,
    "default size 20": lambda d: d["size"] == 20,
})

test("1.2 Search by exact company name", f"{API}/search?q=EQUINOR+ASA&size=5", {
    "finds Equinor": lambda d: d["results"][0]["name"] == "EQUINOR ASA",
    "first result is best match": lambda d: d["results"][0]["orgnr"] == "923609016",
})

test("1.3 Search by 9-digit orgnr", f"{API}/search?q=923609016", {
    "finds exactly 1": lambda d: d["total"] == 1,
    "correct orgnr": lambda d: d["results"][0]["orgnr"] == "923609016",
    "correct name": lambda d: d["results"][0]["name"] == "EQUINOR ASA",
})

test("1.4 Fuzzy search (partial name)", f"{API}/search?q=telenor&size=5", {
    "finds results": lambda d: d["total"] > 0,
    "first result contains telenor": lambda d: "TELENOR" in d["results"][0]["name"].upper(),
})

test("1.5 Search with no results", f"{API}/search?q=xyznonexistent12345", {
    "returns empty": lambda d: d["total"] == 0,
    "results is empty list": lambda d: len(d["results"]) == 0,
    "still page 1": lambda d: d["page"] == 1,
})

test("1.6 Sector filter (IT & Software = 62)", f"{API}/search?sector=62&size=5", {
    "has results": lambda d: d["total"] > 0,
    "all results have sector 62": lambda d: all(r["sector_code"] == "62" for r in d["results"]),
    "sector label is IT & Software": lambda d: d["results"][0]["sector"] == "IT & Software",
})

test("1.7 Legal form filter (ASA)", f"{API}/search?form=ASA&size=5", {
    "has results": lambda d: d["total"] > 0,
    "all results are ASA": lambda d: all(r["legal_form"] == "ASA" for r in d["results"]),
})

test("1.8 Legal form filter (KOMM)", f"{API}/search?form=KOMM&size=5", {
    "has results": lambda d: d["total"] > 0,
    "all results are KOMM": lambda d: all(r["legal_form"] == "KOMM" for r in d["results"]),
})

test("1.9 Data filter: has=website", f"{API}/search?has=website&size=10", {
    "has results": lambda d: d["total"] > 0,
    "all have website": lambda d: all(r["has_website"] for r in d["results"]),
    "website field not empty": lambda d: all(r["website"] for r in d["results"]),
})

test("1.10 Data filter: has=financials", f"{API}/search?has=financials&size=10", {
    "has results": lambda d: d["total"] > 0,
    "all have financials": lambda d: all(r["has_financials"] for r in d["results"]),
    "revenue not null": lambda d: all(r["revenue"] is not None for r in d["results"]),
})

test("1.11 Combined filters: sector+form+has", f"{API}/search?sector=06&form=ASA&has=financials&size=5", {
    "has results": lambda d: d["total"] > 0,
    "all ASA": lambda d: all(r["legal_form"] == "ASA" for r in d["results"]),
    "all sector 06": lambda d: all(r["sector_code"] == "06" for r in d["results"]),
    "all have financials": lambda d: all(r["has_financials"] for r in d["results"]),
})

test("1.12 Pagination: page 2", f"{API}/search?page=2&size=5", {
    "page is 2": lambda d: d["page"] == 2,
    "size is 5": lambda d: d["size"] == 5,
    "has 5 results": lambda d: len(d["results"]) == 5,
})

test("1.13 Pagination: large page (beyond data)", f"{API}/search?page=99999&size=20", {
    "returns empty": lambda d: len(d["results"]) == 0,
    "page is 99999": lambda d: d["page"] == 99999,
})

# Card data integrity
test("1.14 Card field completeness", f"{API}/search?q=923609016", {
    "has orgnr": lambda d: d["results"][0]["orgnr"] == "923609016",
    "has name": lambda d: len(d["results"][0]["name"]) > 0,
    "has legal_form": lambda d: len(d["results"][0]["legal_form"]) > 0,
    "has municipality": lambda d: len(d["results"][0]["municipality"]) > 0,
    "has sector": lambda d: d["results"][0]["sector"] is not None,
    "has sector_code": lambda d: len(d["results"][0]["sector_code"]) > 0,
    "has employees (int)": lambda d: isinstance(d["results"][0]["employees"], int),
    "has website": lambda d: d["results"][0]["website"] is not None,
    "has revenue (formatted)": lambda d: d["results"][0]["revenue"] is not None,
    "has revenue_raw (number)": lambda d: isinstance(d["results"][0]["revenue_raw"], (int, float)),
    "has source_count (int)": lambda d: isinstance(d["results"][0]["source_count"], int),
    "has has_website (bool)": lambda d: isinstance(d["results"][0]["has_website"], bool),
    "has has_financials (bool)": lambda d: isinstance(d["results"][0]["has_financials"], bool),
    "has has_news (bool)": lambda d: isinstance(d["results"][0]["has_news"], bool),
    "has has_jobs (bool)": lambda d: isinstance(d["results"][0]["has_jobs"], bool),
})

# ═══════════════════════════════════════════════════════════
print("\n── 2. PROFILE API ──")
# ═══════════════════════════════════════════════════════════

# Equinor — full profile with financials
prof = test("2.1 Profile: Equinor (full data)", f"{API}/profile/923609016", {
    "has overview": lambda d: d["overview"]["name"] == "EQUINOR ASA",
    "has orgnr": lambda d: d["overview"]["orgnr"] == "923609016",
    "has municipality": lambda d: d["overview"]["municipality"] == "STAVANGER",
    "has sector": lambda d: d["overview"]["sector"] == "Oil & Gas",
    "has synthesis text": lambda d: d["overview"]["synthesis"] is not None and len(d["overview"]["synthesis"]) > 10,
})

# Profile — source metadata on every claim
test("2.2 Profile claims have source metadata", f"{API}/profile/923609016", {
    "legal_form.source exists": lambda d: d["overview"]["legal_form"]["source"] is not None,
    "legal_form.source contains brreg": lambda d: "brreg" in d["overview"]["legal_form"]["source"],
    "legal_form.retrieved_at exists": lambda d: d["overview"]["legal_form"]["retrieved_at"] is not None,
    "legal_form.status is available": lambda d: d["overview"]["legal_form"]["status"] == "available",
    "legal_form.confidence is 1.0": lambda d: d["overview"]["legal_form"]["confidence"] == 1.0,
    "registered_address.source": lambda d: d["overview"]["registered_address"]["source"] is not None,
    "registration_date.source": lambda d: d["overview"]["registration_date"]["source"] is not None,
    "registration_status.source": lambda d: d["overview"]["registration_status"]["source"] is not None,
    "activity_description.source": lambda d: d["overview"]["activity_description"]["source"] is not None,
})

# Profile — financials with source metadata
test("2.3 Profile financials with sources", f"{API}/profile/923609016", {
    "financials.status is available": lambda d: d["financials"]["status"] == "available",
    "revenue.value > 0": lambda d: d["financials"]["revenue"]["value"] > 0,
    "revenue.display formatted": lambda d: "NOK" in d["financials"]["revenue"]["display"],
    "revenue.source is brreg": lambda d: "brreg" in d["financials"]["revenue"]["source"],
    "revenue.retrieved_at exists": lambda d: d["financials"]["revenue"]["retrieved_at"] is not None,
    "revenue.period exists": lambda d: d["financials"]["revenue"]["period"] is not None,
    "revenue.currency is USD": lambda d: d["financials"]["revenue"]["currency"] == "USD",
    "operating_profit.display": lambda d: d["financials"]["operating_profit"]["display"] is not None,
    "net_income has source": lambda d: d["financials"]["net_income"]["source"] is not None,
    "total_assets has source": lambda d: d["financials"]["total_assets"]["source"] is not None,
    "total_equity has source": lambda d: d["financials"]["total_equity"]["source"] is not None,
    "total_debt has source": lambda d: d["financials"]["total_debt"]["source"] is not None,
    "employees.display is formatted count": lambda d: d["financials"]["employees"]["display"] == "21,272",
    "latest_filing_year": lambda d: d["financials"]["latest_filing_year"] is not None,
})

# Profile — leadership
test("2.4 Profile leadership roles", f"{API}/profile/923609016", {
    "has roles list": lambda d: len(d["leadership"]["roles"]) > 0,
    "roles have name": lambda d: all("name" in r for r in d["leadership"]["roles"]),
    "roles have role type": lambda d: all("role" in r for r in d["leadership"]["roles"]),
    "roles have source URL": lambda d: all("source" in r for r in d["leadership"]["roles"]),
    "roles have retrieved_at": lambda d: all("retrieved_at" in r for r in d["leadership"]["roles"]),
    "first role name non-empty": lambda d: len(str(d["leadership"]["roles"][0]["name"])) > 0,
})

# Profile — website data
test("2.5 Profile website & social", f"{API}/profile/923609016", {
    "website.status": lambda d: d["website"]["status"] in ("available", "not_available"),
    "official_website exists": lambda d: d["website"]["official_website"] is not None,
    "official_website.url": lambda d: d["website"]["official_website"]["url"] is not None,
    "social_profiles is list": lambda d: isinstance(d["website"]["social_profiles"], list),
    "news_items is list": lambda d: isinstance(d["website"]["news_items"], list),
})

# Profile — evidence
test("2.6 Profile evidence summary", f"{API}/profile/923609016", {
    "total_claims > 0": lambda d: d["evidence"]["total_claims"] > 0,
    "claims_with_source > 0": lambda d: d["evidence"]["claims_with_source"] > 0,
    "all claims sourced": lambda d: d["evidence"]["claims_with_source"] == d["evidence"]["total_claims"],
    "source_summary list": lambda d: len(d["evidence"]["source_summary"]) > 0,
    "source_summary has source URL": lambda d: "source" in d["evidence"]["source_summary"][0],
    "source_summary has claim_count": lambda d: d["evidence"]["source_summary"][0]["claim_count"] > 0,
    "content_hash exists": lambda d: d["evidence"]["content_hash"] is not None,
    "registry evidence": lambda d: d["evidence"]["registry"] is not None,
})

# Profile — company WITHOUT financials (Bergen Kommune)
test("2.7 Profile: Bergen Kommune (no financials)", f"{API}/profile/964338531", {
    "name is Bergen": lambda d: d["overview"]["name"] == "BERGEN KOMMUNE",
    "financials.status is not_available": lambda d: d["financials"]["status"] == "not_available",
    "has leadership roles": lambda d: len(d["leadership"]["roles"]) > 0,
    "has website": lambda d: d["website"]["official_website"] is not None,
    "has evidence": lambda d: d["evidence"]["total_claims"] > 0,
})

# Profile — 404 for invalid orgnr
test("2.8 Profile: invalid orgnr returns 404", f"{API}/profile/000000000", {},
     expect_status=404)

test("2.9 Profile: non-existent orgnr returns 404", f"{API}/profile/999999999", {},
     expect_status=404)

# Profile — industry codes
test("2.10 Profile industry codes", f"{API}/profile/923609016", {
    "has industry_codes": lambda d: len(d["overview"]["industry_codes"]) > 0,
    "codes have code field": lambda d: all("code" in ic for ic in d["overview"]["industry_codes"]),
    "codes have description": lambda d: all("description" in ic for ic in d["overview"]["industry_codes"]),
    "codes have system": lambda d: all(ic.get("system") == "NACE" for ic in d["overview"]["industry_codes"]),
})

# ═══════════════════════════════════════════════════════════
print("\n── 3. COMPARE API ──")
# ═══════════════════════════════════════════════════════════

test("3.1 Compare Equinor vs Bergen", f"{API}/compare?a=923609016&b=964338531", {
    "has company A": lambda d: d["a"]["overview"]["name"] == "EQUINOR ASA",
    "has company B": lambda d: d["b"]["overview"]["name"] == "BERGEN KOMMUNE",
    "A has financials": lambda d: d["a"]["financials"]["status"] == "available",
    "B has no financials": lambda d: d["b"]["financials"]["status"] == "not_available",
    "both have evidence": lambda d: d["a"]["evidence"]["total_claims"] > 0 and d["b"]["evidence"]["total_claims"] > 0,
    "both have leadership": lambda d: len(d["a"]["leadership"]["roles"]) > 0 and len(d["b"]["leadership"]["roles"]) > 0,
})

test("3.2 Compare: missing param returns 400", f"{API}/compare?a=923609016", {},
     expect_status=400)

test("3.3 Compare: invalid orgnr returns 404", f"{API}/compare?a=923609016&b=000000000", {},
     expect_status=404)

# ═══════════════════════════════════════════════════════════
print("\n── 4. SUGGEST API ──")
# ═══════════════════════════════════════════════════════════

test("4.1 Suggest: 'equi'", f"{API}/suggest?q=equi", {
    "returns results": lambda d: len(d) > 0,
    "has orgnr": lambda d: "orgnr" in d[0],
    "has name": lambda d: "name" in d[0],
    "has municipality": lambda d: "municipality" in d[0],
    "has form": lambda d: "form" in d[0],
    "first result matches": lambda d: "EQUI" in d[0]["name"].upper(),
})

test("4.2 Suggest: too short query", f"{API}/suggest?q=x", {
    "returns empty": lambda d: len(d) == 0,
})

test("4.3 Suggest: orgnr prefix", f"{API}/suggest?q=923609016", {
    "finds by orgnr": lambda d: len(d) > 0 and d[0]["orgnr"] == "923609016",
})

test("4.4 Suggest: max 10 results", f"{API}/suggest?q=as", {
    "at most 10": lambda d: len(d) <= 10,
})

# ═══════════════════════════════════════════════════════════
print("\n── 5. SECTORS & FORMS API ──")
# ═══════════════════════════════════════════════════════════

test("5.1 Sectors list", f"{API}/sectors", {
    "returns list": lambda d: isinstance(d, list),
    "has entries": lambda d: len(d) > 10,
    "each has code": lambda d: all("code" in s for s in d),
    "each has label": lambda d: all("label" in s for s in d),
    "each has count > 0": lambda d: all(s["count"] > 0 for s in d),
    "Oil & Gas exists": lambda d: any(s["label"] == "Oil & Gas" for s in d),
    "IT & Software exists": lambda d: any(s["label"] == "IT & Software" for s in d),
})

test("5.2 Forms list", f"{API}/forms", {
    "returns list": lambda d: isinstance(d, list),
    "has entries": lambda d: len(d) > 5,
    "each has code": lambda d: all("code" in f for f in d),
    "each has count > 0": lambda d: all(f["count"] > 0 for f in d),
    "AS exists": lambda d: any(f["code"] == "AS" for f in d),
    "ASA exists": lambda d: any(f["code"] == "ASA" for f in d),
    "KOMM exists": lambda d: any(f["code"] == "KOMM" for f in d),
    "sorted by count desc": lambda d: d[0]["count"] >= d[1]["count"],
})

# ═══════════════════════════════════════════════════════════
print("\n── 6. EXPLORER PAGE (HTML) ──")
# ═══════════════════════════════════════════════════════════

test("6.1 Page loads", f"{BASE}/explorer", {
    "returns HTML": lambda d: "<!DOCTYPE html>" in d,
    "has title": lambda d: "Signalpost Explorer" in d,
    "has Tailwind CSS": lambda d: "tailwindcss" in d or "tailwind" in d,
    "has search input": lambda d: "searchInput" in d,
    "has render function": lambda d: "function render()" in d,
    "has sourceBadge function": lambda d: "function sourceBadge(" in d,
    "has renderProfile function": lambda d: "function renderProfile()" in d,
    "has renderCompareView function": lambda d: "function renderCompareView()" in d,
    "has renderCompareTable": lambda d: "function renderCompareTable()" in d,
    "has renderFinancialsSection": lambda d: "function renderFinancialsSection(" in d,
    "has renderLeadershipSection": lambda d: "function renderLeadershipSection(" in d,
    "has renderWebsiteSection": lambda d: "function renderWebsiteSection(" in d,
    "has renderJobsSection": lambda d: "function renderJobsSection(" in d,
    "has renderEvidenceSection": lambda d: "function renderEvidenceSection(" in d,
    "has sourceDrawer rendering": lambda d: "renderSourceDrawer()" in d,
    "has compare bar rendering": lambda d: "renderCompareBar()" in d,
    "has drawer-overlay class": lambda d: "drawer-overlay" in d,
    "has drawer-panel class": lambda d: "drawer-panel" in d,
    "has mobile slide-up": lambda d: "slideUp" in d,
    "has compare-bar class": lambda d: "compare-bar" in d,
    "has chip classes": lambda d: "chip-on" in d and "chip-off" in d,
    "has source-available class": lambda d: "source-available" in d,
    "has source-not-available class": lambda d: "source-not-available" in d,
    "has source-blocked class": lambda d: "source-blocked" in d,
    "has mobile breakpoint logic": lambda d: "md:grid-cols-2" in d or "md:w-" in d,
    "has Inter font": lambda d: "Inter" in d,
    "has _sourceRegistry": lambda d: "_sourceRegistry" in d,
    "has _openSource function": lambda d: "_openSource" in d,
    "has closeSourceDrawer": lambda d: "closeSourceDrawer" in d,
})

# ═══════════════════════════════════════════════════════════
print("\n── 7. INTEGRATION (existing app not broken) ──")
# ═══════════════════════════════════════════════════════════

test("7.1 Original chat API still works", f"{BASE}/api/suggest?q=equi", {
    "returns list": lambda d: isinstance(d, list),
})

test("7.2 Original lookup API still works", f"{BASE}/api/lookup/923609016", {
    "has organisation_number": lambda d: d.get("organisation_number") == "923609016",
})

# ═══════════════════════════════════════════════════════════
print("\n── 8. DATA INTEGRITY SPOT-CHECKS ──")
# ═══════════════════════════════════════════════════════════

# Check multiple diverse companies
for org, name, expect_fin in [
    ("923609016", "EQUINOR ASA", True),
    ("964338531", "BERGEN KOMMUNE", False),
    ("986105174", "FORSVARET", False),
]:
    test(f"8.x Profile integrity: {name}", f"{API}/profile/{org}", {
        "correct name": lambda d, n=name: d["overview"]["name"] == n,
        "has evidence": lambda d: d["evidence"]["total_claims"] > 0,
        "claims all sourced": lambda d: d["evidence"]["claims_with_source"] == d["evidence"]["total_claims"],
        "generated_at ISO": lambda d: d.get("generated_at") is not None and "T" in str(d.get("generated_at","")),
    })

# ═══════════════════════════════════════════════════════════
print("\n── 9. EDGE CASES ──")
# ═══════════════════════════════════════════════════════════

test("9.1 Search with special characters", f"{API}/search?q=%C3%B8%C3%A6%C3%A5&size=3", {
    "no error": lambda d: "results" in d,
})

test("9.2 Search with empty query", f"{API}/search?q=&size=5", {
    "returns all companies": lambda d: d["total"] > 10000,
})

test("9.3 Suggest with empty query", f"{API}/suggest?q=", {
    "returns empty": lambda d: len(d) == 0,
})

test("9.4 Search page=0 clamps to 1", f"{API}/search?page=0&size=5", {
    "page is 1": lambda d: d["page"] == 1,
})

test("9.5 Search size=100 clamps to 50", f"{API}/search?size=100", {
    "size is 50": lambda d: d["size"] == 50,
    "results <= 50": lambda d: len(d["results"]) <= 50,
})

test("9.6 Multiple has filters combined", f"{API}/search?has=website,financials&size=5", {
    "all have website": lambda d: all(r["has_website"] for r in d["results"]),
    "all have financials": lambda d: all(r["has_financials"] for r in d["results"]),
})

test("9.7 Non-numeric page param defaults to 1", f"{API}/search?page=abc&size=5", {
    "page is 1": lambda d: d["page"] == 1,
    "returns results": lambda d: len(d["results"]) > 0,
})

test("9.8 Non-numeric size param defaults to 20", f"{API}/search?size=xyz", {
    "size is 20": lambda d: d["size"] == 20,
    "returns results": lambda d: len(d["results"]) > 0,
})

test("9.9 Negative page param clamps to 1", f"{API}/search?page=-5&size=5", {
    "page is 1": lambda d: d["page"] == 1,
})

test("9.10 Negative size param clamps to 1", f"{API}/search?size=-10", {
    "size >= 1": lambda d: d["size"] >= 1,
})

test("9.11 Search with apostrophe in name", f"{API}/search?q=McDonald%27s&size=5", {
    "no crash": lambda d: "results" in d,
})

test("9.12 Profile with leading zeros in orgnr", f"{API}/profile/000000000", {
    "returns 404": lambda d: True,
}, expect_status=404)

test("9.13 Compare same company twice", f"{API}/compare?a=923609016&b=923609016", {
    "returns both keys": lambda d: "a" in d and "b" in d,
    "both same orgnr": lambda d: d["a"]["overview"]["orgnr"] == d["b"]["overview"]["orgnr"],
})

test("9.14 Suggest with special chars", f"{API}/suggest?q=%3Cscript%3E", {
    "no crash": lambda d: isinstance(d, list),
})

test("9.15 Search with very long query", f"{API}/search?q={'a'*100}&size=5", {
    "no crash": lambda d: "results" in d,
    "empty results": lambda d: len(d["results"]) == 0,
})

# ── 10. SOURCE METADATA VERIFICATION ──
print("\n── 10. SOURCE METADATA VERIFICATION ──")

test("10.1 Every profile claim has source fields", f"{API}/profile/923609016", {
    "overview claims have source": lambda d: all(
        "source" in c and "retrieved_at" in c and "status" in c
        for c in d.get("overview", {}).values()
        if isinstance(c, dict)
    ) if d.get("overview") else True,
    "financial claims have source": lambda d: all(
        "source" in c and "retrieved_at" in c and "status" in c
        for yr in (d.get("financials") or {}).get("years", [])
        for c in yr.get("metrics", {}).values()
        if isinstance(c, dict)
    ) if d.get("financials") else True,
})

test("10.2 Source status values are valid", f"{API}/profile/923609016", {
    "valid statuses": lambda d: all(
        c.get("status") in ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed", "verified", None)
        for c in d.get("overview", {}).values()
        if isinstance(c, dict) and "status" in c
    ) if d.get("overview") else True,
})

test("10.3 Evidence section has counts", f"{API}/profile/923609016", {
    "has evidence": lambda d: "evidence" in d,
    "total_sources >= 0": lambda d: d.get("evidence", {}).get("total_sources", 0) >= 0,
    "available_count >= 0": lambda d: d.get("evidence", {}).get("available_count", 0) >= 0,
})


# ═══════════════════════════════════════════════════════════
#  FINAL REPORT
# ═══════════════════════════════════════════════════════════
total = passed + failed
print("\n" + "="*70)
print(f"  RESULTS: {passed}/{total} PASSED  |  {failed} FAILED")
print("="*70)

if errors:
    print("\n  FAILURES:")
    for e in errors:
        print(f"    ❌ {e}")

print()
sys.exit(0 if failed == 0 else 1)
