"""
Tests for data processing Pydantic models.

Tests NormalizedCostData and MultiCloudCostSummary models including
validation, aggregation logic, and multi-cloud data processing.
"""

from datetime import date

import pytest

from src.providers.base import TimeGranularity
from src.utils.data_normalizer import MultiCloudCostSummary, NormalizedCostData


class TestNormalizedCostData:
    """Test cases for NormalizedCostData Pydantic model."""

    def test_create_valid_normalized_cost_data(self):
        """Test creating valid NormalizedCostData with all fields."""
        normalized = NormalizedCostData(
            provider="aws",
            total_cost=750.50,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown={"EC2": 400.0, "S3": 200.50, "RDS": 150.0},
            regional_breakdown={"us-east-1": 500.0, "us-west-2": 250.50},
            daily_costs=[
                {"date": "2024-01-01", "cost": 107.21},
                {"date": "2024-01-02", "cost": 105.43},
                {"date": "2024-01-03", "cost": 110.86},
            ],
        )

        assert normalized.provider == "aws"
        assert normalized.total_cost == 750.50
        assert normalized.currency == "USD"
        assert normalized.service_breakdown["EC2"] == 400.0
        assert normalized.regional_breakdown["us-east-1"] == 500.0
        assert len(normalized.daily_costs) == 3

    def test_provider_validation(self):
        """Test provider field validation."""
        # Valid providers
        for provider in ["aws", "azure", "gcp"]:
            normalized = NormalizedCostData(
                provider=provider,
                total_cost=100.0,
                currency="USD",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                granularity=TimeGranularity.DAILY,
            )
            assert normalized.provider == provider

        # Invalid provider
        with pytest.raises(ValueError, match="Provider must be one of"):
            NormalizedCostData(
                provider="invalid",
                total_cost=100.0,
                currency="USD",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                granularity=TimeGranularity.DAILY,
            )

    def test_negative_total_cost_rejected(self):
        """Test that negative total costs are rejected."""
        with pytest.raises(ValueError, match="Total cost cannot be negative"):
            NormalizedCostData(
                provider="aws",
                total_cost=-100.0,
                currency="USD",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                granularity=TimeGranularity.DAILY,
            )

    def test_date_range_validation(self):
        """Test date range validation."""
        # Valid date range
        normalized = NormalizedCostData(
            provider="aws",
            total_cost=100.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )
        assert normalized.start_date == date(2024, 1, 1)
        assert normalized.end_date == date(2024, 1, 7)

        # Invalid date range (end before start)
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            NormalizedCostData(
                provider="aws",
                total_cost=100.0,
                currency="USD",
                start_date=date(2024, 1, 7),
                end_date=date(2024, 1, 1),
                granularity=TimeGranularity.DAILY,
            )

    def test_service_breakdown_validation(self):
        """Test service breakdown validation."""
        # Valid service breakdown
        service_breakdown = {
            "Compute": 400.0,
            "Storage": 200.0,
            "Database": 150.0,
            "Networking": 50.0,
        }

        normalized = NormalizedCostData(
            provider="aws",
            total_cost=800.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown=service_breakdown,
        )

        assert normalized.service_breakdown == service_breakdown

        # Empty service breakdown should be allowed
        normalized_empty = NormalizedCostData(
            provider="aws",
            total_cost=100.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown={},
        )
        assert normalized_empty.service_breakdown == {}

    def test_regional_breakdown_validation(self):
        """Test regional breakdown validation."""
        regional_breakdown = {"us-east-1": 500.0, "us-west-2": 250.0, "eu-west-1": 100.0}

        normalized = NormalizedCostData(
            provider="aws",
            total_cost=850.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            regional_breakdown=regional_breakdown,
        )

        assert normalized.regional_breakdown["us-east-1"] == 500.0
        assert len(normalized.regional_breakdown) == 3

    def test_daily_costs_structure_validation(self):
        """Test daily costs list structure validation."""
        daily_costs = [
            {"date": "2024-01-01", "cost": 107.21},
            {"date": "2024-01-02", "cost": 105.43},
            {"date": "2024-01-03", "cost": 110.86},
        ]

        normalized = NormalizedCostData(
            provider="aws",
            total_cost=323.50,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            granularity=TimeGranularity.DAILY,
            daily_costs=daily_costs,
        )

        assert len(normalized.daily_costs) == 3
        assert normalized.daily_costs[0]["date"] == "2024-01-01"
        assert normalized.daily_costs[0]["cost"] == 107.21

    def test_currency_normalization(self):
        """Test currency code normalization."""
        normalized = NormalizedCostData(
            provider="aws",
            total_cost=100.0,
            currency="usd",  # lowercase
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )

        assert normalized.currency == "USD"  # Should be normalized to uppercase

    def test_minimal_required_fields(self):
        """Test creating NormalizedCostData with only required fields."""
        normalized = NormalizedCostData(
            provider="aws",
            total_cost=100.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )

        assert normalized.provider == "aws"
        assert normalized.total_cost == 100.0
        assert normalized.service_breakdown == {}  # Default empty
        assert normalized.regional_breakdown == {}  # Default empty
        assert normalized.daily_costs == []  # Default empty

    @pytest.mark.parametrize(
        "granularity", [TimeGranularity.DAILY, TimeGranularity.MONTHLY, TimeGranularity.YEARLY]
    )
    def test_all_granularity_types(self, granularity):
        """Test all supported granularity types."""
        normalized = NormalizedCostData(
            provider="aws",
            total_cost=100.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            granularity=granularity,
        )

        assert normalized.granularity == granularity

    def test_model_serialization(self):
        """Test model serialization to dict."""
        normalized = NormalizedCostData(
            provider="gcp",
            total_cost=456.78,
            currency="USD",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 21),
            granularity=TimeGranularity.MONTHLY,
            service_breakdown={"Compute Engine": 300.0, "Cloud Storage": 156.78},
        )

        data = normalized.model_dump()

        assert data["provider"] == "gcp"
        assert data["total_cost"] == 456.78
        assert data["service_breakdown"]["Compute Engine"] == 300.0


class TestMultiCloudCostSummary:
    """Test cases for MultiCloudCostSummary Pydantic model."""

    def test_create_valid_multi_cloud_summary(self):
        """Test creating valid MultiCloudCostSummary with all fields."""
        # Create sample normalized data
        aws_data = NormalizedCostData(
            provider="aws",
            total_cost=750.50,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )

        multi_cloud = MultiCloudCostSummary(
            total_cost=1500.75,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 750.50, "azure": 500.25, "gcp": 250.00},
            combined_service_breakdown={"Compute": 800.0, "Storage": 400.75, "Database": 300.0},
            provider_data={"aws": aws_data},
        )

        assert multi_cloud.total_cost == 1500.75
        assert multi_cloud.currency == "USD"
        assert multi_cloud.provider_breakdown["aws"] == 750.50
        assert multi_cloud.combined_service_breakdown["Compute"] == 800.0
        assert "aws" in multi_cloud.provider_data

    def test_negative_total_cost_rejected(self):
        """Test that negative total costs are rejected."""
        with pytest.raises(ValueError, match="Total cost cannot be negative"):
            MultiCloudCostSummary(
                total_cost=-1000.0,
                currency="USD",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                provider_breakdown={"aws": 500.0},
                combined_service_breakdown={"Compute": 500.0},
            )

    def test_date_range_validation(self):
        """Test date range validation."""
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            MultiCloudCostSummary(
                total_cost=1000.0,
                currency="USD",
                start_date=date(2024, 1, 7),
                end_date=date(2024, 1, 1),
                provider_breakdown={"aws": 1000.0},
                combined_service_breakdown={"Compute": 1000.0},
            )

    def test_provider_breakdown_validation(self):
        """Test provider breakdown validation."""
        provider_breakdown = {"aws": 600.0, "azure": 300.0, "gcp": 100.0}

        multi_cloud = MultiCloudCostSummary(
            total_cost=1000.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown=provider_breakdown,
            combined_service_breakdown={"Compute": 1000.0},
        )

        assert multi_cloud.provider_breakdown == provider_breakdown
        assert len(multi_cloud.provider_breakdown) == 3

        # Empty provider breakdown should be allowed
        multi_cloud_empty = MultiCloudCostSummary(
            total_cost=1000.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={},
            combined_service_breakdown={"Compute": 1000.0},
        )
        assert multi_cloud_empty.provider_breakdown == {}

    def test_combined_service_breakdown_validation(self):
        """Test combined service breakdown validation."""
        service_breakdown = {
            "Compute": 500.0,
            "Storage": 300.0,
            "Database": 150.0,
            "Networking": 50.0,
        }

        multi_cloud = MultiCloudCostSummary(
            total_cost=1000.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 1000.0},
            combined_service_breakdown=service_breakdown,
        )

        assert multi_cloud.combined_service_breakdown == service_breakdown
        assert multi_cloud.combined_service_breakdown["Compute"] == 500.0

    def test_provider_data_integration(self):
        """Test integration with provider-specific NormalizedCostData."""
        # Create normalized data for multiple providers
        aws_data = NormalizedCostData(
            provider="aws",
            total_cost=600.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown={"EC2": 400.0, "S3": 200.0},
        )

        azure_data = NormalizedCostData(
            provider="azure",
            total_cost=400.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown={"Virtual Machines": 250.0, "Storage": 150.0},
        )

        multi_cloud = MultiCloudCostSummary(
            total_cost=1000.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 600.0, "azure": 400.0},
            combined_service_breakdown={"Compute": 650.0, "Storage": 350.0},
            provider_data={"aws": aws_data, "azure": azure_data},
        )

        assert len(multi_cloud.provider_data) == 2
        assert multi_cloud.provider_data["aws"].provider == "aws"
        assert multi_cloud.provider_data["azure"].provider == "azure"
        assert multi_cloud.provider_data["aws"].total_cost == 600.0

    def test_currency_consistency(self):
        """Test currency consistency across providers."""
        aws_data = NormalizedCostData(
            provider="aws",
            total_cost=500.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )

        # Create multi-cloud summary with consistent currency
        multi_cloud = MultiCloudCostSummary(
            total_cost=1000.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 500.0, "azure": 500.0},
            combined_service_breakdown={"Compute": 1000.0},
            provider_data={"aws": aws_data},
        )

        assert multi_cloud.currency == "USD"
        assert multi_cloud.provider_data["aws"].currency == "USD"

    def test_provider_breakdown_sum_validation(self):
        """Test that provider breakdown sums match total (if validation exists)."""
        provider_breakdown = {"aws": 400.0, "azure": 300.0, "gcp": 200.0}  # Sum = 900.0

        # This should work if total matches sum
        multi_cloud = MultiCloudCostSummary(
            total_cost=900.0,  # Matches sum of breakdown
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown=provider_breakdown,
            combined_service_breakdown={"Compute": 900.0},
        )

        assert multi_cloud.total_cost == 900.0

        # Note: Add validation in future to ensure breakdown sums match total
        # For now, documenting expected behavior

    def test_minimal_multi_cloud_summary(self):
        """Test creating MultiCloudCostSummary with minimal fields."""
        multi_cloud = MultiCloudCostSummary(
            total_cost=500.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 500.0},
            combined_service_breakdown={"Compute": 500.0},
        )

        assert multi_cloud.total_cost == 500.0
        assert multi_cloud.provider_data == {}  # Default empty

    def test_empty_collections(self):
        """Test behavior with empty provider and service breakdowns."""
        multi_cloud = MultiCloudCostSummary(
            total_cost=0.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={},
            combined_service_breakdown={},
        )

        assert multi_cloud.total_cost == 0.0
        assert multi_cloud.provider_breakdown == {}
        assert multi_cloud.combined_service_breakdown == {}

    def test_model_serialization_complex(self):
        """Test serialization of complex MultiCloudCostSummary."""
        aws_data = NormalizedCostData(
            provider="aws",
            total_cost=750.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
        )

        multi_cloud = MultiCloudCostSummary(
            total_cost=1250.0,
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 750.0, "azure": 500.0},
            combined_service_breakdown={"Compute": 800.0, "Storage": 450.0},
            provider_data={"aws": aws_data},
        )

        data = multi_cloud.model_dump()

        assert data["total_cost"] == 1250.0
        assert data["provider_breakdown"]["aws"] == 750.0
        assert data["combined_service_breakdown"]["Compute"] == 800.0
        assert "aws" in data["provider_data"]

    @pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "JPY"])
    def test_currency_support(self, currency):
        """Test support for various currencies."""
        multi_cloud = MultiCloudCostSummary(
            total_cost=1000.0,
            currency=currency,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={"aws": 1000.0},
            combined_service_breakdown={"Compute": 1000.0},
        )

        assert multi_cloud.currency == currency

    def test_large_scale_data(self):
        """Test handling large-scale cost data."""
        # Create a large provider breakdown
        provider_breakdown = {f"provider_{i}": 100.0 for i in range(10)}
        service_breakdown = {f"service_{i}": 200.0 for i in range(10)}

        multi_cloud = MultiCloudCostSummary(
            total_cost=3000.0,  # 10 providers * 100 + 10 services * 200
            currency="USD",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            provider_breakdown=provider_breakdown,
            combined_service_breakdown=service_breakdown,
        )

        assert len(multi_cloud.provider_breakdown) == 10
        assert len(multi_cloud.combined_service_breakdown) == 10
        assert multi_cloud.provider_breakdown["provider_0"] == 100.0
