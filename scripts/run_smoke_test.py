"""100-company smoke test."""
import asyncio, sys
from pathlib import Path
from signalpost.orchestrator import Orchestrator
def main():
    out = sys.argv[1] if len(sys.argv)>1 else "out/smoke_test_report.json"
    fix = Path("tests/fixtures/sample_companies.json")
    if not fix.exists(): print("Create tests/fixtures/sample_companies.json first"); sys.exit(1)
    asyncio.run(Orchestrator(str(fix), out).run())
    print(f"Done: {out}")
if __name__=="__main__": main()
