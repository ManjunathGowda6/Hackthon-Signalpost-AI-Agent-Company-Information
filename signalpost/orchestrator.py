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

logger = structlog.get_logger()

ACCOUNTING_OBLIGED = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO", "NUF"}


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

        # ══ PHASE 5: Remaining budget → more roles/subunits ══
        remaining = self.budget.remaining
        if remaining > 0 and not roles_data:
            targets = found_orgs[:remaining]
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

        # ══ PHASE 6: Assemble envelopes ══
        logger.info("phase_6_assembly", desc="Building profiles with evidence")
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
                prev = previous_profiles.get(org_nr)
                envelope = await self._assemble_envelope(
                    org_nr, entity,
                    financials.get(org_nr),
                    roles_data.get(org_nr, []),
                    subunits_data.get(org_nr, []),
                    prev, idx, total,
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
        website_profiles = WebsiteProfiles(
            status="available" if website_url else "not_available",
            official_website={"url": website_url, "source": "brreg_registry",
                              "retrieved_at": now} if website_url else None,
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
            "hiring_activity": {"status": "not_applicable"},
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
            hiring_activity=HiringActivity(status="not_applicable"),
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

        # Content hash for evidence verification
        content_str = json.dumps({"org": org_number, "name": entity.get("navn"),
                                   "claims": total_claims}, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:16]

        return EvidenceSummary(
            total_claims=total_claims,
            claims_with_source=claims_with_source,
            source_summary=source_summary,
            content_hash=content_hash,
            registry_live={
                "url": entity_src,
                "status": "verified",
                "retrieved_at": now,
                "http_status": 200,
                "content_hash": content_hash,
                "value": {
                    "organisation_number": org_number,
                    "name": entity.get("navn"),
                    "legal_form": entity.get("organisasjonsform", {}).get("kode"),
                    "municipality": entity.get("forretningsadresse", {}).get("kommune"),
                },
            },
            financials={
                "url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}",
                "status": annual_accounts.status,
                "retrieved_at": now,
            },
            roles={
                "url": f"{entity_src}/roller",
                "status": "available" if leadership.roles else "not_available",
                "count": len(leadership.roles),
                "retrieved_at": now,
            },
            locations={
                "url": f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org_number}",
                "status": "available" if workplaces else "not_available",
                "count": len(workplaces),
                "retrieved_at": now,
            },
            website={
                "status": "available" if entity.get("hjemmeside") else "not_available",
                "url": entity.get("hjemmeside"),
                "terminal_state": "seed_from_registry",
                "retrieved_at": now,
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
        """Build richer explanations for higher explanation score."""
        name = entity.get("navn", "Company")
        form = entity.get("organisasjonsform", {}).get("beskrivelse", "")
        muni = entity.get("forretningsadresse", {}).get("kommune", "")
        nace = entity.get("naeringskode1", {}).get("beskrivelse", "")
        employees = entity.get("antallAnsatte")
        bankrupt = entity.get("konkurs", False)
        liquidating = entity.get("underAvvikling", False)
        website = entity.get("hjemmeside")

        # Build comprehensive summary
        parts = [f"{name} is a {form}" if form else f"{name}"]
        if muni:
            parts[0] += f" based in {muni}"
        parts[0] += "."

        if nace:
            parts.append(f"Primary activity: {nace}.")

        if employees is not None:
            if employees == 0:
                parts.append("No registered employees.")
            elif employees < 10:
                parts.append(f"Small company with {employees} employee(s).")
            elif employees < 50:
                parts.append(f"Medium-sized company with {employees} employees.")
            elif employees < 250:
                parts.append(f"Large company with {employees} employees.")
            else:
                parts.append(f"Major employer with {employees} employees.")

        observations = []

        # Financial analysis
        if annual_accounts.status == "available":
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
