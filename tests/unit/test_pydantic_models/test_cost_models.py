"""
Tests for core cost data Pydantic models.

Tests CostDataPoint and CostSummary models including validation,
field constraints, and business logic methods.
"""

from datetime import date, datetime, timedelta

import pytest

from src.providers.base import CostDataPoint, CostSummary, TimeGranularity


class TestCostDataPoint:
    """Test cases for CostDataPoint Pydantic model."""

    def test_create_valid_cost_data_point(self, sample_cost_data_point):
        """Test creating a valid CostDataPoint with all fields."""
        point = sample_cost_data_point

        assert point.date == date(2024, 1, 15)
        assert point.amount == 125.50
        assert point.currency == "USD"
        assert point.service_name == "Amazon EC2"
        assert point.account_id == "123456789012"
        assert point.account_name == "Production Account"
        assert point.region == "us-east-1"
        assert point.resource_id == "i-1234567890abcdef0"
        assert point.tags == {"Environment": "Production", "Team": "Backend"}

    def test_create_minimal_cost_data_point(self):
        """Test creating CostDataPoint with minimal required fields."""
        point = CostDataPoint(date=date.today(), amount=50.0, currency="USD")

        assert point.date == date.today()
        assert point.amount == 50.0
        assert point.currency == "USD"
        assert point.service_name is None
        assert point.account_id is None
        assert point.tags is None

    def test_currency_normalization(self):
        """Test that currency codes are normalized to uppercase."""
        point = CostDataPoint(date=date.today(), amount=100.0, currency="usd")  # lowercase

        assert point.currency == "USD"

    def test_negative_amount_allowed(self):
        """Test that negative amounts are allowed (for credits/refunds)."""
        point = CostDataPoint(
            date=date.today(), amount=-25.50, currency="USD"  # Negative for credit
        )

        assert point.amount == -25.50

    def test_zero_amount_allowed(self):
        """Test that zero amounts are allowed."""
        point = CostDataPoint(date=date.today(), amount=0.0, currency="USD")

        assert point.amount == 0.0

    def test_future_date_validation(self):
        """Test that future dates are rejected."""
        future_date = date.today() + timedelta(days=30)

        with pytest.raises(ValueError, match="cannot be in the future"):
            CostDataPoint(date=future_date, amount=100.0, currency="USD")

    def test_invalid_currency_code(self):
        """Test validation of currency codes."""
        # Test empty currency
        with pytest.raises(ValueError, match="Currency must be specified"):
            CostDataPoint(date=date.today(), amount=100.0, currency="")

        # Test unknown currency code (should warn but not fail)
        point = CostDataPoint(
            date=date.today(), amount=100.0, currency="TOOLONG"  # Unknown currency
        )
        assert point.currency == "TOOLONG"

    def test_model_serialization(self):
        """Test that model can be serialized to dict."""
        point = CostDataPoint(
            date=date(2024, 1, 15), amount=125.50, currency="USD", service_name="Amazon EC2"
        )

        data = point.model_dump()

        assert data["date"] == date(2024, 1, 15)
        assert data["amount"] == 125.50
        assert data["currency"] == "USD"
        assert data["service_name"] == "Amazon EC2"

    def test_model_json_serialization(self):
        """Test JSON serialization with proper date handling."""
        point = CostDataPoint(date=date(2024, 1, 15), amount=125.50, currency="USD")

        json_str = point.model_dump_json()
        assert "2024-01-15" in json_str
        assert "125.5" in json_str

    @pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "JPY"])
    def test_common_currency_codes(self, currency):
        """Test various common currency codes."""
        point = CostDataPoint(date=date.today(), amount=100.0, currency=currency)

        assert point.currency == currency

    def test_large_amount_precision(self):
        """Test handling of large amounts with decimal precision."""
        large_amount = 999999.99
        point = CostDataPoint(date=date.today(), amount=large_amount, currency="USD")

        assert point.amount == large_amount

    def test_tags_validation(self):
        """Test tags field validation."""
        # Valid tags
        point = CostDataPoint(
            date=date.today(),
            amount=100.0,
            currency="USD",
            tags={"Environment": "Production", "Team": "Backend"},
        )

        assert point.tags["Environment"] == "Production"
        assert point.tags["Team"] == "Backend"

    def test_empty_tags(self):
        """Test empty tags dictionary."""
        point = CostDataPoint(date=date.today(), amount=100.0, currency="USD", tags={})

        assert point.tags is None  # Empty dict becomes None


class TestCostSummary:
    """Test cases for CostSummary Pydantic model."""

    def test_create_valid_cost_summary(self, sample_cost_summary):
        """Test creating a valid CostSummary with all fields."""
        summary = sample_cost_summary

        assert summary.provider == "aws"
        assert summary.start_date == date(2024, 1, 1)
        assert summary.end_date == date(2024, 1, 31)
        assert summary.total_cost == 3875.25
        assert summary.currency == "USD"
        assert len(summary.data_points) == 1
        assert summary.granularity == TimeGranularity.DAILY

    def test_provider_validation(self):
        """Test that provider field validates against known providers."""
        # Valid providers
        for provider in ["aws", "azure", "gcp"]:
            summary = CostSummary(
                provider=provider,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                total_cost=100.0,
                currency="USD",
                data_points=[],
                granularity=TimeGranularity.DAILY,
                last_updated=datetime.now(),
            )
            assert summary.provider == provider

        # Invalid provider
        with pytest.raises(ValueError, match="Provider must be one of"):
            CostSummary(
                provider="invalid",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                total_cost=100.0,
                currency="USD",
                data_points=[],
                granularity=TimeGranularity.DAILY,
                last_updated=datetime.now(),
            )

    def test_date_range_validation(self):
        """Test that end_date must be after start_date."""
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            CostSummary(
                provider="aws",
                start_date=date(2024, 1, 31),
                end_date=date(2024, 1, 1),  # Before start_date
                total_cost=100.0,
                currency="USD",
                data_points=[],
                granularity=TimeGranularity.DAILY,
                last_updated=datetime.now(),
            )

    def test_negative_total_cost_rejected(self):
        """Test that negative total costs are rejected."""
        with pytest.raises(ValueError, match="Total cost cannot be negative"):
            CostSummary(
                provider="aws",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                total_cost=-100.0,  # Negative total
                currency="USD",
                data_points=[],
                granularity=TimeGranularity.DAILY,
                last_updated=datetime.now(),
            )

    def test_daily_average_property(self):
        """Test the daily_average computed property."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),  # 10 days
            total_cost=1000.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert summary.daily_average == 100.0  # 1000 / 10

    def test_service_breakdown_property(self, sample_cost_data_point):
        """Test the service_breakdown computed property."""
        # Create multiple data points with different services
        ec2_point = CostDataPoint(
            date=date.today(), amount=100.0, currency="USD", service_name="Amazon EC2"
        )

        s3_point = CostDataPoint(
            date=date.today(), amount=50.0, currency="USD", service_name="Amazon S3"
        )

        summary = CostSummary(
            provider="aws",
            start_date=date.today(),
            end_date=date.today(),
            total_cost=150.0,
            currency="USD",
            data_points=[ec2_point, s3_point],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        breakdown = summary.service_breakdown
        assert breakdown["Amazon EC2"] == 100.0
        assert breakdown["Amazon S3"] == 50.0

    def test_empty_data_points(self):
        """Test CostSummary with empty data points list."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_cost=0.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert len(summary.data_points) == 0
        assert summary.total_cost == 0.0
        assert summary.service_breakdown == {}

    def test_granularity_enum_values(self):
        """Test all TimeGranularity enum values."""
        for granularity in [TimeGranularity.DAILY, TimeGranularity.MONTHLY, TimeGranularity.YEARLY]:
            summary = CostSummary(
                provider="aws",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                total_cost=100.0,
                currency="USD",
                data_points=[],
                granularity=granularity,
                last_updated=datetime.now(),
            )
            assert summary.granularity == granularity

    def test_model_serialization_with_nested_objects(self, sample_cost_data_point):
        """Test serialization of CostSummary with nested CostDataPoint objects."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_cost=125.50,
            currency="USD",
            data_points=[sample_cost_data_point],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        data = summary.model_dump()

        assert data["provider"] == "aws"
        assert len(data["data_points"]) == 1
        assert data["data_points"][0]["amount"] == 125.50

    def test_currency_consistency_validation(self):
        """Test that data points currency matches summary currency."""
        point_with_different_currency = CostDataPoint(
            date=date.today(), amount=100.0, currency="EUR"  # Different from summary
        )

        # Note: This test assumes there's validation for currency consistency
        # If not implemented yet, this test documents the expected behavior
        summary = CostSummary(
            provider="aws",
            start_date=date.today(),
            end_date=date.today(),
            total_cost=100.0,
            currency="USD",
            data_points=[point_with_different_currency],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        # For now, just verify it creates successfully
        # Future enhancement: add currency consistency validation
        assert summary.currency == "USD"
        assert summary.data_points[0].currency == "EUR"

    @pytest.mark.parametrize(
        "total_cost,expected_daily",
        [
            (0.0, 0.0),
            (30.0, 1.0),  # 30 days
            (93.0, 3.0),  # 31 days
            (1000.0, 100.0),  # 10 days in test range
        ],
    )
    def test_daily_average_calculations(self, total_cost, expected_daily):
        """Test daily average calculations for various scenarios."""
        if expected_daily == 100.0:  # Special case for 10-day range
            start_date = date(2024, 1, 1)
            end_date = date(2024, 1, 10)
        elif expected_daily == 3.0:  # 31-day month
            start_date = date(2024, 1, 1)
            end_date = date(2024, 1, 31)
        elif expected_daily == 1.0:  # 30-day month
            start_date = date(2024, 4, 1)
            end_date = date(2024, 4, 30)
        else:  # Single day
            start_date = date(2024, 1, 1)
            end_date = date(2024, 1, 1)

        summary = CostSummary(
            provider="aws",
            start_date=start_date,
            end_date=end_date,
            total_cost=total_cost,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert summary.daily_average == expected_daily
