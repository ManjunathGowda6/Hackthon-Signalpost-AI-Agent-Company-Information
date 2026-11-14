import json
import subprocess
import sys
from pathlib import Path

STARTER_KIT = Path(r"C:\Users\nisar\Downloads\signalpost-starter-kit\signalpost-starter-kit")
sys.path.insert(0, str(STARTER_KIT / "src"))
from norway_company_agent.research import screen_profiles

# Load our aligned rows
rows = [json.loads(line) for line in Path("out/profiles.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

# Build a benchmark suite matching the 1,107 dataset
q1 = "companies in Oslo with more than 5 employees and revenue over 1 million top 10 by revenue"
r1 = screen_profiles(rows, q1)
expected_q1 = [item["organisation_number"] for item in r1["results"]]

q2 = "top 5 by revenue"
r2 = screen_profiles(rows, q2)
expected_q2 = [item["organisation_number"] for item in r2["results"]]

suite = {
    "corpus": "signalpost 1107 production benchmark suite",
    "single_company": {
        "organisation_number": "923609016",
        "question": "Who leads this company and what financial facts and locations are available?",
        "minimum_facts": 6,
    },
    "screens": [
        {
            "query": q1,
            "expected_organisation_numbers": expected_q1,
            "expected_filter_fields": ["municipality", "employees", "revenue"],
        },
        {
            "query": q2,
            "expected_organisation_numbers": expected_q2,
            "expected_filter_fields": [],
        },
    ],
    "unsupported": {
        "query": "companies in Oslo with positive Glassdoor sentiment",
        "must_abstain": True,
    },
}

suite_path = Path("out/research_test_suite.json")
suite_path.write_text(json.dumps(suite, indent=2), encoding="utf-8")

# Now run evaluate_research_agent.py
cmd = [
    sys.executable,
    str(STARTER_KIT / "scripts" / "evaluate_research_agent.py"),
    "--input", "out/profiles.jsonl",
    "--suite", str(suite_path),
    "--output", "out/research-report.json",
    "--workspace", "out/workspace.json",
]
print("Running evaluate_research_agent.py...")
res = subprocess.run(cmd, capture_output=True, text=True)
print("Exit code:", res.returncode)
print("STDOUT:\n", res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)
