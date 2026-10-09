"""Company profile envelope schema (7 required sections + modular evidence)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ClaimValue(BaseModel):
    value: Any = None
    status: str = "available"
    source: Optional[str] = None
    retrieved_at: Optional[str] = None
    confidence: float = 1.0
    currency: Optional[str] = None
    period: Optional[str] = None


class LegalIdentity(BaseModel):
    status: str = "not_available"
    legal_name: Optional[ClaimValue] = None
    legal_form: Optional[ClaimValue] = None
    registered_address: Optional[ClaimValue] = None
    industry_codes: list[dict[str, Any]] = Field(default_factory=list)
    registration_date: Optional[ClaimValue] = None
    registration_status: Optional[ClaimValue] = None
    foundation_date: Optional[ClaimValue] = None
    statutory_purpose: Optional[ClaimValue] = None
    activity_description: Optional[ClaimValue] = None
    public_brand: Optional[ClaimValue] = None
    official_website: Optional[ClaimValue] = None
    is_bankrupt: bool = False
    is_in_liquidation: bool = False


class AnnualAccounts(BaseModel):
    status: str = "not_available"
    latest_filing_year: Optional[int] = None
    currency: str = "NOK"
    revenue: Optional[ClaimValue] = None
    operating_profit: Optional[ClaimValue] = None
    profit_before_tax: Optional[ClaimValue] = None
    net_income: Optional[ClaimValue] = None
    total_assets: Optional[ClaimValue] = None
    total_equity: Optional[ClaimValue] = None
    total_debt: Optional[ClaimValue] = None
    employees: Optional[ClaimValue] = None
    accounting_obligation: Optional[str] = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class LeadershipWorkplaces(BaseModel):
    status: str = "not_available"
    roles: list[dict[str, Any]] = Field(default_factory=list)
    workplaces: list[dict[str, Any]] = Field(default_factory=list)


class WebsiteProfiles(BaseModel):
    status: str = "not_available"
    official_website: Optional[dict[str, Any]] = None
    social_profiles: list[dict[str, Any]] = Field(default_factory=list)


class HiringActivity(BaseModel):
    status: str = "not_available"
    job_postings: list[dict[str, Any]] = Field(default_factory=list)
    public_activity: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    total_claims: int = 0
    claims_with_source: int = 0
    source_summary: list[dict[str, Any]] = Field(default_factory=list)
    registry_live: Optional[dict[str, Any]] = None
    financials: Optional[dict[str, Any]] = None
    roles: Optional[dict[str, Any]] = None
    locations: Optional[dict[str, Any]] = None
    website: Optional[dict[str, Any]] = None
    accounting_obligation: Optional[dict[str, Any]] = None
    external_footprint: Optional[dict[str, Any]] = None


class RefreshMetadata(BaseModel):
    is_initial_run: bool = True
    previous_version: Optional[int] = None
    material_changes: list[dict[str, Any]] = Field(default_factory=list)
    last_refreshed: Optional[str] = None
    next_suggested_refresh: Optional[str] = None


class Synthesis(BaseModel):
    company_summary: str = ""
    key_observations: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence_assessment: str = ""


class CompanyEnvelope(BaseModel):
    organisation_number: str
    name: Optional[str] = None
    legal_form: Optional[str] = None
    municipality: Optional[str] = None
    website: Optional[str] = None
    profile_version: int = 1
    generated_at: str = Field(default_factory=utc_now)
    status: str = "available"
    legal_identity: LegalIdentity = Field(default_factory=LegalIdentity)
    annual_accounts: AnnualAccounts = Field(default_factory=AnnualAccounts)
    leadership_workplaces: LeadershipWorkplaces = Field(default_factory=LeadershipWorkplaces)
    website_profiles: WebsiteProfiles = Field(default_factory=WebsiteProfiles)
    hiring_activity: HiringActivity = Field(default_factory=HiringActivity)
    evidence: EvidenceSummary = Field(default_factory=EvidenceSummary)
    refresh_metadata: RefreshMetadata = Field(default_factory=RefreshMetadata)
    synthesis: Synthesis = Field(default_factory=Synthesis)

    @classmethod
    def create_failed(cls, org_number: str, error: str) -> "CompanyEnvelope":
        now = utc_now()
        return cls(
            organisation_number=org_number,
            status="failed",
            synthesis=Synthesis(
                company_summary=f"Research failed: {error}",
                confidence_assessment="Failed due to technical error during batch.",
            ),
            refresh_metadata=RefreshMetadata(is_initial_run=True, last_refreshed=now),
        )

    @classmethod
    def create_not_available(cls, org_number: str) -> "CompanyEnvelope":
        now = utc_now()
        return cls(
            organisation_number=org_number,
            status="not_available",
            synthesis=Synthesis(
                company_summary="Entity was searched in public registry but not found.",
                confidence_assessment="Verified absence in official registry.",
            ),
            refresh_metadata=RefreshMetadata(is_initial_run=True, last_refreshed=now),
        )
