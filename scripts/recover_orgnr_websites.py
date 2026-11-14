#!/usr/bin/env python3
"""
scripts/recover_orgnr_websites.py

Runs a fast, concurrent 100% precision orgnr-only recovery pass for companies
currently without a verified website.
Rule: Candidate website is accepted IF AND ONLY IF the exact 9-digit Norwegian orgnr
is found on the homepage, /kontakt, or /om-oss, with zero conflicting orgnr.
"""

import json
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from signalpost.align import align_profile

socket.setdefaulttimeout(2.5)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Signalpost/4.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CORP_SUFFIXES = {"as", "asa", "ans", "da", "ba", "sa", "ks", "enk", "nuf", "sf", "sti", "kommune", "gruppen", "norge"}

def get_candidates(name: str) -> list[str]:
    tokens = [t.lower() for t in re.findall(r"[a-zA-ZæøåÆØÅ0-9]+", name) if t.lower() not in CORP_SUFFIXES]
    if not tokens or len(tokens) > 3:
        return []
    joined = "".join(tokens)
    hyphen = "-".join(tokens)
    res = [f"https://www.{joined}.no", f"https://{joined}.no"]
    if len(tokens) > 1:
        res.append(f"https://www.{hyphen}.no")
    return res

def check_orgnr_on_site(base_url: str, target_orgnr: str) -> tuple[bool, str, str]:
    subpages = ["", "/kontakt", "/om-oss", "/contact"]
    clean_target = target_orgnr.replace(" ", "").replace(".", "")
    session = requests.Session()
    session.headers.update(HEADERS)

    for sub in subpages:
        url = base_url.rstrip("/") + sub
        try:
            resp = session.get(url, timeout=2.5, allow_redirects=True, verify=False)
            if resp.status_code == 200:
                html = resp.text
                text_clean = re.sub(r"[\s.]", "", html)
                if clean_target in text_clean:
                    # Extract all 9-digit numbers
                    raw_9 = re.findall(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}\b", html)
                    found_orgs = {re.sub(r"[\s.]", "", x) for x in raw_9}
                    if clean_target in found_orgs:
                        conflicts = [o for o in found_orgs if o != clean_target and o.startswith(("8", "9"))]
                        if not conflicts:
                            return True, resp.url, html
        except Exception:
            continue
    return False, "", ""

def extract_metadata(url: str, html: str, orgnr: str, company_name: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    socials = []
    seen_soc = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        for plat in ["facebook.com", "linkedin.com/company", "instagram.com"]:
            if plat in lower and href not in seen_soc:
                seen_soc.add(href)
                p_name = "facebook" if "facebook" in plat else "linkedin" if "linkedin" in plat else "instagram"
                socials.append({"platform": p_name, "url": href})

    return {
        "website": url,
        "social_links": socials,
    }

def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    data_file = ROOT / "out" / "signalpost_1000.json"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    no_web = [p for p in data if not p.get("website")]
    print(f"Total companies without verified website: {len(no_web)}")

    recovered = {}

    def worker(p):
        org = p["organisation_number"]
        name = p["name"]
        candidates = get_candidates(name)
        for cand in candidates:
            ok, final_url, html = check_orgnr_on_site(cand, org)
            if ok:
                meta = extract_metadata(final_url, html, org, name)
                return org, meta
        return org, None

    print("Running concurrent 100%-orgnr recovery pass...")
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(worker, p): p for p in no_web}
        for f in as_completed(futures):
            org, meta = f.result()
            if meta:
                recovered[org] = meta
                p = futures[f]
                print(f"  RECOVERED: {p['name']} ({org}) -> {meta['website']}")

    print(f"Total newly recovered websites: {len(recovered)}")

    if recovered:
        for p in data:
            org = p["organisation_number"]
            if org in recovered:
                p["website"] = recovered[org]["website"]
                p["verification_method"] = "orgnr_verified"
                if recovered[org]["social_links"]:
                    p["social_links"] = recovered[org]["social_links"]

        aligned = [align_profile(p) for p in data]
        data_file.write_text(json.dumps(aligned, indent=2, ensure_ascii=False), encoding="utf-8")
        (ROOT / "out" / "signalpost_final.json").write_text(json.dumps(aligned, indent=2, ensure_ascii=False), encoding="utf-8")
        with (ROOT / "out" / "profiles.jsonl").open("w", encoding="utf-8") as f:
            for item in aligned:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print("Updated out/signalpost_1000.json and out/profiles.jsonl with newly recovered websites!")

if __name__ == "__main__":
    main()
