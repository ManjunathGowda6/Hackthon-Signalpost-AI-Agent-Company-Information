"""Batch processing orchestrator."""
import asyncio, json, time
from pathlib import Path
from typing import Optional
import structlog
from signalpost.config import MAX_CONCURRENT_WORKERS, MAX_REQUESTS, MAX_COST_USD, MAX_TIME_SECONDS
from signalpost.utils.request_budget import RequestBudget
from signalpost.utils.cost_tracker import CostTracker
from signalpost.models.envelope import CompanyEnvelope

logger = structlog.get_logger()

class Orchestrator:
    def __init__(self, input_file, output_file, max_workers=MAX_CONCURRENT_WORKERS,
                 max_requests=MAX_REQUESTS, max_cost_usd=MAX_COST_USD):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.max_workers = max_workers
        self.budget = RequestBudget(max_requests=max_requests)
        self.cost_tracker = CostTracker(max_cost_usd=max_cost_usd)
        self.start_time = None

    async def run(self):
        self.start_time = time.time()
        org_numbers = self._load_input()
        logger.info("batch_loaded", count=len(org_numbers))
        sem = asyncio.Semaphore(self.max_workers)
        tasks = [self._process(nr, sem) for nr in org_numbers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(CompanyEnvelope.create_failed(org_numbers[i], str(r)).model_dump())
            else:
                final.append(r)
        self._write_output(final)
        elapsed = time.time() - self.start_time
        logger.info("done", total=len(org_numbers), elapsed=round(elapsed,1),
                     requests=self.budget.used, cost=round(self.cost_tracker.total_cost,4))

    async def _process(self, org_number, sem):
        async with sem:
            if self.start_time and (time.time()-self.start_time) >= MAX_TIME_SECONDS:
                return CompanyEnvelope.create_failed(org_number, "Time exceeded").model_dump()
            try:
                from signalpost.identity.brreg_client import BrregClient
                brreg = BrregClient(budget=self.budget)
                entity = await brreg.get_entity(org_number)
                if not entity:
                    return CompanyEnvelope.create_not_available(org_number).model_dump()
                return CompanyEnvelope.from_registry_data(org_number, entity).model_dump()
            except Exception as e:
                return CompanyEnvelope.create_failed(org_number, str(e)).model_dump()

    def _load_input(self):
        numbers = []
        with open(self.input_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        nr = data.get("organisasjonsnummer") or data.get("org_number") or data.get("orgnr")
                        if nr: numbers.append(str(nr))
                    else: numbers.append(str(data))
                except json.JSONDecodeError:
                    numbers.append(line)
        return numbers

    def _write_output(self, results):
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
