import asyncio
import json
import time
from pathlib import Path

from signalpost.orchestrator import Orchestrator

test_input = Path("out/temp_test_orgs.json")
test_output = Path("out/temp_test_live.json")

test_input.write_text(json.dumps(["923609016", "914757657"]))

print("Starting live Orchestrator run on 2 companies (EQUINOR ASA and ARCON AS)...")
t0 = time.time()
orch = Orchestrator(
    input_file=str(test_input),
    output_file=str(test_output),
    max_workers=2,
    max_requests=100,
)
asyncio.run(orch.run())
print(f"Orchestrator completed in {time.time() - t0:.2f}s!")

results = json.loads(test_output.read_text(encoding="utf-8"))
for r in results:
    print(f"Company: {r.get('name')} ({r.get('organisation_number')})")
    print(f"  Website: {r.get('website')}")
    print(f"  Socials: {r.get('social_links')}")
    print(f"  Summary: {r.get('summary')[:100]}...")
    print(f"  Evidence modules: {list(r.get('evidence', {}).keys())}")
