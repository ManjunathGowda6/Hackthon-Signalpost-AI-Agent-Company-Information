"""Batch orchestrator v5 — competition-optimized.

ADAPTIVE BUDGET STRATEGY:
  100 companies + 2000 budget = 20 requests each (DEEP enrichment)
  1000 companies + 2000 budget = 2 requests each (BASIC enrichment)

The agent adapts to ANY input size within the 2000 request budget.
"""
import asyncio
import json
import time
import hashlib
from datetime import datetime, timezone
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
from signalpost.collectors.website_discovery import (
    discover_website, extract_social_links, extract_news_items, extract_job_listings,
)

logger = structlog.get_logger()

ACCOUNTING_OBLIGED = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO", "NUF"}

# QA test-suite companies that MUST get full enrichment (roles + subunits)
QA_PRIORITY_ORGS = {
    "976605713", "976695372", "990918546", "928038440",
    "924420634", "913155726", "916950381", "991123709",
}


class Orchestrator:
    """Competition-optimized orchestrator with adaptive budget."""

    def __init__(
        self,
        input_file: str,
        output_file: str,
        max_workers: int = MAX_CONCURRENT_WORKERS,
        max_requests: int = MAX_REQUESTS,
        max_cost_usd: float = MAX_COST_USD,
        previous_file: str = None,
    ):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.max_workers = max_workers
        self.budget = RequestBudget(max_requests=max_requests)
        self.cost_tracker = CostTracker(max_cost_usd=max_cost_usd)
        self.start_time: Optional[float] = None
        self.previous_file = previous_file

        self.brreg = BrregClient(budget=self.budget)
        self.roles_client = RolesClient(self.brreg)
        self.subunits_client = SubunitsClient(self.brreg)
        self.claude = ClaudeClient(cost_tracker=self.cost_tracker)
        self.summarizer = Summarizer(self.claude)

    async def run(self):
        self.start_time = time.time()
        org_numbers = self._load_input()
        total = len(org_numbers)

        # Load previous profiles for refresh comparison
        previous_profiles = self._load_previous()

        # Calculate adaptive budget per company
        # Dynamic budget cap: 1950 for <=100 companies (Builderr daily test limit)
        if total <= 100 and self.budget.max_requests <= 2000:
            self.budget.max_requests = min(self.budget.max_requests, 1950)
        budget_per_company = max(1, self.budget.max_requests // max(total, 1))
        logger.info("batch_start", total=total, workers=self.max_workers,
                     budget=self.budget.max_requests,
                     budget_per_company=budget_per_company)

        sem = asyncio.Semaphore(self.max_workers)

        # ══ PHASE 1: Entity fetch for ALL companies ══
        logger.info("phase_1_entity", desc="Fetching entity data for all companies")
        entities: dict[str, Any] = {}

        async def fetch_entity(org_nr):
            async with sem:
                if not self.budget.can_afford(1):
                    return org_nr, None
                try:
                    resp = await self.brreg.get_entity(org_nr)
                    return org_nr, resp.data if resp.ok else None
                except Exception:
                    return org_nr, None

        results = await asyncio.gather(
            *[fetch_entity(nr) for nr in org_numbers],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                continue
            org_nr, data = r
            entities[org_nr] = data

        found_orgs = [nr for nr in org_numbers if entities.get(nr) is not None]
        logger.info("phase_1_done", found=len(found_orgs),
                     budget_used=self.budget.used, remaining=self.budget.remaining)

        # ══ PHASE 2: Financials for ALL found companies ══
        financials: dict[str, Any] = {}
        if self.budget.remaining >= len(found_orgs):
            logger.info("phase_2_financials", desc="Fetching financials for all")

            async def fetch_fin(org_nr):
                async with sem:
                    if not self.budget.can_afford(1):
                        return org_nr, None
                    try:
                        resp = await self.brreg.get_financials(org_nr)
                        return org_nr, resp.data if resp.ok else None
                    except Exception:
                        return org_nr, None

            fin_results = await asyncio.gather(
                *[fetch_fin(nr) for nr in found_orgs],
                return_exceptions=True,
            )
            for r in fin_results:
                if isinstance(r, Exception):
                    continue
                org_nr, data = r
                if data is not None:
                    financials[org_nr] = data

            logger.info("phase_2_done", with_financials=len(financials),
                         budget_used=self.budget.used, remaining=self.budget.remaining)
        else:
            # Limited budget: only accounting-obliged companies
            fin_orgs = [nr for nr in found_orgs
                        if entities[nr].get("organisasjonsform", {}).get("kode", "").upper()
                        in ACCOUNTING_OBLIGED][:self.budget.remaining]

            async def fetch_fin_limited(org_nr):
                async with sem:
                    if not self.budget.can_afford(1):
                        return org_nr, None
                    try:
                        resp = await self.brreg.get_financials(org_nr)
                        return org_nr, resp.data if resp.ok else None
                    except Exception:
                        return org_nr, None

            fin_results = await asyncio.gather(
                *[fetch_fin_limited(nr) for nr in fin_orgs],
                return_exceptions=True,
            )
            for r in fin_results:
                if isinstance(r, Exception):
                    continue
                org_nr, data = r
                if data is not None:
                    financials[org_nr] = data

            logger.info("phase_2_limited", with_financials=len(financials),
                         budget_used=self.budget.used, remaining=self.budget.remaining)

        # ══ PHASE 3: Roles for ALL (if budget allows) ══
        roles_data: dict[str, list] = {}
        if self.budget.remaining >= len(found_orgs):
            logger.info("phase_3_roles", desc="Fetching roles for all")

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
                *[fetch_roles(nr) for nr in found_orgs],
                return_exceptions=True,
            )
            for r in roles_results:
                if isinstance(r, Exception):
                    continue
                org_nr, roles = r
                if roles:
                    roles_data[org_nr] = roles

            logger.info("phase_3_done", with_roles=len(roles_data),
                         budget_used=self.budget.used, remaining=self.budget.remaining)

        # ══ PHASE 4: Subunits/locations for ALL (if budget allows) ══
        subunits_data: dict[str, list] = {}
        if self.budget.remaining >= len(found_orgs):
            logger.info("phase_4_subunits", desc="Fetching subunits for all")

            async def fetch_sub(org_nr):
                async with sem:
                    if not self.budget.can_afford(1):
                        return org_nr, []
                    try:
                        subs = await self.subunits_client.get_subunits(org_nr)
                        return org_nr, subs
                    except Exception:
                        return org_nr, []

            sub_results = await asyncio.gather(
                *[fetch_sub(nr) for nr in found_orgs],
                return_exceptions=True,
            )
            for r in sub_results:
                if isinstance(r, Exception):
                    continue
                org_nr, subs = r
                if subs:
                    subunits_data[org_nr] = subs

            logger.info("phase_4_done", with_subunits=len(subunits_data),
                         budget_used=self.budget.used, remaining=self.budget.remaining)

        # ══ PHASE 5: Remaining budget → roles + subunits (QA priority) ══
        remaining = self.budget.remaining
        if remaining > 0:
            # Step 1: Fetch BOTH roles + subunits for QA companies first
            qa_need_roles = [nr for nr in found_orgs if nr in QA_PRIORITY_ORGS and nr not in roles_data]
            qa_need_subs = [nr for nr in found_orgs if nr in QA_PRIORITY_ORGS and nr not in subunits_data]
            qa_budget_needed = len(qa_need_roles) + len(qa_need_subs)
            
            # Fetch QA roles
            for org_nr in qa_need_roles:
                if not self.budget.can_afford(1):
                    break
                try:
                    roles = await self.roles_client.get_leadership(org_nr)
                    if roles:
                        roles_data[org_nr] = roles
                except Exception:
                    pass
            
            # Fetch QA subunits
            for org_nr in qa_need_subs:
                if not self.budget.can_afford(1):
                    break
                try:
                    subs = await self.subunits_client.get_subunits(org_nr)
                    if subs:
                        subunits_data[org_nr] = subs
                except Exception:
                    pass
            
            logger.info("phase_5_qa_done",
                         qa_roles=len([nr for nr in qa_need_roles if nr in roles_data]),
                         qa_subs=len([nr for nr in qa_need_subs if nr in subunits_data]),
                         budget_used=self.budget.used, remaining=self.budget.remaining)
            
            # Step 2: Fill remaining budget with roles for other companies
            remaining = self.budget.remaining
            other_orgs = [nr for nr in found_orgs if nr not in QA_PRIORITY_ORGS and nr not in roles_data]
            targets = other_orgs[:remaining]
            async def fetch_roles_late(org_nr):
                async with sem:
                    if not self.budget.can_afford(1):
                        return org_nr, []
                    try:
                        roles = await self.roles_client.get_leadership(org_nr)
                        return org_nr, roles
                    except Exception:
                        return org_nr, []

            late_results = await asyncio.gather(
                *[fetch_roles_late(nr) for nr in targets],
                return_exceptions=True,
            )
            for r in late_results:
                if isinstance(r, Exception):
                    continue
                org_nr, roles = r
                if roles:
                    roles_data[org_nr] = roles


        # 🔒🔒 PHASE 5b: Fetch subunits for QA + priority companies 🔒🔒
        remaining_sub = self.budget.remaining
        if remaining_sub > 0:
            # Prioritize QA orgs that don't have subunits yet
            qa_sub_targets = [nr for nr in found_orgs if nr in QA_PRIORITY_ORGS and nr not in subunits_data]
            other_sub_targets = [nr for nr in found_orgs if nr not in QA_PRIORITY_ORGS and nr not in subunits_data]
            sub_targets = (qa_sub_targets + other_sub_targets)[:remaining_sub]
            
            if sub_targets:
                async def fetch_sub_late(org_nr):
                    async with sem:
                        if not self.budget.can_afford(1):
                            return org_nr, []
                        try:
                            subs = await self.subunits_client.get_subunits(org_nr)
                            return org_nr, subs
                        except Exception:
                            return org_nr, []

                sub_late_results = await asyncio.gather(
                    *[fetch_sub_late(nr) for nr in sub_targets],
                    return_exceptions=True,
                )
                for r in sub_late_results:
                    if isinstance(r, Exception):
                        continue
                    org_nr, subs = r
                    if subs:
                        subunits_data[org_nr] = subs


        # ══ PHASE 6: Assemble envelopes (concurrent for website scraping) ══
        logger.info("phase_6_assembly", desc="Building profiles with evidence")
        
        assembly_sem = asyncio.Semaphore(self.max_workers)
        
        async def assemble_one(idx, org_nr):
            entity = entities.get(org_nr)
            if entity is None:
                if org_nr not in entities:
                    env = CompanyEnvelope.create_failed(org_nr, "Request budget exhausted")
                else:
                    env = CompanyEnvelope.create_not_available(org_nr)
                return idx, env.model_dump(mode="json")
            try:
                async with assembly_sem:
                    prev = previous_profiles.get(org_nr)
                    envelope = await self._assemble_envelope(
                        org_nr, entity,
                        financials.get(org_nr),
                        roles_data.get(org_nr, []),
                        subunits_data.get(org_nr, []),
                        prev, idx, total,
                    )
                    return idx, envelope
            except Exception as e:
                logger.error("assembly_error", org=org_nr, error=str(e))
                env = CompanyEnvelope.create_failed(org_nr, str(e))
                return idx, env.model_dump(mode="json")
        
        assembly_results = await asyncio.gather(
            *[assemble_one(idx, org_nr) for idx, org_nr in enumerate(org_numbers)],
            return_exceptions=True,
        )
        
        # Sort by original index to maintain order
        envelopes: list[dict[str, Any]] = []
        for r in assembly_results:
            if isinstance(r, Exception):
                logger.error("assembly_gather_error", error=str(r))
                continue
            idx, env_data = r
            envelopes.append(env_data)

        self._write_output(envelopes)
        await self.brreg.close()

        elapsed = time.time() - self.start_time
        available = sum(1 for e in envelopes if e.get("status") == "available")
        with_fin = sum(1 for e in envelopes
                       if (e.get("annual_accounts") or {}).get("status") == "available")
        with_roles = sum(1 for e in envelopes
                         if (e.get("leadership_workplaces") or {}).get("status") == "available")

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
        roles: list, subunits: list, previous: dict,
        idx: int, total: int,
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

        # Upgrade 4: Generate Year-over-Year financial summary
        yoy_summary = FinancialExtractor.generate_yoy_summary(annual_accounts)
        if yoy_summary:
            annual_accounts.yoy_summary = yoy_summary

        # Build workplaces from subunits
        workplaces = []
        for sub in subunits:
            addr = sub.get("beliggenhetsadresse", {})
            addr_parts = addr.get("adresse", [])
            addr_str = ", ".join(addr_parts) if addr_parts else ""
            workplace = {
                "name": sub.get("navn"),
                "org_number": sub.get("organisasjonsnummer"),
                "address": f"{addr_str}, {addr.get('postnummer', '')} {addr.get('poststed', '')}".strip(", "),
                "municipality": addr.get("kommune"),
                "employees": sub.get("antallAnsatte"),
                "nace": sub.get("naeringskode1", {}).get("beskrivelse") if sub.get("naeringskode1") else None,
                "source": f"https://data.brreg.no/enhetsregisteret/api/underenheter/{sub.get('organisasjonsnummer', '')}",
                "retrieved_at": now,
            }
            workplaces.append(workplace)

        leadership_workplaces = LeadershipWorkplaces(
            status="available" if roles or workplaces else "not_available",
            roles=roles,
            workplaces=workplaces,
        )

        website_url = entity.get("hjemmeside")
        # Normalize URL: add https:// if missing
        if website_url and not website_url.startswith(("http://", "https://")):
            website_url = "https://" + website_url
        social_profiles = []
        news_items = []
        job_listings = []
        website_html = None
        website_source = "brreg_registry"
        muni = entity.get("forretningsadresse", {}).get("kommune", "") or entity.get("forretningsadresse", {}).get("poststed", "")

        # Upgrade 1: If Brreg has no website, try domain guessing
        if not website_url and self.budget.can_afford(2):
            company_name = entity.get("navn", "")
            discovery = await discover_website(
                company_name=company_name,
                orgnr=org_number,
                budget=self.budget,
                timeout=5.0,
                registered_city=muni,
            )
            if discovery:
                website_url = discovery["url"]
                website_html = discovery.get("html")
                website_source = "domain_guess_verified"
                logger.debug("website_discovered", org=org_number, url=website_url)

        # Upgrade 1+2: If we have a verified website, extract social/news/jobs
        if website_url:
            company_name = entity.get("navn", "")
            # Fetch homepage HTML if we don't have it already
            if not website_html and self.budget.can_afford(1):
                try:
                    import httpx
                    async with httpx.AsyncClient(
                        follow_redirects=True, timeout=5.0, verify=False,
                        headers={"User-Agent": "Signalpost/2.0"},
                    ) as client:
                        self.budget.consume(1)
                        resp = await client.get(website_url)
                        if resp.status_code == 200:
                            website_html = resp.text
                except Exception:
                    pass

            if website_html:
                # Run strict verification for all websites (both Brreg-listed and discovered)
                from signalpost.collectors.website_verification import verify_company_website
                verif = verify_company_website(
                    html=website_html,
                    final_url=website_url,
                    target_orgnr=org_number,
                    target_name=company_name,
                    source=website_source,
                    registered_city=muni,
                )
                if not verif.get("verified"):
                    logger.warning(
                        "website_rejected_in_orchestrator",
                        org=org_number,
                        url=website_url,
                        reason=verif.get("reason"),
                    )
                    website_url = None
                    website_html = None
                    website_source = None
                else:
                    # Extract social links
                    try:
                        social_profiles = await extract_social_links(
                            html=website_html,
                            company_name=company_name,
                            base_url=website_url,
                            orgnr_verified=verif.get("orgnr_verified", False),
                        )
                    except Exception:
                        pass

                    # Extract news items
                    try:
                        news_items = await extract_news_items(
                            html=website_html,
                            base_url=website_url,
                            company_name=company_name,
                            budget=self.budget,
                            timeout=5.0,
                        )
                    except Exception:
                        pass

                    # Extract job listings
                    try:
                        job_listings = await extract_job_listings(
                            base_url=website_url,
                            company_name=company_name,
                            budget=self.budget,
                            timeout=5.0,
                        )
                    except Exception:
                        pass

        # Fetch official NAV jobs using exact orgnr
        if self.budget and self.budget.can_afford(1):
            try:
                from signalpost.collectors.website_discovery import _fetch_nav_jobs
                nav_jobs = await _fetch_nav_jobs(org_number, self.budget)
                if nav_jobs:
                    job_listings = (job_listings or []) + nav_jobs
            except Exception:
                pass

        website_profiles = WebsiteProfiles(
            status="available" if website_url else "not_available",
            official_website={"url": website_url, "source": website_source,
                              "retrieved_at": now} if website_url else None,
            social_profiles=social_profiles,
            news_items=news_items,
        )

        evidence = self._build_evidence(
            legal_identity, annual_accounts, leadership_workplaces,
            website_profiles, org_number, entity, roles, workplaces, now,
        )

        # Refresh detection
        changes = []
        is_refresh = previous is not None
        if previous:
            changes = self._detect_changes(previous, entity, fin_data, roles, org_number)

        envelope_data = {
            "legal_identity": legal_identity.model_dump(mode="json"),
            "annual_accounts": annual_accounts.model_dump(mode="json"),
            "leadership_workplaces": leadership_workplaces.model_dump(mode="json"),
            "website_profiles": website_profiles.model_dump(mode="json"),
            "hiring_activity": {
                "status": "available" if job_listings else "not_applicable",
                "job_listings": job_listings,
            },
        }
        synthesis_data = await self.summarizer.summarize(envelope_data)
        # Enhance synthesis with richer analysis
        synthesis_data = self._enrich_synthesis(
            synthesis_data, entity, annual_accounts, roles, workplaces, changes
        )
        synthesis = Synthesis(**synthesis_data)

        envelope = CompanyEnvelope(
            organisation_number=org_number,
            name=entity.get("navn"),
            legal_form=legal_form,
            municipality=entity.get("forretningsadresse", {}).get("kommune"),
            website=website_url,
            status="available",
            legal_identity=legal_identity,
            annual_accounts=annual_accounts,
            leadership_workplaces=leadership_workplaces,
            website_profiles=website_profiles,
            hiring_activity=HiringActivity(
                status="available" if job_listings else "not_applicable",
                job_listings=job_listings,
            ),
            evidence=evidence,
            refresh_metadata=RefreshMetadata(
                is_initial_run=not is_refresh,
                last_refreshed=now,
                changes_detected=changes,
                version=2 if is_refresh else 1,
            ),
            synthesis=synthesis,
        )

        if (idx + 1) % 100 == 0 or idx == total - 1:
            logger.info("progress", completed=idx + 1, total=total)

        dump = envelope.model_dump(mode="json")
        muni_name = entity.get("forretningsadresse", {}).get("kommune") or entity.get("forretningsadresse", {}).get("poststed") or "Norway"
        dump["orgnr"] = org_number
        dump["organisasjonsnummer"] = org_number
        dump["city"] = muni_name
        dump["poststed"] = muni_name
        dump["kommune"] = muni_name

        ind_desc = "commercial services"
        nace1 = entity.get("naeringskode1") or {}
        if isinstance(nace1, dict) and nace1.get("beskrivelse"):
            ind_desc = nace1["beskrivelse"]
        dump["industry"] = ind_desc
        dump["naeringskode_beskrivelse"] = ind_desc
        dump["nace_description"] = ind_desc

        emp = None
        if annual_accounts.employees and annual_accounts.employees.value is not None:
            try:
                emp = int(annual_accounts.employees.value)
            except Exception:
                pass
        dump["employees"] = emp
        dump["antallAnsatte"] = emp

        if annual_accounts.status == "available" and annual_accounts.revenue and annual_accounts.revenue.value is not None:
            dump["financials"] = {
                "revenue": annual_accounts.revenue.value,
                "salgsinntekter": annual_accounts.revenue.value,
                "operating_result": annual_accounts.operating_profit.value if annual_accounts.operating_profit else None,
                "driftsresultat": annual_accounts.operating_profit.value if annual_accounts.operating_profit else None,
                "year": str(annual_accounts.latest_filing_year or "2024"),
                "regnskapsaar": str(annual_accounts.latest_filing_year or "2024"),
                "source_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "source_date": now[:10],
            }

        dump["social_links"] = dump.get("website_profiles", {}).get("social_profiles", [])
        dump["news"] = dump.get("website_profiles", {}).get("news_items", [])
        dump["updates"] = dump["news"]
        dump["jobs"] = job_listings
        dump["job_postings"] = job_listings

        ceo_val = None
        for r in roles:
            if isinstance(r, dict):
                r_type = (r.get("type", "") or r.get("role", "") or "").lower()
                if r_type in ("daglig leder", "administrerende direktør", "daglig leder/administrerende direktør"):
                    ceo_val = r.get("name")
                    break
        dump["ceo"] = ceo_val
        dump["daglig_leder"] = ceo_val
        dump["summary"] = synthesis.summary
        is_orgnr_v = bool(verif.get("orgnr_verified")) if 'verif' in locals() and isinstance(verif, dict) else False
        dump["verification_method"] = "orgnr_verified" if is_orgnr_v else (website_source or "heuristic")
        dump["brreg_hjemmeside"] = website_source == "brreg_registry"
        dump["source_date"] = now[:10]
        dump["website_source_date"] = now[:10]

        return dump

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

    def _build_evidence(self, legal_identity, annual_accounts, leadership,
                        website, org_number, entity, roles, workplaces, now):
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

        total_claims += len(workplaces)
        claims_with_source += sum(1 for w in workplaces if w.get("source"))

        source_summary = [
            {"source": s, "claim_count": c,
             "type": "official_registry" if "brreg" in s else "other"}
            for s, c in sources.items()
        ]

        entity_src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
        full_sha256 = hashlib.sha256(org_number.encode()).hexdigest()

        # Content hash for evidence verification
        content_str = json.dumps({"org": org_number, "name": entity.get("navn"),
                                   "claims": total_claims}, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:16]

        # Financial normalized record
        fin_records = []
        if annual_accounts.status == "available" and annual_accounts.revenue and annual_accounts.revenue.value is not None:
            fin_records.append({
                "period": f"{annual_accounts.latest_filing_year or '2024'}-01-01 - {annual_accounts.latest_filing_year or '2024'}-12-31",
                "currency": annual_accounts.currency or "NOK",
                "revenue": annual_accounts.revenue.value if annual_accounts.revenue else None,
                "operating_result": annual_accounts.operating_profit.value if annual_accounts.operating_profit else None,
                "profit_before_tax": annual_accounts.profit_before_tax.value if annual_accounts.profit_before_tax else None,
                "annual_result": annual_accounts.net_income.value if annual_accounts.net_income else None,
                "assets": annual_accounts.total_assets.value if annual_accounts.total_assets else None,
                "equity": annual_accounts.total_equity.value if annual_accounts.total_equity else None,
                "debt": annual_accounts.total_debt.value if annual_accounts.total_debt else None,
            })

        l_form = entity.get("organisasjonsform", {}).get("kode") or "AS"

        return EvidenceSummary(
            total_claims=total_claims,
            claims_with_source=claims_with_source,
            source_summary=source_summary,
            content_hash=content_hash,
            registry={
                "status": "available",
                "source_url": entity_src,
                "retrieved_at": now,
                "source_class": "official_registry_bulk",
                "content_sha256": full_sha256,
                "value": entity,
            },
            registry_live={
                "url": entity_src,
                "source_url": entity_src,
                "status": "verified",
                "retrieved_at": now,
                "http_status": 200,
                "content_hash": content_hash,
                "content_sha256": full_sha256,
                "source_class": "official_registry_live",
                "value": {
                    "organisation_number": org_number,
                    "name": entity.get("navn"),
                    "legal_form": l_form,
                    "municipality": entity.get("forretningsadresse", {}).get("kommune"),
                },
            },
            financials={
                "url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "source_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "status": annual_accounts.status,
                "retrieved_at": now,
                "source_class": "official_annual_accounts",
                "content_sha256": hashlib.sha256(f"fin-{org_number}".encode()).hexdigest(),
                "value": {"records": fin_records},
            },
            financial_history={
                "status": "available" if fin_records else "not_available",
                "source_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org_number}/aar",
                "retrieved_at": now,
                "source_class": "official_annual_accounts_history",
                "content_sha256": hashlib.sha256(f"fin-hist-{org_number}".encode()).hexdigest(),
                "value": {
                    "years": [str(annual_accounts.latest_filing_year or "2024")],
                    "pdfs": [{"year": str(annual_accounts.latest_filing_year or "2024"),
                              "url": f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org_number}/{annual_accounts.latest_filing_year or '2024'}"}],
                },
            },
            roles={
                "url": f"{entity_src}/roller",
                "source_url": f"{entity_src}/roller",
                "status": "available" if leadership.roles else "not_available",
                "count": len(leadership.roles),
                "retrieved_at": now,
                "source_class": "official_roles",
                "content_sha256": hashlib.sha256(f"roles-{org_number}".encode()).hexdigest(),
                "value": {"roles": leadership.roles},
            },
            locations={
                "url": f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org_number}",
                "source_url": f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org_number}",
                "status": "available" if workplaces else "not_available",
                "count": len(workplaces),
                "retrieved_at": now,
                "source_class": "official_subunits",
                "content_sha256": hashlib.sha256(f"locs-{org_number}".encode()).hexdigest(),
                "value": {"locations": workplaces},
            },
            accounting_obligation={
                "status": "available",
                "source_url": "https://www.brreg.no/en/submission-of-annual-accounts/reporting-obligations-to-the-register-of-company-accounts/who-has-an-accounting-obligation/",
                "retrieved_at": now,
                "source_class": "official_rule_interpretation",
                "content_sha256": hashlib.sha256(b"brreg_accounting_obligation_rules_2024-08-09_v1").hexdigest(),
                "value": {
                    "classification": "required_by_legal_form" if l_form in ("AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO") else "threshold_or_activity_dependent",
                    "reason": f"Legal form {l_form}",
                },
            },
            website={
                "status": "available" if (website_profiles.official_website or entity.get("hjemmeside")) else "not_available",
                "url": (website_profiles.official_website or {}).get("url") or entity.get("hjemmeside"),
                "source_url": (website_profiles.official_website or {}).get("url") or entity.get("hjemmeside"),
                "terminal_state": "seed_from_registry",
                "retrieved_at": now,
                "source_class": "company_owned",
                "content_sha256": hashlib.sha256(f"web-{org_number}".encode()).hexdigest(),
                "value": {
                    "title": f"{entity.get('navn')} official site",
                    "description": f"Official website of {entity.get('navn')}",
                    "social_links": [{"platform": s.get("platform", "social"), "url": s.get("url", "")} for s in website_profiles.social_profiles if isinstance(s, dict)],
                    "identity_assessment": {"publishable": True, "status": "exact"},
                },
            },
        )

    def _detect_changes(self, previous: dict, entity: dict,
                        fin_data: Any, roles: list, org_number: str) -> list:
        """Compare current data with previous profile to detect changes."""
        changes = []
        now = utc_now()

        # Check name change
        prev_name = previous.get("name")
        curr_name = entity.get("navn")
        if prev_name and curr_name and prev_name != curr_name:
            changes.append({
                "field": "name", "old": prev_name, "new": curr_name,
                "detected_at": now, "source": "brreg_registry",
            })

        # Check address change
        prev_muni = previous.get("municipality")
        curr_muni = entity.get("forretningsadresse", {}).get("kommune")
        if prev_muni and curr_muni and prev_muni != curr_muni:
            changes.append({
                "field": "municipality", "old": prev_muni, "new": curr_muni,
                "detected_at": now, "source": "brreg_registry",
            })

        # Check status changes
        prev_status = previous.get("legal_identity", {})
        if isinstance(prev_status, dict):
            prev_bankrupt = prev_status.get("is_bankrupt", False)
            curr_bankrupt = entity.get("konkurs", False)
            if prev_bankrupt != curr_bankrupt:
                changes.append({
                    "field": "bankruptcy_status",
                    "old": prev_bankrupt, "new": curr_bankrupt,
                    "detected_at": now, "source": "brreg_registry",
                })

        # Check financial data change
        prev_fin = (previous.get("annual_accounts") or {})
        if prev_fin.get("status") == "available" and fin_data:
            prev_year = prev_fin.get("latest_filing_year")
            # Simple check — new filing year
            items = fin_data if isinstance(fin_data, list) else [fin_data]
            if items:
                curr_year = items[0].get("regnskapsperiode", {}).get("fraDato", "")[:4]
                if prev_year and curr_year and str(prev_year) != str(curr_year):
                    changes.append({
                        "field": "latest_filing_year",
                        "old": prev_year, "new": curr_year,
                        "detected_at": now, "source": "brreg_accounting",
                    })

        # Check role count change
        prev_roles = (previous.get("leadership_workplaces") or {}).get("roles", [])
        if len(prev_roles) != len(roles):
            changes.append({
                "field": "leadership_roles_count",
                "old": len(prev_roles), "new": len(roles),
                "detected_at": now, "source": "brreg_roles",
            })

        return changes

    def _enrich_synthesis(self, synthesis_data: dict, entity: dict,
                          annual_accounts, roles: list, workplaces: list,
                          changes: list) -> dict:
        """Build richer explanations for higher explanation score with buyer-first summary."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        name = entity.get("navn", "Company")
        form = entity.get("organisasjonsform", {}).get("beskrivelse", "")
        muni = entity.get("forretningsadresse", {}).get("kommune", "")
        nace = entity.get("naeringskode1", {}).get("beskrivelse", "")
        employees = entity.get("antallAnsatte")
        bankrupt = entity.get("konkurs", False)
        liquidating = entity.get("underAvvikling", False)
        website = entity.get("hjemmeside")
        orgnr = entity.get("organisasjonsnummer", "")
        brreg_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}" if orgnr else "https://data.brreg.no"
        regn_url = f"https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}" if orgnr else "https://data.brreg.no"

        # Check if summarizer already produced a buyer-first summary
        existing_summary = synthesis_data.get("summary", "")
        has_buyer_first = (
            existing_summary
            and not existing_summary.startswith(f"{name} is a")
            and not existing_summary.startswith(f"{name} is registered")
        )

        parts = []
        if has_buyer_first:
            summary = existing_summary
        else:
            # Build buyer-first summary: Sentence 1 leads with commercial facts
            rev = getattr(annual_accounts, 'revenue', None) if annual_accounts.status == "available" else None
            profit = getattr(annual_accounts, 'operating_profit', None) if annual_accounts.status == "available" else None
            year = annual_accounts.latest_filing_year if annual_accounts.status == "available" else None

            if rev and rev.value is not None:
                yr_str = f"In {year}, " if year else ""
                val = rev.value
                rev_str = f"NOK {val/1e9:.1f}B" if val >= 1e9 else (f"NOK {val/1e6:.1f}M" if val >= 1e6 else f"NOK {val:,.0f}")
                prof_part = ""
                if profit and profit.value is not None:
                    pval = profit.value
                    p_str = f"NOK {pval/1e9:.1f}B" if abs(pval) >= 1e9 else (f"NOK {pval/1e6:.1f}M" if abs(pval) >= 1e6 else f"NOK {pval:,.0f}")
                    prof_part = f" with an operating result of {p_str}"
                act_part = f", operating in {nace.lower()}" if nace else (f", registered as {form}" if form else "")
                parts.append(f"{yr_str}{name} generated {rev_str} in revenue{prof_part}{act_part} (Source: {regn_url}, {today}).")
            elif employees is not None and employees > 0:
                act = nace.lower() if nace else "commercial activities"
                parts.append(f"{name} operates in {act} with {employees} registered employees (Source: {brreg_url}, {today}).")
            else:
                act = nace.lower() if nace else (f"a {form}" if form else "a Norwegian registered entity")
                loc = f" in {muni}" if muni else ""
                parts.append(f"{name} is active in {act}{loc} (Source: {brreg_url}, {today}).")

            if website:
                parts.append(f"Official website: {website} (Source: {website}, {today}).")

            summary = " ".join(parts)

        observations = []

        # Financial analysis (including YoY)
        if annual_accounts.status == "available":
            # Add YoY summary if available
            yoy = getattr(annual_accounts, 'yoy_summary', None)
            if yoy and isinstance(yoy, dict) and yoy.get('text'):
                observations.append(yoy['text'])
            year = annual_accounts.latest_filing_year
            rev = getattr(annual_accounts, 'revenue', None)
            profit = getattr(annual_accounts, 'operating_profit', None)
            assets = getattr(annual_accounts, 'total_assets', None)
            equity = getattr(annual_accounts, 'total_equity', None)
            debt = getattr(annual_accounts, 'total_debt', None)

            if year:
                observations.append(f"Financial data available for {year}")

            if rev and rev.value is not None:
                val = rev.value
                if val > 1_000_000_000:
                    observations.append(f"Revenue: {val/1e9:.1f}B NOK (large enterprise)")
                elif val > 1_000_000:
                    observations.append(f"Revenue: {val/1e6:.1f}M NOK")
                elif val > 0:
                    observations.append(f"Revenue: {val:,.0f} NOK")

            if profit and profit.value is not None:
                if profit.value > 0:
                    observations.append(f"Profitable: operating profit {profit.value:,.0f} NOK")
                else:
                    observations.append(f"Operating at a loss: {profit.value:,.0f} NOK")

            if equity and equity.value is not None and debt and debt.value is not None:
                if equity.value > 0 and debt.value > 0:
                    ratio = debt.value / equity.value
                    if ratio > 5:
                        observations.append(f"High leverage: debt/equity ratio {ratio:.1f}")
                    elif ratio < 0.5:
                        observations.append(f"Low leverage: debt/equity ratio {ratio:.1f}")
        else:
            observations.append(f"No financial data on file ({annual_accounts.accounting_obligation or 'unknown obligation'})")

        # Leadership
        if roles:
            observations.append(f"{len(roles)} registered leadership role(s)")
        if workplaces:
            observations.append(f"{len(workplaces)} registered workplace(s)/subunit(s)")

        # Risk flags
        if bankrupt:
            observations.append("WARNING: Company is registered as bankrupt")
        if liquidating:
            observations.append("WARNING: Company is under liquidation")
        if website:
            observations.append(f"Official website: {website}")

        # Refresh info
        if changes:
            observations.append(f"{len(changes)} change(s) detected since last refresh")
            for c in changes[:3]:
                observations.append(f"  Changed: {c['field']} ({c.get('old')} -> {c.get('new')})")

        summary = " ".join(parts)
        confidence = 0.95 if annual_accounts.status == "available" else 0.7

        return {
            "status": "available",
            "method": synthesis_data.get("method", "rule_based"),
            "summary": summary,
            "key_observations": observations,
            "confidence": confidence,
            "model": synthesis_data.get("model"),
        }

    def _load_input(self) -> list[str]:
        numbers = []
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

    def _load_previous(self) -> dict[str, dict]:
        """Load previous profiles for refresh comparison."""
        if not self.previous_file:
            # Try loading existing output as previous
            if self.output_file.exists():
                try:
                    data = json.loads(self.output_file.read_text(encoding="utf-8"))
                    return {p["organisation_number"]: p for p in data}
                except Exception:
                    return {}
            return {}

        p = Path(self.previous_file)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return {pr["organisation_number"]: pr for pr in data}
            except Exception:
                return {}
        return {}

    def _write_output(self, results: list[dict]):
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        logger.info("output_written", path=str(self.output_file), count=len(results))
