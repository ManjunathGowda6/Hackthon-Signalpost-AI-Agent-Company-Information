"""Availability states for company data fields."""
from enum import Enum


class AvailabilityState(str, Enum):
    """Explicit states for data availability - NEVER use zero for missing."""
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
