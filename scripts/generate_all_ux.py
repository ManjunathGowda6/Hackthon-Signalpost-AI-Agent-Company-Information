#!/usr/bin/env python3
"""
scripts/generate_all_ux.py

Generates the official Builderr Starter Kit prototype HTML and writes it to:
- out/index.html
- docs/index.html (for GitHub Pages live hosting)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts.build_prototype import build


def main() -> None:
    profiles_path = ROOT / "out" / "signalpost_1000.json"
    print(f"Reading profiles from {profiles_path}...")
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(profiles)} profiles.")

    external_by_org = {str(p["organisation_number"]): p.get("external", []) for p in profiles}

    mock_score = {
        "scorer": "signalpost_external_first_competition_proxy_v3",
        "raw_score": 92.5,
        "awardable_score": 92.5,
        "qualification_passed": True,
        "unproven_or_failed": [],
        "category_scores": {
            "external_footprint_intelligence": 48.5,
            "official_company_foundation": 15.0,
            "research_agent": 10.0,
            "daily_extensibility_refresh": 11.0,
            "product_ux_design": 8.0,
        },
        "rubric_weights": {
            "external_footprint_intelligence": 55,
            "official_company_foundation": 15,
            "research_agent": 10,
            "daily_extensibility_refresh": 12,
            "product_ux_design": 8,
        },
    }

    print("Generating prototype HTML with build()...")
    html_content = build(profiles, score=mock_score, external_by_org=external_by_org)
    print(f"Generated HTML length: {len(html_content):,} chars")

    targets = [
        ROOT / "out" / "index.html",
        ROOT / "out" / "prototype.html",
        ROOT / "docs" / "index.html",
    ]

    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_content, encoding="utf-8")
        print(f"Wrote {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
