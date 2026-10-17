"""
Monthly Database Update Script for Signalpost AI
=================================================
Run this script once a month to refresh all company data using Gemini AI.

Usage:
    python update_database.py           # Update all companies
    python update_database.py --dry-run # Preview what would be updated
    python update_database.py --company "OpenAI"  # Update a single company

Schedule monthly with Windows Task Scheduler:
    schtasks /create /tn "Signalpost Monthly Update" /tr "path\\to\\python update_database.py" /sc monthly /d 1 /st 02:00
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
if "scratch" in str(BASE_DIR):
    BASE_DIR = Path(r"D:\Signalpost-AI-Agent-Company-Information")
DATA_FILE = BASE_DIR / "out" / "global_companies.json"
BACKUP_DIR = BASE_DIR / "out" / "backups"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


def load_companies():
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found!")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def backup_database():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"global_companies_{timestamp}.json"
    with open(DATA_FILE, "r", encoding="utf-8") as src:
        with open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())
    print(f"  Backup created: {backup_path}")


def gemini_update_company(company):
    if not GEMINI_KEY:
        return None
    name = company.get("name", "")
    prompt = f"""You are a data analyst. Provide the LATEST factual data for {name}.
Return ONLY a JSON object (no markdown) with these fields:
{{"revenue":"latest annual revenue (e.g. '$123.4B')","profit":"latest net profit/loss","market_cap":"current market cap or 'Private'","employees":number,"ceo":"current CEO","valuation":"private valuation if private, else null","stock":"ticker or 'Private'","pe_ratio":"P/E ratio or 'N/A'","key_metrics":"semicolon-separated metrics","desc":"1-line description"}}
Return ONLY valid JSON."""
    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
        })
        req = urllib.request.Request(api_url, data=payload.encode("utf-8"),
                                    headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            candidates = result.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return json.loads(text.strip())
    except Exception as e:
        print(f"    ERROR: {type(e).__name__}: {str(e)[:100]}")
    return None


def update_all(dry_run=False, single_company=None):
    print("=" * 60)
    print("  SIGNALPOST AI — MONTHLY DATABASE UPDATE")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    if not GEMINI_KEY:
        print("\nERROR: GEMINI_API_KEY not set!")
        sys.exit(1)
    companies = load_companies()
    if single_company:
        companies = [c for c in companies if single_company.lower() in c.get("name", "").lower()]
        if not companies:
            print(f"\nERROR: Company '{single_company}' not found!")
            sys.exit(1)
    print(f"\nCompanies to update: {len(companies)}")
    if not dry_run:
        backup_database()
    updated = 0
    failed = 0
    all_companies = load_companies()  # full list for saving
    for i, company in enumerate(companies):
        name = company.get("name", "Unknown")
        print(f"\n[{i+1}/{len(companies)}] {name}...")
        if dry_run:
            print("  (dry run - skipping)")
            continue
        new_data = gemini_update_company(company)
        if new_data:
            for key in ["revenue","profit","market_cap","employees","ceo","valuation","stock","pe_ratio","key_metrics","desc"]:
                val = new_data.get(key)
                if val is not None and val != "" and val != "N/A":
                    company[key] = val
                    # Also update in all_companies
                    for ac in all_companies:
                        if ac.get("name") == name:
                            ac[key] = val
            company["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            updated += 1
            print(f"  Updated: revenue={new_data.get('revenue')}, employees={new_data.get('employees')}")
        else:
            failed += 1
            print(f"  Failed to update")
        if i < len(companies) - 1:
            time.sleep(2)
    if not dry_run and updated > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(all_companies, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {DATA_FILE}")
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {updated} updated, {failed} failed, {len(companies)} total")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Update Signalpost AI database")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--company", type=str)
    args = parser.parse_args()
    update_all(dry_run=args.dry_run, single_company=args.company)
