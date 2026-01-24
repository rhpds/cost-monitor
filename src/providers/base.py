"""
Abstract base provider class for multi-cloud cost monitoring.

Defines the interface that all cloud provider implementations must follow.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


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


class CostDataPoint(BaseModel):
    """Represents a single cost data point with comprehensive validation."""

    date: datetime | date
    amount: float
    currency: str
    service_name: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    region: str | None = None
    resource_id: str | None = None
    tags: dict[str, str] | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate and normalize currency code."""
        if not v or not v.strip():
            raise ValueError("Currency must be specified")

        normalized = v.upper().strip()

        # Common ISO 4217 currency codes for validation
        valid_currencies = {
            "USD",
            "EUR",
            "GBP",
            "JPY",
            "AUD",
            "CAD",
            "CHF",
            "CNY",
            "SEK",
            "NZD",
            "MXN",
            "SGD",
            "HKD",
            "NOK",
            "ZAR",
            "BRL",
        }

        if normalized not in valid_currencies:
            # Allow any 3-letter code but warn about unknown currencies
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown currency code: {normalized}")

        return normalized

    @field_validator("service_name", "account_name")
    @classmethod
    def validate_display_names(cls, v: str | None) -> str | None:
        """Validate and normalize display names."""
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Validate tags dictionary."""
        if v is None:
            return v

        # Validate tag keys and values
        validated_tags = {}
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(
                    f"Tags must be string key-value pairs, got {type(key)}: {type(value)}"
                )

            # Normalize whitespace
            clean_key = key.strip()
            clean_value = value.strip()

            if clean_key:  # Skip empty keys
                validated_tags[clean_key] = clean_value

        return validated_tags if validated_tags else None

    @model_validator(mode="after")
    def validate_cost_data_point(self):
        """Validate the complete cost data point."""
        # Check for future dates
        today = date.today()
        point_date = self.date.date() if isinstance(self.date, datetime) else self.date

        if point_date > today:
            raise ValueError(f"Cost data point date {point_date} cannot be in the future")

        # Validate amount range (prevent extreme values)
        if abs(self.amount) > 1e12:  # 1 trillion
            raise ValueError(f"Cost amount {self.amount} exceeds reasonable limits")

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class CostSummary(BaseModel):
    """Summary of costs for a time period with comprehensive validation."""

    provider: str
    start_date: datetime | date
    end_date: datetime | date
    total_cost: float
    currency: str
    data_points: list[CostDataPoint]
    granularity: TimeGranularity
    last_updated: datetime

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate and normalize currency code."""
        if not v or not v.strip():
            raise ValueError("Currency must be specified")
        return v.upper().strip()

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate and normalize provider name."""
        normalized = v.lower().strip()
        valid_providers = {"aws", "azure", "gcp", "all"}

        if normalized not in valid_providers:
            raise ValueError(
                f'Invalid provider "{v}". Must be one of: {", ".join(sorted(valid_providers))}'
            )
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self):
        """Validate date range and data consistency."""
        # Convert dates for comparison
        start = self.start_date.date() if isinstance(self.start_date, datetime) else self.start_date
        end = self.end_date.date() if isinstance(self.end_date, datetime) else self.end_date

        # Validate date range
        if start >= end:
            raise ValueError(f"Start date {start} must be before end date {end}")

        # Check for reasonable time ranges (not more than 10 years)
        if (end - start).days > 3650:
            raise ValueError("Date range cannot exceed 10 years")

        # Validate that last_updated is not in the future
        if self.last_updated > datetime.now():
            raise ValueError("Last updated timestamp cannot be in the future")

        # Validate data point consistency
        if self.data_points:
            # Check that all data points use the same currency
            currencies = {point.currency for point in self.data_points}
            if len(currencies) > 1:
                raise ValueError(f"Mixed currencies in data points: {currencies}")

            primary_currency = next(iter(currencies))
            if primary_currency != self.currency:
                raise ValueError(
                    f"Summary currency {self.currency} doesn't match data points currency {primary_currency}"
                )

            # Verify total cost calculation (allow small floating point differences)
            calculated_total = sum(point.amount for point in self.data_points)
            tolerance = abs(self.total_cost) * 0.01  # 1% tolerance
            if abs(calculated_total - self.total_cost) > max(tolerance, 0.01):
                raise ValueError(
                    f"Total cost {self.total_cost} doesn't match sum of data points {calculated_total:.2f}"
                )

        return self

    @property
    def daily_average(self) -> float:
        """Calculate daily average cost."""
        if not self.data_points:
            return 0.0

        start = self.start_date.date() if isinstance(self.start_date, datetime) else self.start_date
        end = self.end_date.date() if isinstance(self.end_date, datetime) else self.end_date
        days = (end - start).days + 1

        return self.total_cost / max(days, 1)

    @property
    def service_breakdown(self) -> dict[str, float]:
        """Get cost breakdown by service."""
        breakdown = {}
        for point in self.data_points:
            service = point.service_name or "Unknown"
            breakdown[service] = breakdown.get(service, 0.0) + point.amount
        return breakdown

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class CloudProviderError(Exception):
    """Base exception for cloud provider errors."""

    pass


class AuthenticationError(CloudProviderError):
    """Authentication-related errors."""

    pass


class APIError(CloudProviderError):
    """API-related errors."""

    def __init__(self, message: str, status_code: int | None = None, provider: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class RateLimitError(APIError):
    """Rate limiting errors."""

    def __init__(self, message: str, retry_after: int | None = None, provider: str | None = None):
        super().__init__(message, status_code=429, provider=provider)
        self.retry_after = retry_after


class ConfigurationError(CloudProviderError):
    """Configuration-related errors."""

    pass


class CloudCostProvider(ABC):
    """Abstract base class for cloud cost providers."""

    def __init__(self, config: dict[str, Any]):
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
        start_date: datetime | date,
        end_date: datetime | date,
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: list[str] | None = None,
        filter_by: dict[str, Any] | None = None,
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
        self, start_date: datetime | date, end_date: datetime | date
    ) -> list[CostDataPoint]:
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
        self, start_date: datetime | date, end_date: datetime | date, top_n: int = 10
    ) -> dict[str, float]:
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
    def get_supported_regions(self) -> list[str]:
        """
        Get list of supported regions for this provider.

        Returns:
            List of region identifiers
        """
        pass

    @abstractmethod
    def get_supported_services(self) -> list[str]:
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
        self, start_date: datetime | date, end_date: datetime | date
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
        start_date_for_comparison = (
            start_date.date() if isinstance(start_date, datetime) else start_date
        )
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

    async def health_check(self) -> dict[str, Any]:
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
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "provider": self.provider_name,
                "authenticated": False,
                "connection": False,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }


class ProviderFactory:
    """Factory class for creating cloud provider instances."""

    _providers = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        """Register a provider class with the factory."""
        cls._providers[name.lower()] = provider_class

    @classmethod
    def create_provider(cls, name: str, config: dict[str, Any]) -> CloudCostProvider:
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
    def get_available_providers(cls) -> list[str]:
        """Get list of available provider names."""
        return list(cls._providers.keys())
