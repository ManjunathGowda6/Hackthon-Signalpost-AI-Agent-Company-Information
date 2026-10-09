"""Financial data models for annual accounts."""
from typing import Optional
from pydantic import BaseModel, Field


class FinancialYear(BaseModel):
    """Financial data for a single year."""
    year: int
    revenue: Optional[float] = None
    operating_profit: Optional[float] = None
    net_income: Optional[float] = None
    total_assets: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None
    employees: Optional[int] = None
    currency: str = "NOK"
    source: Optional[str] = None
    retrieved_at: Optional[str] = None


class FinancialHistory(BaseModel):
    """Collection of financial data across years."""
    years: list[FinancialYear] = Field(default_factory=list)

    @property
    def latest(self) -> Optional[FinancialYear]:
        if not self.years:
            return None
        return max(self.years, key=lambda y: y.year)
