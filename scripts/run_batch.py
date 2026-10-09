"""Batch runner for 1000+ companies."""
import asyncio
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from signalpost.orchestrator import Orchestrator
from signalpost.config import OUTPUT_DIR


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_companies.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else str(OUTPUT_DIR / "batch_results.json")

    print(f"\n  Signalpost Batch Runner")
    print(f"  Input:  {input_file}")
    print(f"  Output: {output_file}\n")

    orchestrator = Orchestrator(
        input_file=input_file,
        output_file=output_file,
        max_workers=10,
        max_requests=2000,
        max_cost_usd=10.0,
    )

    start = time.time()
    asyncio.run(orchestrator.run())
    elapsed = time.time() - start

    results = json.loads(Path(output_file).read_text(encoding="utf-8"))
    available = sum(1 for r in results if r.get("status") == "available")

    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  {available}/{len(results)} profiles available")
    print(f"  Requests: {orchestrator.budget.used}")
    print(f"  Cost: ${orchestrator.cost_tracker.total_cost:.4f}")


if __name__ == "__main__":
    main()
