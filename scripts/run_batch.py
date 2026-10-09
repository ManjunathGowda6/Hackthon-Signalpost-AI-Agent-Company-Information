"""Batch runner."""
import asyncio, sys
from signalpost.orchestrator import Orchestrator
def main():
    if len(sys.argv)<3: print("Usage: python scripts/run_batch.py <input> <output>"); sys.exit(1)
    asyncio.run(Orchestrator(sys.argv[1], sys.argv[2]).run())
if __name__=="__main__": main()
