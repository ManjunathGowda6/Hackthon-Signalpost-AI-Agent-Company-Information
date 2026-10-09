"""Claim models - individual facts with evidence."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

from signalpost.models.evidence import EvidenceSource
from signalpost.models.availability import AvailabilityState


class Claim(BaseModel):
    """A single fact/claim about a company with evidence."""
    field_name: str = Field(..., description="Name of the data field")
    value: Any = Field(..., description="The claim value")
    status: AvailabilityState = Field(default=AvailabilityState.AVAILABLE)
    source: Optional[EvidenceSource] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    reporting_period: Optional[str] = Field(None, description="e.g. '2025' for annual accounts")

    class Config:
        use_enum_values = True
