import json
import re
import socket
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Enforce strict global socket timeout for DNS and TCP connections
socket.setdefaulttimeout(2.0)

CORP_SUFFIXES = {"as", "asa", "ans", "da", "ba", "sa", "ks", "enk", "nuf", "sf", "sti", "kommune"}

def core_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZæøåÆØÅ0-9]+", (name or "").lower())
    return [t for t in tokens if t not in CORP_SUFFIXES]

def candidate_domains(name: str) -> list[str]:
    tokens = core_tokens(name)
    if not tokens or len(tokens) > 3:
        return []
    joined = "".join(tokens)
    hyphen = "-".join(tokens)
    domains = [f"https://www.{joined}.no", f"https://{joined}.no"]
    if len(tokens) > 1:
        domains.append(f"https://www.{hyphen}.no")
    return domains

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Signalpost/4.0"}

def probe_page(url: str, orgnr: str) -> bool:
    subpages = ["", "/kontakt", "/om-oss"]
    clean_org = orgnr.replace(" ", "").replace(".", "")
    for sub in subpages:
        target_url = url.rstrip("/") + sub
        try:
            req = urllib.request.Request(target_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    html_text = resp.read().decode("utf-8", errors="ignore")
                    text_digits = re.sub(r"[\s.]", "", html_text)
                    if clean_org in text_digits:
                        # Extract all 9-digit org numbers
                        found_orgs = set(re.findall(r"\b\d{9}\b", text_digits))
                        if clean_org in found_orgs:
                            return True
        except Exception:
            pass
    return False

def test_company(p):
    org = p["organisation_number"]
    name = p["name"]
    for dom in candidate_domains(name):
        if probe_page(dom, org):
            return org, name, dom
    return org, name, None

data = json.load(open("out/signalpost_1000.json", encoding="utf-8"))
no_web = [p for p in data if not p.get("website")]
print(f"Testing sample of 25 companies without website...")
with ThreadPoolExecutor(max_workers=15) as pool:
    futures = [pool.submit(test_company, p) for p in no_web[:25]]
    for f in as_completed(futures):
        org, name, found = f.result()
        if found:
            print(f"  RECOVERED 100% ORGNR VERIFIED: {name} ({org}) -> {found}")
print("Sample test completed.")
