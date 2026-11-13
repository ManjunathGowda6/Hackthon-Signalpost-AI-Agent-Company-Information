"""Clean up dataset to ensure 100% compliance across all 47 audit tests.

1. Filter out any news item with:
   - title < 5 chars
   - generic navigation title (matching _NAV_LABELS)
   - invalid / unparseable date or future date
2. Filter out any job listing with:
   - title < 3 chars
   - generic career title (matching _GENERIC_JOB_TITLES or _NAV_LABELS)
   - invalid date or future date
3. Sync flat and nested schemas
4. Rebuild buyer-first summaries
5. Write to out/signalpost_1000.json and out/signalpost_final.json
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
DATASET_PATH = ROOT_DIR / "out" / "signalpost_1000.json"
FINAL_PATH = ROOT_DIR / "out" / "signalpost_final.json"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from signalpost.collectors.website_verification import _NAV_LABELS
from signalpost.collectors.website_discovery import _GENERIC_JOB_TITLES
from scripts.run_clean_and_summarize import build_buyer_first_summary

def is_valid_date(d_str: str) -> bool:
    if not d_str:
        return False
    try:
        dt = date.fromisoformat(d_str[:10])
        return dt <= date.today()
    except Exception:
        return False

def main():
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    profiles = data if isinstance(data, list) else data.get("companies") or []

    cleaned_news_count = 0
    cleaned_jobs_count = 0

    for p in profiles:
        wp = p.get("website_profiles") or {}
        ha = p.get("hiring_activity") or {}

        # 1. Clean news
        raw_news = wp.get("news_items") or p.get("news") or []
        valid_news = []
        for n in raw_news:
            if not isinstance(n, dict):
                continue
            title = (n.get("title") or "").strip()
            s_url = n.get("source_url") or n.get("url") or ""
            d_str = n.get("date") or n.get("publish_date") or ""

            if len(title) < 5:
                cleaned_news_count += 1
                continue
            if _NAV_LABELS.match(title):
                cleaned_news_count += 1
                continue
            if not s_url or not is_valid_date(d_str):
                cleaned_news_count += 1
                continue

            # Normalize date to YYYY-MM-DD
            iso_d = d_str[:10]
            n["date"] = iso_d
            n["publish_date"] = iso_d
            n["source_url"] = s_url
            valid_news.append(n)

        wp["news_items"] = valid_news
        p["news"] = valid_news
        p["updates"] = valid_news

        # 2. Clean jobs
        raw_jobs = ha.get("job_listings") or ha.get("active_listings") or p.get("jobs") or []
        valid_jobs = []
        for j in raw_jobs:
            if not isinstance(j, dict):
                continue
            title = (j.get("title") or "").strip()
            s_url = j.get("source_url") or j.get("url") or ""
            d_str = j.get("date") or j.get("retrieved_at") or ""

            if len(title) < 3:
                cleaned_jobs_count += 1
                continue
            if _GENERIC_JOB_TITLES.match(title) or _NAV_LABELS.match(title):
                cleaned_jobs_count += 1
                continue
            if not s_url or not is_valid_date(d_str):
                cleaned_jobs_count += 1
                continue

            iso_d = d_str[:10]
            j["date"] = iso_d
            j["source_url"] = s_url
            valid_jobs.append(j)

        ha["job_listings"] = valid_jobs
        p["jobs"] = valid_jobs
        p["job_postings"] = valid_jobs

        p["website_profiles"] = wp
        p["hiring_activity"] = ha

        # 3. Regenerate summary
        new_summary = build_buyer_first_summary(p)
        p["summary"] = new_summary
        if "synthesis" in p and isinstance(p["synthesis"], dict):
            p["synthesis"]["summary"] = new_summary
        elif "synthesis" in p and isinstance(p["synthesis"], str):
            p["synthesis"] = new_summary

    DATASET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    FINAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Purged {cleaned_news_count} invalid news items and {cleaned_jobs_count} generic job titles.")
    print("Dataset saved and synchronized successfully.")

if __name__ == "__main__":
    main()
