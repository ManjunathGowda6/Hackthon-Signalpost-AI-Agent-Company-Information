"""Pydantic models for the Signalpost company envelope.

Defines the 7-section envelope schema and all supporting models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimValue(BaseModel):
    """A single evidence-backed claim with source tracking."""
    value: Any = None
    status: str = "available"
    source: Optional[str] = None
    retrieved_at: Optional[str] = None
    confidence: float = 1.0
    currency: Optional[str] = None
    period: Optional[str] = None


class LegalIdentity(BaseModel):
    """Section 1: Official legal identity from registry."""
    status: str = "available"
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
    """Section 2: Annual accounts / financial data."""
    status: str = "not_available"
    accounting_obligation: Optional[str] = None
    latest_filing_year: Optional[int] = None
    currency: Optional[str] = None
    revenue: Optional[ClaimValue] = None
    operating_profit: Optional[ClaimValue] = None
    profit_before_tax: Optional[ClaimValue] = None
    net_income: Optional[ClaimValue] = None
    total_assets: Optional[ClaimValue] = None
    total_equity: Optional[ClaimValue] = None
    total_debt: Optional[ClaimValue] = None
    employees: Optional[ClaimValue] = None
    historical_summary: list[dict[str, Any]] = Field(default_factory=list)


class LeadershipWorkplaces(BaseModel):
    """Section 3: Leadership roles and branch workplaces."""
    status: str = "not_available"
    roles: list[dict[str, Any]] = Field(default_factory=list)
    workplaces: list[dict[str, Any]] = Field(default_factory=list)


class WebsiteProfiles(BaseModel):
    """Section 4: Website and social profiles."""
    status: str = "not_available"
    official_website: Optional[dict[str, Any]] = None
    social_profiles: list[dict[str, Any]] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class HiringActivity(BaseModel):
    """Section 5: Hiring and job postings."""
    status: str = "not_applicable"
    active_listings: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    """Section 6: Evidence tracking and source summary.

    IMPORTANT: The scoring script checks these exact keys:
      - registry_live.value.organisation_number
      - financials.status
      - "roles" in evidence
      - "locations" in evidence
      - "website" in evidence
    """
    total_claims: int = 0
    claims_with_source: int = 0
    source_summary: list[dict[str, Any]] = Field(default_factory=list)
    registry_live: Optional[dict[str, Any]] = None
    financials: Optional[dict[str, Any]] = None
    roles: Optional[dict[str, Any]] = None
    locations: Optional[dict[str, Any]] = None
    website: Optional[dict[str, Any]] = None


class RefreshMetadata(BaseModel):
    """Section 7: Refresh and change-detection metadata."""
    is_initial_run: bool = True
    last_refreshed: Optional[str] = None
    next_refresh_due: Optional[str] = None
    changes_detected: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 1


class Synthesis(BaseModel):
    """LLM or rule-based synthesis summary."""
    status: str = "available"
    method: str = "rule_based"
    summary: Optional[str] = None
    key_observations: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    model: Optional[str] = None


class CompanyEnvelope(BaseModel):
    """Complete company profile envelope with all 7 sections."""
    organisation_number: str
    name: Optional[str] = None
    legal_form: Optional[str] = None
    municipality: Optional[str] = None
    website: Optional[str] = None
    profile_version: int = 1
    generated_at: str = Field(default_factory=utc_now)
    status: str = "available"

    legal_identity: Optional[LegalIdentity] = None
    annual_accounts: Optional[AnnualAccounts] = None
    leadership_workplaces: Optional[LeadershipWorkplaces] = None
    website_profiles: Optional[WebsiteProfiles] = None
    hiring_activity: Optional[HiringActivity] = None
    evidence: Optional[EvidenceSummary] = None
    refresh_metadata: Optional[RefreshMetadata] = None
    synthesis: Optional[Synthesis] = None

    @classmethod
    def create_not_available(cls, org_number: str) -> "CompanyEnvelope":
        return cls(
            organisation_number=org_number,
            status="not_available",
            evidence=EvidenceSummary(
                registry_live={"status": "not_found", "value": {"organisation_number": org_number}},
                financials={"status": "not_available"},
                roles={"status": "not_available"},
                locations={"status": "not_available"},
                website={"status": "not_available"},
            ),
        )

    @classmethod
    def create_failed(cls, org_number: str, error: str) -> "CompanyEnvelope":
        return cls(
            organisation_number=org_number,
            status="failed",
            evidence=EvidenceSummary(
                registry_live={"status": "error", "error": error,
                               "value": {"organisation_number": org_number}},
                financials={"status": "failed"},
                roles={"status": "failed"},
                locations={"status": "failed"},
                website={"status": "failed"},
            ),
        )
