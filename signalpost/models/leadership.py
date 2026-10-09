"""Leadership and organizational role models."""
from typing import Optional
from pydantic import BaseModel, Field


class PersonRole(BaseModel):
    """A person holding a role in the company."""
    role_type: str = Field(..., description="e.g. Daglig leder, Styreleder, Styremedlem")
    person_name: str
    birth_year: Optional[int] = None
    source: Optional[str] = None
    retrieved_at: Optional[str] = None


class BoardComposition(BaseModel):
    """Board of directors composition."""
    chair: Optional[PersonRole] = None
    members: list[PersonRole] = Field(default_factory=list)
    source: Optional[str] = None
