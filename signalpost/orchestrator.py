"""Batch processing orchestrator — full company research pipeline."""
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
    """Runs the full company research pipeline for a batch of org numbers."""

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
        self.subunits_client = SubunitsClient(self.brreg)
        self.claude = ClaudeClient(cost_tracker=self.cost_tracker)
        self.summarizer = Summarizer(self.claude)

    async def run(self):
        """Execute the full batch pipeline."""
        self.start_time = time.time()
        org_numbers = self._load_input()
        total = len(org_numbers)
        logger.info("batch_start", total=total, workers=self.max_workers)

        sem = asyncio.Semaphore(self.max_workers)
        tasks = [self._process_company(nr, idx, total, sem)
                 for idx, nr in enumerate(org_numbers)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Ensure we always return one envelope per input
        final: list[dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                env = CompanyEnvelope.create_failed(org_numbers[i], str(r))
                final.append(env.model_dump(mode="json"))
            elif isinstance(r, dict):
                final.append(r)
            else:
                env = CompanyEnvelope.create_failed(org_numbers[i], "Unknown error")
                final.append(env.model_dump(mode="json"))

        self._write_output(final)
        await self.brreg.close()

        elapsed = time.time() - self.start_time
        logger.info(
            "batch_complete",
            total=total,
            elapsed_sec=round(elapsed, 1),
            requests_used=self.budget.used,
            cost_usd=round(self.cost_tracker.total_cost, 4),
        )

    async def _process_company(
        self, org_number: str, idx: int, total: int, sem: asyncio.Semaphore
    ) -> dict[str, Any]:
        """Research a single company through the full pipeline."""
        async with sem:
            # Check time budget
            if self.start_time and (time.time() - self.start_time) >= MAX_TIME_SECONDS:
                return CompanyEnvelope.create_failed(
                    org_number, "Time budget exceeded"
                ).model_dump(mode="json")

            log = logger.bind(org=org_number, progress=f"{idx+1}/{total}")

            try:
                return await self._research_company(org_number, log)
            except Exception as e:
                log.error("company_failed", error=str(e))
                return CompanyEnvelope.create_failed(
                    org_number, str(e)
                ).model_dump(mode="json")

    async def _research_company(self, org_number: str, log) -> dict[str, Any]:
        """Full research pipeline for one company."""
        now = utc_now()

        # ── Step 1: Fetch entity from Brreg ──
        entity_resp = await self.brreg.get_entity(org_number)

        if not entity_resp.ok:
            if entity_resp.status_code == 404:
                log.info("entity_not_found")
                return CompanyEnvelope.create_not_available(org_number).model_dump(mode="json")
            log.warning("entity_fetch_failed", status=entity_resp.status_code)
            return CompanyEnvelope.create_failed(
                org_number, f"Registry returned HTTP {entity_resp.status_code}"
            ).model_dump(mode="json")

        entity = entity_resp.data
        log.info("entity_found", name=entity.get("navn"))

        # ── Step 2: Build Legal Identity ──
        legal_identity = self._build_legal_identity(entity, org_number, now)

        # ── Step 3: Fetch roles (leadership / board) ──
        roles = await self._fetch_roles(org_number, log)

        # ── Step 4: Fetch subunits (workplaces) ──
        workplaces = await self._fetch_subunits(org_number, log)

        leadership_workplaces = LeadershipWorkplaces(
            status="available" if (roles or workplaces) else "not_available",
            roles=roles,
            workplaces=workplaces,
        )

        # ── Step 5: Fetch financials from Regnskapsregisteret ──
        annual_accounts = await self._fetch_financials(
            org_number, entity, legal_identity, log
        )

        # ── Step 6: Crawl company website ──
        website_profiles = await self._fetch_website(org_number, entity, log)

        # ── Step 7: Evidence summary ──
        evidence = self._build_evidence(
            entity_resp, legal_identity, annual_accounts,
            leadership_workplaces, website_profiles, org_number
        )

        # ── Step 8: Synthesis ──
        envelope_data = {
            "legal_identity": legal_identity.model_dump(mode="json"),
            "annual_accounts": annual_accounts.model_dump(mode="json"),
            "leadership_workplaces": leadership_workplaces.model_dump(mode="json"),
            "website_profiles": website_profiles.model_dump(mode="json"),
            "hiring_activity": {"status": "not_applicable"},
        }
        synthesis_data = await self.summarizer.summarize(envelope_data)
        synthesis = Synthesis(**synthesis_data)

        # ── Assemble envelope ──
        envelope = CompanyEnvelope(
            organisation_number=org_number,
            name=entity.get("navn"),
            legal_form=entity.get("organisasjonsform", {}).get("kode"),
            municipality=entity.get("forretningsadresse", {}).get("kommune"),
            website=entity.get("hjemmeside"),
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

        log.info("envelope_built",
                 sections_available=sum(1 for s in [
                     legal_identity.status, annual_accounts.status,
                     leadership_workplaces.status, website_profiles.status,
                 ] if s == "available"))

        return envelope.model_dump(mode="json")

    # ── Pipeline helpers ──

    def _build_legal_identity(self, entity: dict, org_number: str, now: str) -> LegalIdentity:
        """Build LegalIdentity from Brreg entity data."""
        src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"

        # Address
        addr = entity.get("forretningsadresse", {})
        addr_parts = addr.get("adresse", [])
        addr_str = ", ".join(addr_parts) if addr_parts else None
        full_addr = None
        if addr_str:
            full_addr = f"{addr_str}, {addr.get('postnummer','')} {addr.get('poststed','')}"

        # Industry codes (NACE)
        codes = []
        nace = entity.get("naeringskode1")
        if nace:
            codes.append({
                "code": nace.get("kode"),
                "description": nace.get("beskrivelse"),
                "system": "NACE",
                "source": src,
            })
        nace2 = entity.get("naeringskode2")
        if nace2:
            codes.append({
                "code": nace2.get("kode"),
                "description": nace2.get("beskrivelse"),
                "system": "NACE",
                "source": src,
            })
        nace3 = entity.get("naeringskode3")
        if nace3:
            codes.append({
                "code": nace3.get("kode"),
                "description": nace3.get("beskrivelse"),
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

    async def _fetch_roles(self, org_number: str, log) -> list[dict]:
        try:
            return await self.roles_client.get_leadership(org_number)
        except Exception as e:
            log.warning("roles_error", error=str(e))
            return []

    async def _fetch_subunits(self, org_number: str, log) -> list[dict]:
        try:
            return await self.subunits_client.get_workplaces(org_number)
        except Exception as e:
            log.warning("subunits_error", error=str(e))
            return []

    async def _fetch_financials(
        self, org_number: str, entity: dict, legal_identity: LegalIdentity, log
    ) -> AnnualAccounts:
        """Fetch and parse financial data from Regnskapsregisteret."""
        legal_form = entity.get("organisasjonsform", {}).get("kode")
        employees = entity.get("antallAnsatte")

        try:
            fin_resp = await self.brreg.get_financials(org_number)
            if fin_resp.ok:
                log.info("financials_found")
                return FinancialExtractor.extract_accounts(
                    fin_resp.data, org_number,
                    legal_form=legal_form,
                    registry_employees=employees,
                )
            else:
                log.info("financials_not_found", status=fin_resp.status_code)
                obligation = FinancialExtractor.assess_obligation(legal_form, False)
                return AnnualAccounts(
                    status="not_available",
                    accounting_obligation=obligation["classification"],
                    employees=ClaimValue(
                        value=employees,
                        source=f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}",
                        retrieved_at=utc_now(),
                    ) if employees is not None else None,
                )
        except Exception as e:
            log.warning("financials_error", error=str(e))
            return AnnualAccounts(status="failed")

    async def _fetch_website(
        self, org_number: str, entity: dict, log
    ) -> WebsiteProfiles:
        """Fetch and analyze company website."""
        website_url = entity.get("hjemmeside")
        if not website_url:
            return WebsiteProfiles(status="not_available")

        if not self.budget.can_afford(1):
            return WebsiteProfiles(status="blocked")

        try:
            from signalpost.collectors.website_collector import WebsiteCollector
            collector = WebsiteCollector(budget=self.budget)
            result = await collector.collect(org_number, entity)

            if result.get("website_status") == "available":
                pages = result.get("pages", [])
                return WebsiteProfiles(
                    status="available",
                    official_website={
                        "url": result.get("website_url", website_url),
                        "title": pages[0].get("title") if pages else None,
                        "content_preview": (pages[0].get("main_text", "")[:500]
                                            if pages else None),
                        "retrieved_at": utc_now(),
                    },
                    social_profiles=result.get("social_links", []),
                )
            else:
                return WebsiteProfiles(status=result.get("website_status", "failed"))
        except Exception as e:
            log.warning("website_error", error=str(e))
            return WebsiteProfiles(status="failed")

    def _build_evidence(
        self,
        entity_resp,
        legal_identity: LegalIdentity,
        annual_accounts: AnnualAccounts,
        leadership: LeadershipWorkplaces,
        website: WebsiteProfiles,
        org_number: str,
    ) -> EvidenceSummary:
        """Build evidence summary tracking all sources and claim counts."""
        total_claims = 0
        claims_with_source = 0
        sources = {}

        # Count claims in legal_identity
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

        # Count claims in annual_accounts
        for field_name in ["revenue", "operating_profit", "profit_before_tax",
                           "net_income", "total_assets", "total_equity",
                           "total_debt", "employees"]:
            claim = getattr(annual_accounts, field_name, None)
            if claim and claim.value is not None:
                total_claims += 1
                if claim.source:
                    claims_with_source += 1
                    sources[claim.source] = sources.get(claim.source, 0) + 1

        # Roles and workplaces
        total_claims += len(leadership.roles) + len(leadership.workplaces)
        claims_with_source += sum(1 for r in leadership.roles if r.get("source"))
        claims_with_source += sum(1 for w in leadership.workplaces if w.get("source"))
        for r in leadership.roles:
            s = r.get("source", "")
            if s:
                sources[s] = sources.get(s, 0) + 1

        source_summary = [
            {"source": s, "claim_count": c, "type": "official_registry" if "brreg" in s else "website"}
            for s, c in sources.items()
        ]

        entity_src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
        return EvidenceSummary(
            total_claims=total_claims,
            claims_with_source=claims_with_source,
            source_summary=source_summary,
            registry_live={
                "url": entity_src,
                "status": "verified",
                "content_hash": entity_resp.sha256,
                "retrieved_at": utc_now(),
            },
            financials={
                "url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "status": annual_accounts.status,
            },
            roles={
                "url": f"{entity_src}/roller",
                "status": leadership.status,
                "count": len(leadership.roles),
            },
            locations={
                "status": "available" if leadership.workplaces else "not_available",
                "count": len(leadership.workplaces),
            },
            website={
                "status": website.status,
                "url": (website.official_website or {}).get("url"),
            },
        )

    # ── I/O ──

    def _load_input(self) -> list[str]:
        """Load organisation numbers from JSONL, plain text, or JSON."""
        numbers: list[str] = []
        text = self.input_file.read_text(encoding="utf-8")

        # Try as JSON array first
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

        # Try JSONL / plain text
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
                # Plain org number
                if line.isdigit() and len(line) == 9:
                    numbers.append(line)

        return numbers

    def _write_output(self, results: list[dict]):
        """Write results as JSON array."""
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        logger.info("output_written", path=str(self.output_file), count=len(results))
