"""Batch orchestrator -- smart budget allocation for maximum section coverage.

Budget Strategy for 2,000 requests / 1,000 companies:
  Phase 1: Entity fetch for ALL companies             (1,000 requests)
  Phase 2: Interleave financials + roles               (1,000 requests)
           - Each company gets ONE enrichment call
           - AS/ASA/BRL -> financials (they file accounts)
           - Others -> roles (they rarely have accounts)
  Result: Every company has legal_identity + at least one more section.
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
from signalpost.extractors.financial_extractor import FinancialExtractor
from signalpost.synthesis.claude_client import ClaudeClient
from signalpost.synthesis.summarizer import Summarizer

logger = structlog.get_logger()

# Legal forms that are ALWAYS accounting-obliged
ACCOUNTING_OBLIGED = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO", "NUF"}


class Orchestrator:
    """Runs company research with smart budget allocation."""

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

        self.brreg = BrregClient(budget=self.budget)
        self.roles_client = RolesClient(self.brreg)
        self.claude = ClaudeClient(cost_tracker=self.cost_tracker)
        self.summarizer = Summarizer(self.claude)

    async def run(self):
        self.start_time = time.time()
        org_numbers = self._load_input()
        total = len(org_numbers)
        logger.info("batch_start", total=total, workers=self.max_workers,
                     budget=self.budget.max_requests)

        # ── Phase 1: Fetch all entities ──
        logger.info("phase_1_entity", desc="Fetching entity data for all companies")
        sem = asyncio.Semaphore(self.max_workers)
        entities: dict[str, Any] = {}

        async def fetch_entity(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, None
                resp = await self.brreg.get_entity(org_nr)
                return org_nr, resp.data if resp.ok else None

        results = await asyncio.gather(
            *[fetch_entity(nr) for nr in org_numbers],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                continue
            org_nr, data = r
            entities[org_nr] = data

        found_count = sum(1 for v in entities.values() if v is not None)
        logger.info("phase_1_done", found=found_count, budget_used=self.budget.used,
                     budget_remaining=self.budget.remaining)

        # ── Phase 2: Smart enrichment — financials OR roles per company ──
        # Split companies by legal form to decide which enrichment to prioritize
        fin_priority: list[str] = []   # Companies that should get financials
        roles_priority: list[str] = [] # Companies that should get roles

        for org_nr in org_numbers:
            entity = entities.get(org_nr)
            if entity is None:
                continue
            legal_form = entity.get("organisasjonsform", {}).get("kode", "")
            if legal_form.upper() in ACCOUNTING_OBLIGED:
                fin_priority.append(org_nr)
            else:
                roles_priority.append(org_nr)

        remaining = self.budget.remaining
        logger.info("phase_2_plan",
                     financial_candidates=len(fin_priority),
                     roles_candidates=len(roles_priority),
                     budget_remaining=remaining)

        # Allocate budget: financials for obliged companies, roles for the rest
        # If budget allows, also get roles for financial companies
        financials: dict[str, Any] = {}
        roles_data: dict[str, list] = {}

        # Phase 2a: Financials for accounting-obliged companies
        logger.info("phase_2a_financials", count=min(len(fin_priority), remaining))

        async def fetch_financials(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, None
                resp = await self.brreg.get_financials(org_nr)
                return org_nr, resp.data if resp.ok else None

        fin_tasks = [fetch_financials(nr) for nr in fin_priority]
        fin_results = await asyncio.gather(*fin_tasks, return_exceptions=True)
        for r in fin_results:
            if isinstance(r, Exception):
                continue
            org_nr, data = r
            if data is not None:
                financials[org_nr] = data

        logger.info("phase_2a_done", with_financials=len(financials),
                     budget_used=self.budget.used)

        # Phase 2b: Roles for non-obliged companies (and any remaining budget)
        remaining = self.budget.remaining
        if remaining > 0:
            # First: roles for non-accounting companies
            # Then: roles for accounting companies if budget still available
            roles_targets = roles_priority + fin_priority
            roles_targets = roles_targets[:remaining]

            logger.info("phase_2b_roles", count=len(roles_targets),
                         budget_remaining=remaining)

            async def fetch_roles(org_nr):
                async with sem:
                    if not self.budget.can_afford(1):
                        return org_nr, []
                    try:
                        roles = await self.roles_client.get_leadership(org_nr)
                        return org_nr, roles
                    except Exception:
                        return org_nr, []

            roles_results = await asyncio.gather(
                *[fetch_roles(nr) for nr in roles_targets],
                return_exceptions=True,
            )
            for r in roles_results:
                if isinstance(r, Exception):
                    continue
                org_nr, roles = r
                if roles:
                    roles_data[org_nr] = roles

        logger.info("phase_2b_done", with_roles=len(roles_data),
                     budget_used=self.budget.used)

        # ── Phase 3: Assemble all envelopes ──
        logger.info("phase_3_assembly", desc="Building company profiles")
        envelopes: list[dict[str, Any]] = []

        for idx, org_nr in enumerate(org_numbers):
            entity = entities.get(org_nr)
            if entity is None:
                if org_nr not in entities:
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
        with_fin = sum(1 for e in envelopes
                       if e.get("annual_accounts", {}).get("status") == "available")
        with_roles = sum(1 for e in envelopes
                         if e.get("leadership_workplaces", {}).get("status") == "available")

        logger.info(
            "batch_complete",
            total=total,
            available=available,
            with_financials=with_fin,
            with_leadership=with_roles,
            elapsed_sec=round(elapsed, 1),
            requests_used=self.budget.used,
            cost_usd=round(self.cost_tracker.total_cost, 4),
        )

    async def _assemble_envelope(
        self, org_number: str, entity: dict, fin_data: Any,
        roles: list[dict], idx: int, total: int,
    ) -> dict[str, Any]:
        now = utc_now()
        legal_identity = self._build_legal_identity(entity, org_number, now)

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

        leadership_workplaces = LeadershipWorkplaces(
            status="available" if roles else "not_available",
            roles=roles,
            workplaces=[],
        )

        website_url = entity.get("hjemmeside")
        website_profiles = WebsiteProfiles(
            status="available" if website_url else "not_available",
            official_website={"url": website_url, "source": "brreg_registry",
                              "retrieved_at": now} if website_url else None,
        )

        evidence = self._build_evidence(
            legal_identity, annual_accounts, leadership_workplaces,
            website_profiles, org_number,
        )

        envelope_data = {
            "legal_identity": legal_identity.model_dump(mode="json"),
            "annual_accounts": annual_accounts.model_dump(mode="json"),
            "leadership_workplaces": leadership_workplaces.model_dump(mode="json"),
            "website_profiles": website_profiles.model_dump(mode="json"),
            "hiring_activity": {"status": "not_applicable"},
        }
        synthesis_data = await self.summarizer.summarize(envelope_data)
        synthesis = Synthesis(**synthesis_data)

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
            refresh_metadata=RefreshMetadata(is_initial_run=True, last_refreshed=now),
            synthesis=synthesis,
        )

        if (idx + 1) % 200 == 0 or idx == total - 1:
            logger.info("progress", completed=idx + 1, total=total)

        return envelope.model_dump(mode="json")

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
            registered_address=ClaimValue(
                value=full_addr, source=src, retrieved_at=now
            ) if full_addr else None,
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
                value=entity.get("hjemmeside"), source=src, retrieved_at=now,
            ) if entity.get("hjemmeside") else None,
            is_bankrupt=entity.get("konkurs", False),
            is_in_liquidation=entity.get("underAvvikling", False),
        )

    def _build_evidence(self, legal_identity, annual_accounts,
                        leadership, website, org_number):
        total_claims = 0
        claims_with_source = 0
        sources: dict[str, int] = {}

        for fn in ["legal_name", "legal_form", "registered_address",
                    "registration_date", "registration_status",
                    "activity_description", "official_website"]:
            claim = getattr(legal_identity, fn, None)
            if claim and claim.value is not None:
                total_claims += 1
                if claim.source:
                    claims_with_source += 1
                    sources[claim.source] = sources.get(claim.source, 0) + 1

        total_claims += len(legal_identity.industry_codes)
        claims_with_source += len(legal_identity.industry_codes)

        for fn in ["revenue", "operating_profit", "profit_before_tax",
                    "net_income", "total_assets", "total_equity",
                    "total_debt", "employees"]:
            claim = getattr(annual_accounts, fn, None)
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
             "type": "official_registry" if "brreg" in s else "other"}
            for s, c in sources.items()
        ]

        entity_src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
        return EvidenceSummary(
            total_claims=total_claims,
            claims_with_source=claims_with_source,
            source_summary=source_summary,
            registry_live={"url": entity_src, "status": "verified",
                           "retrieved_at": utc_now()},
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

    def _load_input(self) -> list[str]:
        numbers: list[str] = []
        text = self.input_file.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        nr = (item.get("organisasjonsnummer")
                              or item.get("org_number") or item.get("orgnr"))
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
                          or data.get("org_number") or data.get("orgnr"))
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
