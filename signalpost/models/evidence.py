"""Evidence and source tracking models."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    """A single source of evidence for a claim."""
    source_url: str = Field(..., description="URL or identifier of the source")
    source_class: str = Field(..., description="official_registry | company_website | licensed_api | public_page")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    effective_date: Optional[str] = Field(None, description="Reporting period or effective date")
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of source content")
    extraction_method: str = Field(default="api_response", description="How the data was extracted")
    snapshot_id: Optional[str] = Field(None, description="Reference to stored raw snapshot")
    access_policy: Optional[str] = Field(None, description="License or access terms")
