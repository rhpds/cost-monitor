"""
Tests for base provider functionality.

Tests the abstract CostProvider base class and common provider
functionality including authentication, validation, and data structures.
"""

from datetime import date, datetime

import pytest

from src.providers.base import CloudCostProvider, CostDataPoint, CostSummary, TimeGranularity


class MockCostProvider(CloudCostProvider):
    """Mock implementation of CloudCostProvider for testing."""

    def __init__(self, config=None):
        super().__init__(config or {})
        self.mock_authenticated = False
        self.mock_connection_result = True

    def _get_provider_name(self) -> str:
        """Return the provider name."""
        return "aws"  # Use valid provider name

    async def authenticate(self) -> bool:
        """Mock authentication."""
        self.mock_authenticated = True
        return True

    async def test_connection(self) -> bool:
        """Mock connection test."""
        return self.mock_connection_result

    async def get_cost_data(
        self, start_date: date, end_date: date, granularity: TimeGranularity = TimeGranularity.DAILY
    ) -> CostSummary:
        """Mock get_cost_data implementation."""
        return CostSummary(
            provider="aws",  # Use valid provider name
            start_date=start_date,
            end_date=end_date,
            total_cost=100.0,
            currency="USD",
            data_points=[],
            granularity=granularity,
            last_updated=datetime.now(),
        )

    async def get_current_month_cost(self) -> float:
        """Mock current month cost."""
        return 500.0

    async def get_daily_costs(self, start_date: date, end_date: date) -> list[CostDataPoint]:
        """Mock daily costs."""
        return [CostDataPoint(date=start_date, amount=50.0, currency="USD")]

    async def get_service_costs(
        self, start_date: date, end_date: date, top_n: int = 10
    ) -> dict[str, float]:
        """Mock service costs."""
        return {"Service A": 60.0, "Service B": 40.0}

    def get_supported_regions(self) -> list[str]:
        """Mock supported regions."""
        return ["us-east-1", "us-west-2"]

    def get_supported_services(self) -> list[str]:
        """Mock supported services."""
        return ["Service A", "Service B", "Service C"]


class TestCloudCostProvider:
    """Test cases for CloudCostProvider base class."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock provider for testing."""
        return MockCostProvider()

    def test_provider_initialization(self, mock_provider):
        """Test provider initialization with config."""
        assert mock_provider.config == {}

    def test_provider_initialization_with_config(self):
        """Test provider initialization with configuration."""
        config = {"enabled": True, "timeout": 30, "retry_attempts": 3}
        provider = MockCostProvider(config)
        assert provider.config == config

    async def test_authenticate_method(self, mock_provider):
        """Test authenticate method implementation."""
        result = await mock_provider.authenticate()
        assert result is True
        assert mock_provider.mock_authenticated is True

    async def test_test_connection_method(self, mock_provider):
        """Test test_connection method implementation."""
        result = await mock_provider.test_connection()
        assert result is True

        # Test connection failure
        mock_provider.mock_connection_result = False
        result = await mock_provider.test_connection()
        assert result is False

    async def test_get_cost_data_method(self, mock_provider):
        """Test get_cost_data method implementation."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7)

        result = await mock_provider.get_cost_data(start_date, end_date)

        assert isinstance(result, CostSummary)
        assert result.provider == "aws"
        assert result.start_date == start_date
        assert result.end_date == end_date
        assert result.total_cost == 100.0
        assert result.currency == "USD"

    async def test_get_cost_data_with_granularity(self, mock_provider):
        """Test get_cost_data with different granularity options."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)

        # Test daily granularity
        result = await mock_provider.get_cost_data(start_date, end_date, TimeGranularity.DAILY)
        assert result.granularity == TimeGranularity.DAILY

        # Test yearly granularity
        result = await mock_provider.get_cost_data(start_date, end_date, TimeGranularity.YEARLY)
        assert result.granularity == TimeGranularity.YEARLY

        # Test monthly granularity
        result = await mock_provider.get_cost_data(start_date, end_date, TimeGranularity.MONTHLY)
        assert result.granularity == TimeGranularity.MONTHLY


class TestTimeGranularity:
    """Test cases for TimeGranularity enum."""

    def test_time_granularity_values(self):
        """Test all TimeGranularity enum values."""
        assert TimeGranularity.DAILY.value == "daily"
        assert TimeGranularity.MONTHLY.value == "monthly"
        assert TimeGranularity.YEARLY.value == "yearly"

    def test_time_granularity_from_string(self):
        """Test creating TimeGranularity from string values."""
        assert TimeGranularity("daily") == TimeGranularity.DAILY
        assert TimeGranularity("monthly") == TimeGranularity.MONTHLY
        assert TimeGranularity("yearly") == TimeGranularity.YEARLY

    def test_time_granularity_comparison(self):
        """Test comparing TimeGranularity values."""
        daily = TimeGranularity.DAILY
        monthly = TimeGranularity.MONTHLY
        yearly = TimeGranularity.YEARLY

        assert daily == TimeGranularity.DAILY
        assert daily != monthly
        assert monthly != yearly

    @pytest.mark.parametrize(
        "granularity", [TimeGranularity.DAILY, TimeGranularity.MONTHLY, TimeGranularity.YEARLY]
    )
    def test_time_granularity_in_collection(self, granularity):
        """Test TimeGranularity enum values in collections."""
        granularities = [TimeGranularity.DAILY, TimeGranularity.MONTHLY, TimeGranularity.YEARLY]
        assert granularity in granularities


class TestCostDataPointIntegration:
    """Test CostDataPoint integration with provider workflows."""

    def test_cost_data_point_creation_from_provider_data(self):
        """Test creating CostDataPoint from typical provider data."""
        # Simulate AWS-style data
        point = CostDataPoint(
            date=date(2024, 1, 15),
            amount=125.50,
            currency="USD",
            service_name="Amazon EC2",
            account_id="123456789012",
            region="us-east-1",
            tags={"Environment": "Production"},
        )

        assert point.date == date(2024, 1, 15)
        assert point.service_name == "Amazon EC2"
        assert point.region == "us-east-1"

    def test_cost_data_point_with_negative_amount(self):
        """Test CostDataPoint with negative amounts (credits)."""
        credit_point = CostDataPoint(
            date=date(2024, 1, 15),
            amount=-25.00,  # Credit/refund
            currency="USD",
            service_name="AWS Credits",
        )

        assert credit_point.amount == -25.00

    def test_cost_data_point_aggregation(self):
        """Test aggregating multiple CostDataPoint objects."""
        points = [
            CostDataPoint(
                date=date(2024, 1, 1), amount=100.0, currency="USD", service_name="Service A"
            ),
            CostDataPoint(
                date=date(2024, 1, 1), amount=50.0, currency="USD", service_name="Service B"
            ),
            CostDataPoint(
                date=date(2024, 1, 1),
                amount=25.0,
                currency="USD",
                service_name="Service A",  # Same service, should aggregate
            ),
        ]

        # Test manual aggregation logic
        service_totals = {}
        for point in points:
            service_name = point.service_name or "Unknown"
            if service_name not in service_totals:
                service_totals[service_name] = 0.0
            service_totals[service_name] += point.amount

        assert service_totals["Service A"] == 125.0
        assert service_totals["Service B"] == 50.0


class TestCostSummaryIntegration:
    """Test CostSummary integration with provider workflows."""

    def test_cost_summary_with_multiple_data_points(self):
        """Test CostSummary containing multiple CostDataPoint objects."""
        data_points = [
            CostDataPoint(
                date=date(2024, 1, 1), amount=100.0, currency="USD", service_name="Service A"
            ),
            CostDataPoint(
                date=date(2024, 1, 2), amount=150.0, currency="USD", service_name="Service B"
            ),
            CostDataPoint(
                date=date(2024, 1, 3), amount=75.0, currency="USD", service_name="Service A"
            ),
        ]

        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            total_cost=325.0,
            currency="USD",
            data_points=data_points,
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert len(summary.data_points) == 3
        assert summary.total_cost == 325.0

        # Test service breakdown calculation
        breakdown = summary.service_breakdown
        assert breakdown["Service A"] == 175.0  # 100 + 75
        assert breakdown["Service B"] == 150.0

    def test_cost_summary_daily_average_calculation(self):
        """Test daily average calculation in CostSummary."""
        # Test 7-day period
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),  # 7 days
            total_cost=700.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert summary.daily_average == 100.0  # 700 / 7

        # Test single day
        summary_single = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),  # Same day
            total_cost=150.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert summary_single.daily_average == 150.0  # 150 / 1

    def test_cost_summary_empty_data_points(self):
        """Test CostSummary behavior with empty data points."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            total_cost=0.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert len(summary.data_points) == 0
        assert summary.service_breakdown == {}
        assert summary.daily_average == 0.0

    def test_cost_summary_serialization_compatibility(self):
        """Test CostSummary serialization for API responses."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            total_cost=456.78,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.WEEKLY,
            last_updated=datetime(2024, 1, 8, 10, 30, 0),
        )

        # Test model_dump for API serialization
        data = summary.model_dump()

        assert data["provider"] == "aws"
        assert data["total_cost"] == 456.78
        assert data["granularity"] == TimeGranularity.WEEKLY

        # Test JSON serialization
        json_data = summary.model_dump_json()
        assert "456.78" in json_data
        assert "aws" in json_data


class TestProviderErrorHandling:
    """Test error handling in provider base functionality."""

    async def test_provider_authentication_failure(self):
        """Test handling authentication failures."""

        class FailingProvider(MockCostProvider):
            async def authenticate(self) -> bool:
                raise Exception("Authentication failed")

        provider = FailingProvider()

        with pytest.raises(Exception, match="Authentication failed"):
            await provider.authenticate()

    async def test_provider_connection_failure(self):
        """Test handling connection failures."""

        class FailingConnectionProvider(MockCostProvider):
            async def test_connection(self) -> bool:
                raise Exception("Connection failed")

        provider = FailingConnectionProvider()

        with pytest.raises(Exception, match="Connection failed"):
            await provider.test_connection()

    async def test_provider_get_cost_data_failure(self):
        """Test handling get_cost_data failures."""

        class FailingCostsProvider(MockCostProvider):
            async def get_cost_data(
                self,
                start_date: date,
                end_date: date,
                granularity: TimeGranularity = TimeGranularity.DAILY,
            ) -> CostSummary:
                raise Exception("Failed to retrieve costs")

        provider = FailingCostsProvider()

        with pytest.raises(Exception, match="Failed to retrieve costs"):
            await provider.get_cost_data(date.today(), date.today())


class TestProviderConfigurationHandling:
    """Test provider configuration handling."""

    def test_provider_with_empty_config(self):
        """Test provider with empty configuration."""
        provider = MockCostProvider({})
        assert provider.config == {}

    def test_provider_with_none_config(self):
        """Test provider with None configuration."""
        provider = MockCostProvider(None)
        assert provider.config == {}

    def test_provider_with_complex_config(self):
        """Test provider with complex configuration."""
        config = {
            "enabled": True,
            "credentials": {
                "access_key": "test_key",
                "secret_key": "test_secret",
            },  # pragma: allowlist secret
            "regions": ["us-east-1", "us-west-2"],
            "timeout": 30,
            "retry_config": {"max_attempts": 3, "backoff_factor": 2.0},
        }

        provider = MockCostProvider(config)
        assert provider.config == config
        assert provider.config["credentials"]["access_key"] == "test_key"
        assert len(provider.config["regions"]) == 2
