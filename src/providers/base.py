"""
Abstract base provider class for multi-cloud cost monitoring.

Defines the interface that all cloud provider implementations must follow.
"""

from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum


class TimeGranularity(Enum):
    """Supported time granularities for cost queries."""
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class CostMetricType(Enum):
    """Types of cost metrics available."""
    BLENDED_COST = "blended_cost"
    UNBLENDED_COST = "unblended_cost"
    NET_COST = "net_cost"
    AMORTIZED_COST = "amortized_cost"


@dataclass
class CostDataPoint:
    """Represents a single cost data point."""
    date: Union[datetime, date]
    amount: float
    currency: str
    service_name: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    region: Optional[str] = None
    resource_id: Optional[str] = None
    tags: Optional[Dict[str, str]] = None

    def __post_init__(self):
        """Validate cost data point after initialization."""
        # Note: Negative amounts are allowed (credits, refunds, adjustments)
        if not self.currency:
            raise ValueError("Currency must be specified")


@dataclass
class CostSummary:
    """Summary of costs for a time period."""
    provider: str
    start_date: Union[datetime, date]
    end_date: Union[datetime, date]
    total_cost: float
    currency: str
    data_points: List[CostDataPoint]
    granularity: TimeGranularity
    last_updated: datetime

    @property
    def daily_average(self) -> float:
        """Calculate daily average cost."""
        if not self.data_points:
            return 0.0
        days = (self.end_date - self.start_date).days + 1
        return self.total_cost / max(days, 1)

    @property
    def service_breakdown(self) -> Dict[str, float]:
        """Get cost breakdown by service."""
        breakdown = {}
        for point in self.data_points:
            service = point.service_name or "Unknown"
            breakdown[service] = breakdown.get(service, 0.0) + point.amount
        return breakdown


class CloudProviderError(Exception):
    """Base exception for cloud provider errors."""
    pass


class AuthenticationError(CloudProviderError):
    """Authentication-related errors."""
    pass


class APIError(CloudProviderError):
    """API-related errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, provider: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class RateLimitError(APIError):
    """Rate limiting errors."""
    def __init__(self, message: str, retry_after: Optional[int] = None, provider: Optional[str] = None):
        super().__init__(message, status_code=429, provider=provider)
        self.retry_after = retry_after


class ConfigurationError(CloudProviderError):
    """Configuration-related errors."""
    pass


class CloudCostProvider(ABC):
    """Abstract base class for cloud cost providers."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the cloud provider with configuration.

        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self.provider_name = self._get_provider_name()
        self._authenticated = False

    @abstractmethod
    def _get_provider_name(self) -> str:
        """Return the provider name (aws, azure, gcp)."""
        pass

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the cloud provider.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test the connection to the cloud provider's billing API.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_cost_data(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """
        Retrieve cost data for the specified time period.

        Args:
            start_date: Start date for cost data
            end_date: End date for cost data
            granularity: Time granularity for the data
            group_by: Optional list of dimensions to group by
            filter_by: Optional filters to apply

        Returns:
            CostSummary object containing cost data

        Raises:
            APIError: If API call fails
            ConfigurationError: If provider not configured
        """
        pass

    @abstractmethod
    async def get_current_month_cost(self) -> float:
        """
        Get the current month's total cost.

        Returns:
            Total cost for current month

        Raises:
            APIError: If API call fails
        """
        pass

    @abstractmethod
    async def get_daily_costs(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date]
    ) -> List[CostDataPoint]:
        """
        Get daily cost breakdown for the specified period.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of daily cost data points
        """
        pass

    @abstractmethod
    async def get_service_costs(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        top_n: int = 10
    ) -> Dict[str, float]:
        """
        Get cost breakdown by service for the specified period.

        Args:
            start_date: Start date
            end_date: End date
            top_n: Number of top services to return

        Returns:
            Dictionary mapping service names to costs
        """
        pass

    @abstractmethod
    def get_supported_regions(self) -> List[str]:
        """
        Get list of supported regions for this provider.

        Returns:
            List of region identifiers
        """
        pass

    @abstractmethod
    def get_supported_services(self) -> List[str]:
        """
        Get list of supported services for cost monitoring.

        Returns:
            List of service identifiers
        """
        pass

    async def is_authenticated(self) -> bool:
        """Check if the provider is authenticated."""
        return self._authenticated

    async def ensure_authenticated(self):
        """Ensure the provider is authenticated, authenticate if not."""
        if not self._authenticated:
            await self.authenticate()

    def normalize_service_name(self, service_name: str) -> str:
        """
        Normalize service names to a common format.

        Args:
            service_name: Original service name

        Returns:
            Normalized service name
        """
        # Default implementation - override in provider classes
        return service_name.strip().title()

    def validate_date_range(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date]
    ) -> tuple[datetime, datetime]:
        """
        Validate and normalize date range.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Tuple of normalized datetime objects

        Raises:
            ValueError: If date range is invalid
        """
        # Convert dates to datetime if needed
        if isinstance(start_date, date) and not isinstance(start_date, datetime):
            start_date = datetime.combine(start_date, datetime.min.time())
        if isinstance(end_date, date) and not isinstance(end_date, datetime):
            end_date = datetime.combine(end_date, datetime.max.time())

        # Handle single-day queries - AWS and other providers require start < end
        if start_date.date() == end_date.date():
            # For same-day queries, extend end date to next day to satisfy API requirements
            from datetime import timedelta
            end_date = datetime.combine(end_date.date() + timedelta(days=1), datetime.min.time())

        # Validate range
        if start_date >= end_date:
            raise ValueError("Start date must be before end date")

        # Check if dates are too far in the future
        now = datetime.now()
        # Convert start_date to date object for comparison if it's a datetime
        start_date_for_comparison = start_date.date() if isinstance(start_date, datetime) else start_date
        if start_date_for_comparison > now.date():
            raise ValueError("Start date cannot be in the future")

        return start_date, end_date

    def format_currency(self, amount: float, currency: str = "USD") -> str:
        """
        Format currency amount for display.

        Args:
            amount: Amount to format
            currency: Currency code

        Returns:
            Formatted currency string
        """
        if currency.upper() == "USD":
            return f"${amount:.2f}"
        else:
            return f"{amount:.2f} {currency}"

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check of the provider.

        Returns:
            Dictionary with health check results
        """
        try:
            await self.ensure_authenticated()
            connection_ok = await self.test_connection()

            return {
                "provider": self.provider_name,
                "authenticated": self._authenticated,
                "connection": connection_ok,
                "status": "healthy" if (self._authenticated and connection_ok) else "unhealthy",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "provider": self.provider_name,
                "authenticated": False,
                "connection": False,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


class ProviderFactory:
    """Factory class for creating cloud provider instances."""

    _providers = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        """Register a provider class with the factory."""
        cls._providers[name.lower()] = provider_class

    @classmethod
    def create_provider(cls, name: str, config: Dict[str, Any]) -> CloudCostProvider:
        """
        Create a provider instance.

        Args:
            name: Provider name (aws, azure, gcp)
            config: Provider configuration

        Returns:
            Provider instance

        Raises:
            ValueError: If provider not found
        """
        name = name.lower()
        if name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(f"Unknown provider '{name}'. Available providers: {available}")

        provider_class = cls._providers[name]
        return provider_class(config)

    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available provider names."""
        return list(cls._providers.keys())