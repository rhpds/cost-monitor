"""
API data models for cost monitoring.

Contains Pydantic models used across the API layer.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class DailyCostSummary(BaseModel):
    date: str
    total_cost: float
    currency: str
    provider_breakdown: dict[str, float]


class ProviderData(BaseModel):
    total_cost: float
    currency: str
    service_breakdown: dict[str, float]


class AccountData(BaseModel):
    account_id: str
    account_name: str
    cost: float
    currency: str


class CostSummary(BaseModel):
    total_cost: float
    currency: str
    period_start: date
    period_end: date
    provider_breakdown: dict[str, float]
    combined_daily_costs: list[DailyCostSummary]
    provider_data: dict[str, ProviderData]
    account_breakdown: dict[str, list[AccountData]]
    data_collection_complete: bool
    last_updated: datetime
    data_freshness: str | None = None
    background_refresh_triggered: bool | None = None
    refresh_status: str | None = None
    freshness_metadata: dict[str, Any] | None = None


class HealthCheck(BaseModel):
    status: str
    timestamp: datetime
    version: str


class CostDataPoint(BaseModel):
    provider: str
    date: date
    cost: float
    currency: str
    service_name: str | None = None
    account_id: str | None = None
    region: str | None = None
