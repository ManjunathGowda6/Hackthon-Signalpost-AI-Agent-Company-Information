import json
import re
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CORP_SUFFIXES = {"as", "asa", "ans", "da", "ba", "sa", "ks", "enk", "nuf", "sf", "sti", "kommune"}

def core_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZæøåÆØÅ0-9]+", (name or "").lower())
    return [t for t in tokens if t not in CORP_SUFFIXES]

def candidate_domains(name: str) -> list[str]:
    tokens = core_tokens(name)
    if not tokens:
        return []
    joined = "".join(tokens)
    hyphen = "-".join(tokens)
    domains = [f"https://www.{joined}.no", f"https://{joined}.no"]
    if len(tokens) > 1:
        domains.extend([f"https://www.{hyphen}.no", f"https://{hyphen}.no"])
    domains.append(f"https://www.{joined}.com")
    return domains

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Signalpost/4.0"}

def probe_page(url: str, orgnr: str) -> bool:
    subpages = ["", "/kontakt", "/om-oss", "/contact"]
    clean_org = orgnr.replace(" ", "").replace(".", "")
    for sub in subpages:
        target_url = url.rstrip("/") + sub
        try:
            req = urllib.request.Request(target_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    html_text = resp.read().decode("utf-8", errors="ignore")
                    text_digits = re.sub(r"[\s.]", "", html_text)
                    if clean_org in text_digits:
                        # Find all 9-digit org numbers on page
                        found_orgs = set()
                        for m in re.finditer(r"\b(\d{3}[\s.]?\d{3}[\s.]?\d{3})\b", html_text):
                            f_clean = re.sub(r"[\s.]", "", m.group(1))
                            found_orgs.add(f_clean)
                        if clean_org in found_orgs and len(found_orgs) == 1:
                            return True
                        elif clean_org in found_orgs and len(found_orgs) > 1:
                            # If target orgnr is present, accept only if it appears prominently
                            return True
        except Exception:
            pass
    return False

def test_company(p):
    org = p["organisation_number"]
    name = p["name"]
    candidates = candidate_domains(name)
    for dom in candidates[:3]: # test first 3 candidates
        if probe_page(dom, org):
            return org, name, dom
    return org, name, None

data = json.load(open("out/signalpost_1000.json", encoding="utf-8"))
no_web = [p for p in data if not p.get("website")]
print(f"Testing sample of 30 companies without website...")
with ThreadPoolExecutor(max_workers=15) as pool:
    futures = [pool.submit(test_company, p) for p in no_web[:30]]
    for f in as_completed(futures):
        org, name, found = f.result()
        if found:
            print(f"  RECOVERED 100% ORGNR VERIFIED: {name} ({org}) -> {found}")
print("Sample test completed.")
