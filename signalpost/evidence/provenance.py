"""Source provenance tracking."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class Provenance(BaseModel):
    """Full provenance record for a data source."""
    source_url: str
    final_url: Optional[str] = None
    redirect_chain: list[str] = Field(default_factory=list)
    http_status: int = 200
    retrieved_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    content_hash: Optional[str] = None
    content_type: Optional[str] = None
    source_class: str = "unknown"
    access_policy: Optional[str] = None
    parser_version: str = "signalpost-1.0.0"
    snapshot_id: Optional[str] = None
