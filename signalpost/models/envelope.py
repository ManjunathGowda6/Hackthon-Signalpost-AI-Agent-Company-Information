"""Company profile envelope schema (7 required sections)."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

class ClaimValue(BaseModel):
    value: Any = None
    status: str = "available"
    source: Optional[str] = None
    retrieved_at: Optional[str] = None
    confidence: float = 1.0

class LegalIdentity(BaseModel):
    status: str = "not_available"
    legal_name: Optional[ClaimValue] = None
    legal_form: Optional[ClaimValue] = None
    registered_address: Optional[ClaimValue] = None
    industry_codes: list[dict] = Field(default_factory=list)
    registration_date: Optional[ClaimValue] = None
    registration_status: Optional[ClaimValue] = None
    public_brand: Optional[ClaimValue] = None
    official_website: Optional[ClaimValue] = None

class AnnualAccounts(BaseModel):
    status: str = "not_available"
    latest_filing_year: Optional[int] = None
    revenue: Optional[ClaimValue] = None
    operating_profit: Optional[ClaimValue] = None
    total_assets: Optional[ClaimValue] = None
    employees: Optional[ClaimValue] = None
    history: list[dict] = Field(default_factory=list)

class LeadershipWorkplaces(BaseModel):
    status: str = "not_available"
    roles: list[dict] = Field(default_factory=list)
    workplaces: list[dict] = Field(default_factory=list)

class WebsiteProfiles(BaseModel):
    status: str = "not_available"
    official_website: Optional[dict] = None
    social_profiles: list[dict] = Field(default_factory=list)

class HiringActivity(BaseModel):
    status: str = "not_available"
    job_postings: list[dict] = Field(default_factory=list)
    public_activity: list[dict] = Field(default_factory=list)

class EvidenceSummary(BaseModel):
    total_claims: int = 0
    claims_with_source: int = 0
    source_summary: list[dict] = Field(default_factory=list)

class RefreshMetadata(BaseModel):
    is_initial_run: bool = True
    previous_version: Optional[int] = None
    material_changes: list[dict] = Field(default_factory=list)
    last_refreshed: Optional[str] = None

class Synthesis(BaseModel):
    company_summary: str = ""
    key_observations: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence_assessment: str = ""

class CompanyEnvelope(BaseModel):
    organisation_number: str
    profile_version: int = 1
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat()+"Z")
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
    def create_failed(cls, org_number, error):
        return cls(organisation_number=org_number, status="failed",
                   synthesis=Synthesis(company_summary=f"Research failed: {error}"))

    @classmethod
    def create_not_available(cls, org_number):
        return cls(organisation_number=org_number, status="not_available",
                   synthesis=Synthesis(company_summary="Entity not found in registry."))

    @classmethod
    def from_registry_data(cls, org_number, data):
        src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}"
        now = datetime.utcnow().isoformat()+"Z"
        addr = data.get("forretningsadresse") or data.get("postadresse") or {}
        nace = data.get("naeringskode1")
        li = LegalIdentity(
            status="available",
            legal_name=ClaimValue(value=data.get("navn"), source=src, retrieved_at=now),
            legal_form=ClaimValue(value=data.get("organisasjonsform",{}).get("kode"), source=src, retrieved_at=now),
            registered_address=ClaimValue(value={
                "street": " ".join(addr.get("adresse",[])),
                "postal_code": addr.get("postnummer"),
                "city": addr.get("poststed"), "country": addr.get("land","Norge")
            }, source=src, retrieved_at=now),
            industry_codes=[{"code":nace.get("kode"),"description":nace.get("beskrivelse"),"source":src}] if nace else [],
            registration_date=ClaimValue(value=data.get("registreringsdatoEnhetsregisteret"), source=src, retrieved_at=now),
            registration_status=ClaimValue(value="active" if not data.get("slettedato") else "deleted", source=src, retrieved_at=now),
        )
        return cls(organisation_number=org_number, status="available", legal_identity=li,
                   evidence=EvidenceSummary(total_claims=5, claims_with_source=5,
                                           source_summary=[{"source_class":"official_registry","claims":5}]),
                   refresh_metadata=RefreshMetadata(is_initial_run=True, last_refreshed=now))
