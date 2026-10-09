"""Batch processing orchestrator — budget-optimized company research pipeline.

Budget Strategy (2,000 requests for 1,000+ companies):
  Phase 1: Entity fetch for ALL companies (1 req each)        ~1,000 requests
  Phase 2: Financials for ALL found companies (1 req each)    ~1,000 requests
  Phase 3: Roles with remaining budget                        remaining
  Total: stays within 2,000 request cap
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from signalpost.config import (
    MAX_CONCURRENT_WORKERS, MAX_REQUESTS, MAX_COST_USD, MAX_TIME_SECONDS,
)
from signalpost.utils.request_budget import RequestBudget
from signalpost.utils.cost_tracker import CostTracker
from signalpost.models.envelope import (
    CompanyEnvelope, ClaimValue, LegalIdentity, AnnualAccounts,
    LeadershipWorkplaces, WebsiteProfiles, HiringActivity,
    EvidenceSummary, RefreshMetadata, Synthesis, utc_now,
)
from signalpost.identity.brreg_client import BrregClient
from signalpost.identity.roles_client import RolesClient
from signalpost.identity.subunits_client import SubunitsClient
from signalpost.extractors.financial_extractor import FinancialExtractor
from signalpost.synthesis.claude_client import ClaudeClient
from signalpost.synthesis.summarizer import Summarizer

logger = structlog.get_logger()


class Orchestrator:
    """Runs the full company research pipeline for a batch of org numbers.

    Uses a phased approach to maximize coverage within the request budget:
    Phase 1: Fetch entity data for all companies (1 request each)
    Phase 2: Fetch financials for all found companies (1 request each)
    Phase 3: Fetch roles with any remaining budget
    """

    def __init__(
        self,
        input_file: str,
        output_file: str,
        max_workers: int = MAX_CONCURRENT_WORKERS,
        max_requests: int = MAX_REQUESTS,
        max_cost_usd: float = MAX_COST_USD,
    ):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.max_workers = max_workers
        self.budget = RequestBudget(max_requests=max_requests)
        self.cost_tracker = CostTracker(max_cost_usd=max_cost_usd)
        self.start_time: Optional[float] = None

        # Shared clients
        self.brreg = BrregClient(budget=self.budget)
        self.roles_client = RolesClient(self.brreg)
        self.claude = ClaudeClient(cost_tracker=self.cost_tracker)
        self.summarizer = Summarizer(self.claude)

    async def run(self):
        """Execute the phased batch pipeline."""
        self.start_time = time.time()
        org_numbers = self._load_input()
        total = len(org_numbers)
        logger.info("batch_start", total=total, workers=self.max_workers,
                     budget=self.budget.max_requests)

        # ── Phase 1: Fetch all entities ──
        logger.info("phase_1_start", desc="Fetching entity data")
        entities: dict[str, Any] = {}  # org_number -> entity_data or None
        sem = asyncio.Semaphore(self.max_workers)

        async def fetch_entity(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, None
                resp = await self.brreg.get_entity(org_nr)
                return org_nr, resp.data if resp.ok else None

        tasks = [fetch_entity(nr) for nr in org_numbers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            org_nr, data = r
            entities[org_nr] = data

        found_count = sum(1 for v in entities.values() if v is not None)
        logger.info("phase_1_done", found=found_count, not_found=total - found_count,
                     requests_used=self.budget.used)

        # ── Phase 2: Fetch financials for found entities ──
        logger.info("phase_2_start", desc="Fetching financial data",
                     budget_remaining=self.budget.remaining)
        financials: dict[str, Any] = {}  # org_number -> accounts data or None

        found_orgs = [nr for nr in org_numbers if entities.get(nr) is not None]

        async def fetch_financials(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, None
                resp = await self.brreg.get_financials(org_nr)
                return org_nr, resp.data if resp.ok else None

        tasks = [fetch_financials(nr) for nr in found_orgs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            org_nr, data = r
            financials[org_nr] = data

        fin_count = sum(1 for v in financials.values() if v is not None)
        logger.info("phase_2_done", with_financials=fin_count,
                     requests_used=self.budget.used)

        # ── Phase 3: Fetch roles with remaining budget ──
        remaining = self.budget.remaining
        logger.info("phase_3_start", desc="Fetching leadership roles",
                     budget_remaining=remaining)
        roles_data: dict[str, list] = {}

        # Prioritize companies that have entity data
        roles_orgs = found_orgs[:remaining]  # Only fetch as many as budget allows

        async def fetch_roles(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, []
                try:
                    roles = await self.roles_client.get_leadership(org_nr)
                    return org_nr, roles
                except Exception:
                    return org_nr, []

        if roles_orgs:
            tasks = [fetch_roles(nr) for nr in roles_orgs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    continue
                org_nr, roles = r
                roles_data[org_nr] = roles

        roles_count = sum(1 for v in roles_data.values() if v)
        logger.info("phase_3_done", with_roles=roles_count,
                     requests_used=self.budget.used)

        # ── Phase 4: Assemble envelopes ──
        logger.info("phase_4_start", desc="Assembling company profiles")
        envelopes: list[dict[str, Any]] = []

        for idx, org_nr in enumerate(org_numbers):
            entity = entities.get(org_nr)
            if entity is None:
                # Entity not found or budget exhausted
                if self.budget.used >= self.budget.max_requests and org_nr not in entities:
                    env = CompanyEnvelope.create_failed(org_nr, "Request budget exhausted")
                else:
                    env = CompanyEnvelope.create_not_available(org_nr)
                envelopes.append(env.model_dump(mode="json"))
                continue

            try:
                envelope = await self._assemble_envelope(
                    org_nr, entity,
                    financials.get(org_nr),
                    roles_data.get(org_nr, []),
                    idx, total,
                )
                envelopes.append(envelope)
            except Exception as e:
                logger.error("assembly_error", org=org_nr, error=str(e))
                env = CompanyEnvelope.create_failed(org_nr, str(e))
                envelopes.append(env.model_dump(mode="json"))

        self._write_output(envelopes)
        await self.brreg.close()

        elapsed = time.time() - self.start_time
        available = sum(1 for e in envelopes if e.get("status") == "available")
        logger.info(
            "batch_complete",
            total=total,
            available=available,
            elapsed_sec=round(elapsed, 1),
            requests_used=self.budget.used,
            cost_usd=round(self.cost_tracker.total_cost, 4),
        )

    async def _assemble_envelope(
        self,
        org_number: str,
        entity: dict,
        fin_data: Any,
        roles: list[dict],
        idx: int,
        total: int,
    ) -> dict[str, Any]:
        """Assemble a complete envelope from collected data."""
        now = utc_now()

        # Legal Identity
        legal_identity = self._build_legal_identity(entity, org_number, now)

        # Annual Accounts
        legal_form = entity.get("organisasjonsform", {}).get("kode")
        employees = entity.get("antallAnsatte")

        if fin_data is not None:
            annual_accounts = FinancialExtractor.extract_accounts(
                fin_data, org_number,
                legal_form=legal_form,
                registry_employees=employees,
            )
        else:
            obligation = FinancialExtractor.assess_obligation(legal_form, False)
            annual_accounts = AnnualAccounts(
                status="not_available",
                accounting_obligation=obligation["classification"],
                employees=ClaimValue(
                    value=employees,
                    source=f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}",
                    retrieved_at=now,
                ) if employees is not None else None,
            )

        # Leadership & Workplaces
        leadership_workplaces = LeadershipWorkplaces(
            status="available" if roles else "not_available",
            roles=roles,
            workplaces=[],
        )

        # Website (from registry data only, no crawling to save budget)
        website_url = entity.get("hjemmeside")
        website_profiles = WebsiteProfiles(
            status="available" if website_url else "not_available",
            official_website={"url": website_url, "source": "brreg_registry"} if website_url else None,
        )

        # Evidence
        evidence = self._build_evidence(
            legal_identity, annual_accounts, leadership_workplaces,
            website_profiles, org_number,
        )

        # Synthesis (rule-based to save LLM budget)
        envelope_data = {
            "legal_identity": legal_identity.model_dump(mode="json"),
            "annual_accounts": annual_accounts.model_dump(mode="json"),
            "leadership_workplaces": leadership_workplaces.model_dump(mode="json"),
            "website_profiles": website_profiles.model_dump(mode="json"),
            "hiring_activity": {"status": "not_applicable"},
        }
        synthesis_data = await self.summarizer.summarize(envelope_data)
        synthesis = Synthesis(**synthesis_data)

        # Assemble
        envelope = CompanyEnvelope(
            organisation_number=org_number,
            name=entity.get("navn"),
            legal_form=entity.get("organisasjonsform", {}).get("kode"),
            municipality=entity.get("forretningsadresse", {}).get("kommune"),
            website=website_url,
            status="available",
            legal_identity=legal_identity,
            annual_accounts=annual_accounts,
            leadership_workplaces=leadership_workplaces,
            website_profiles=website_profiles,
            hiring_activity=HiringActivity(status="not_applicable"),
            evidence=evidence,
            refresh_metadata=RefreshMetadata(
                is_initial_run=True,
                last_refreshed=now,
            ),
            synthesis=synthesis,
        )

        if (idx + 1) % 100 == 0 or idx == total - 1:
            logger.info("progress", completed=idx + 1, total=total)

        return envelope.model_dump(mode="json")

    # ── Builders ──

    def _build_legal_identity(self, entity: dict, org_number: str, now: str) -> LegalIdentity:
        src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"

        addr = entity.get("forretningsadresse", {})
        addr_parts = addr.get("adresse", [])
        addr_str = ", ".join(addr_parts) if addr_parts else None
        full_addr = None
        if addr_str:
            full_addr = f"{addr_str}, {addr.get('postnummer', '')} {addr.get('poststed', '')}"

        codes = []
        for nace_key in ["naeringskode1", "naeringskode2", "naeringskode3"]:
            nace = entity.get(nace_key)
            if nace:
                codes.append({
                    "code": nace.get("kode"),
                    "description": nace.get("beskrivelse"),
                    "system": "NACE",
                    "source": src,
                })

        return LegalIdentity(
            status="available",
            legal_name=ClaimValue(value=entity.get("navn"), source=src, retrieved_at=now),
            legal_form=ClaimValue(
                value=entity.get("organisasjonsform", {}).get("beskrivelse"),
                source=src, retrieved_at=now,
            ),
            registered_address=ClaimValue(value=full_addr, source=src, retrieved_at=now) if full_addr else None,
            industry_codes=codes,
            registration_date=ClaimValue(
                value=entity.get("registreringsdatoEnhetsregisteret"),
                source=src, retrieved_at=now,
            ) if entity.get("registreringsdatoEnhetsregisteret") else None,
            registration_status=ClaimValue(
                value="Active" if not entity.get("slettedato") else "Deleted",
                source=src, retrieved_at=now,
            ),
            activity_description=ClaimValue(
                value=entity.get("naeringskode1", {}).get("beskrivelse"),
                source=src, retrieved_at=now,
            ) if entity.get("naeringskode1") else None,
            official_website=ClaimValue(
                value=entity.get("hjemmeside"),
                source=src, retrieved_at=now,
            ) if entity.get("hjemmeside") else None,
            is_bankrupt=entity.get("konkurs", False),
            is_in_liquidation=entity.get("underAvvikling", False),
        )

    def _build_evidence(
        self,
        legal_identity: LegalIdentity,
        annual_accounts: AnnualAccounts,
        leadership: LeadershipWorkplaces,
        website: WebsiteProfiles,
        org_number: str,
    ) -> EvidenceSummary:
        total_claims = 0
        claims_with_source = 0
        sources: dict[str, int] = {}

        for field_name in ["legal_name", "legal_form", "registered_address",
                           "registration_date", "registration_status",
                           "activity_description", "official_website"]:
            claim = getattr(legal_identity, field_name, None)
            if claim and claim.value is not None:
                total_claims += 1
                if claim.source:
                    claims_with_source += 1
                    sources[claim.source] = sources.get(claim.source, 0) + 1

        total_claims += len(legal_identity.industry_codes)
        claims_with_source += len(legal_identity.industry_codes)

        for field_name in ["revenue", "operating_profit", "profit_before_tax",
                           "net_income", "total_assets", "total_equity",
                           "total_debt", "employees"]:
            claim = getattr(annual_accounts, field_name, None)
            if claim and claim.value is not None:
                total_claims += 1
                if claim.source:
                    claims_with_source += 1
                    sources[claim.source] = sources.get(claim.source, 0) + 1

        total_claims += len(leadership.roles)
        claims_with_source += sum(1 for r in leadership.roles if r.get("source"))
        for r in leadership.roles:
            s = r.get("source", "")
            if s:
                sources[s] = sources.get(s, 0) + 1

        source_summary = [
            {"source": s, "claim_count": c,
             "type": "official_registry" if "brreg" in s else "website"}
            for s, c in sources.items()
        ]

        entity_src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
        return EvidenceSummary(
            total_claims=total_claims,
            claims_with_source=claims_with_source,
            source_summary=source_summary,
            registry_live={"url": entity_src, "status": "verified", "retrieved_at": utc_now()},
            financials={
                "url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "status": annual_accounts.status,
            },
            roles={
                "url": f"{entity_src}/roller",
                "status": leadership.status,
                "count": len(leadership.roles),
            },
            website={"status": website.status},
        )

    # ── I/O ──

    def _load_input(self) -> list[str]:
        numbers: list[str] = []
        text = self.input_file.read_text(encoding="utf-8")

        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        nr = (item.get("organisasjonsnummer")
                              or item.get("org_number")
                              or item.get("orgnr"))
                        if nr:
                            numbers.append(str(nr))
                    elif isinstance(item, (str, int)):
                        numbers.append(str(item))
                return numbers
        except json.JSONDecodeError:
            pass

        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    nr = (data.get("organisasjonsnummer")
                          or data.get("org_number")
                          or data.get("orgnr"))
                    if nr:
                        numbers.append(str(nr))
                elif isinstance(data, (str, int)):
                    numbers.append(str(data))
            except json.JSONDecodeError:
                if line.isdigit() and len(line) == 9:
                    numbers.append(line)

        return numbers

    def _write_output(self, results: list[dict]):
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        logger.info("output_written", path=str(self.output_file), count=len(results))
