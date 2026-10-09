"""Refresh and diff tracking models."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class FieldChange(BaseModel):
    """A single field change between profile versions."""
    field_path: str
    previous_value: Any = None
    current_value: Any = None
    change_type: str = Field(..., description="added | modified | removed")
    is_material: bool = False
    previous_source: Optional[str] = None
    current_source: Optional[str] = None
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class RefreshResult(BaseModel):
    """Result of a profile refresh operation."""
    organisation_number: str
    previous_version: int
    current_version: int
    changes: list[FieldChange] = Field(default_factory=list)
    material_changes_count: int = 0
    refreshed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    @property
    def has_material_changes(self) -> bool:
        return any(c.is_material for c in self.changes)
