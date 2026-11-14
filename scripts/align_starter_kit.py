#!/usr/bin/env python3
"""
scripts/align_starter_kit.py

Refreshes all datasets and envelopes using the unified signalpost.align module.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
STARTER_KIT_SRC = ROOT / "src"
if str(STARTER_KIT_SRC) not in sys.path:
    sys.path.insert(0, str(STARTER_KIT_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signalpost.align import align_profile
from norway_company_agent.batch import terminal_envelope, validate_envelopes


def main() -> None:
    in_path = ROOT / "out" / "signalpost_1000.json"
    print(f"Loading {in_path}...")
    data = json.loads(in_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} profiles.")

    aligned = [align_profile(row) for row in data]

    # Save to out/signalpost_1000.json
    out_1000 = ROOT / "out" / "signalpost_1000.json"
    out_1000.write_text(json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved aligned JSON to {out_1000}")

    # Save to out/signalpost_final.json
    out_final = ROOT / "out" / "signalpost_final.json"
    out_final.write_text(json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved aligned JSON to {out_final}")

    # Save to out/profiles.jsonl
    out_profiles_jsonl = ROOT / "out" / "profiles.jsonl"
    with out_profiles_jsonl.open("w", encoding="utf-8") as f:
        for item in aligned:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Saved JSONL profiles to {out_profiles_jsonl}")

    # Generate envelopes.jsonl
    started_at = "2026-11-06T00:00:00Z"
    completed_at = "2026-11-06T00:15:00Z"
    modules = ["registry", "accounting_obligation", "registry_live", "financials", "roles", "locations", "website"]
    envelopes = [
        terminal_envelope(profile, run_id="v4-starter-aligned", modules=modules, started_at=started_at, completed_at=completed_at)
        for profile in aligned
    ]
    val = validate_envelopes(envelopes, len(aligned))
    print(f"Envelopes validation passed: {val['passed']} (checks: {val['checks']})")

    out_envelopes = ROOT / "out" / "envelopes.jsonl"
    with out_envelopes.open("w", encoding="utf-8") as f:
        for env in envelopes:
            f.write(json.dumps(env, ensure_ascii=False) + "\n")
    print(f"Saved terminal envelopes to {out_envelopes}")


if __name__ == "__main__":
    main()
