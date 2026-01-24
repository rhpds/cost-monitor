"""
Basic tests for Pydantic models to verify test infrastructure.

These tests focus on basic model creation and serialization rather than
extensive validation logic.
"""

from datetime import date, datetime

from src.monitoring.alerts import Alert, AlertLevel, AlertRule, AlertType
from src.providers.base import CostDataPoint, CostSummary, TimeGranularity


class TestBasicCostDataPoint:
    """Basic tests for CostDataPoint model."""

    def test_create_cost_data_point(self):
        """Test basic CostDataPoint creation."""
        point = CostDataPoint(date=date(2024, 1, 15), amount=125.50, currency="USD")

        assert point.date == date(2024, 1, 15)
        assert point.amount == 125.50
        assert point.currency == "USD"

    def test_cost_data_point_with_optional_fields(self):
        """Test CostDataPoint with optional fields."""
        point = CostDataPoint(
            date=date(2024, 1, 15),
            amount=125.50,
            currency="USD",
            service_name="Amazon EC2",
            account_id="123456789012",
            region="us-east-1",
            tags={"Environment": "Production"},
        )

        assert point.service_name == "Amazon EC2"
        assert point.account_id == "123456789012"
        assert point.region == "us-east-1"
        assert point.tags["Environment"] == "Production"

    def test_cost_data_point_serialization(self):
        """Test CostDataPoint serialization."""
        point = CostDataPoint(date=date(2024, 1, 15), amount=125.50, currency="USD")

        data = point.model_dump()
        assert data["amount"] == 125.50
        assert data["currency"] == "USD"


class TestBasicCostSummary:
    """Basic tests for CostSummary model."""

    def test_create_cost_summary(self):
        """Test basic CostSummary creation."""
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_cost=1000.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert summary.provider == "aws"
        assert summary.total_cost == 1000.0
        assert summary.currency == "USD"
        assert summary.granularity == TimeGranularity.DAILY

    def test_cost_summary_with_data_points(self):
        """Test CostSummary with nested data points."""
        point = CostDataPoint(date=date(2024, 1, 15), amount=125.50, currency="USD")

        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_cost=125.50,
            currency="USD",
            data_points=[point],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        assert len(summary.data_points) == 1
        assert summary.data_points[0].amount == 125.50


class TestBasicAlertRule:
    """Basic tests for AlertRule model."""

    def test_create_alert_rule(self):
        """Test basic AlertRule creation."""
        rule = AlertRule(
            name="Daily Cost Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=500.0
        )

        assert rule.name == "Daily Cost Alert"
        assert rule.alert_type == AlertType.DAILY_THRESHOLD
        assert rule.threshold_value == 500.0
        assert rule.enabled is True  # Default value
        assert rule.alert_level == AlertLevel.WARNING  # Default value

    def test_alert_rule_with_all_fields(self):
        """Test AlertRule with all fields."""
        rule = AlertRule(
            name="Daily Cost Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            provider="aws",
            threshold_value=500.0,
            time_window=1,
            enabled=True,
            alert_level=AlertLevel.CRITICAL,
            description="Alert when daily costs exceed $500",
        )

        assert rule.provider == "aws"
        assert rule.threshold_value == 500.0
        assert rule.alert_level == AlertLevel.CRITICAL
        assert rule.description == "Alert when daily costs exceed $500"


class TestBasicAlert:
    """Basic tests for Alert model."""

    def test_create_alert(self):
        """Test basic Alert creation."""
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test alert message",
            timestamp=datetime.now(),
        )

        assert alert.id == "alert-12345678"
        assert alert.rule_name == "Test Rule"
        assert alert.current_value == 650.0
        assert alert.threshold_value == 500.0
        assert alert.acknowledged is False  # Default value
        assert alert.resolved is False  # Default value


class TestEnumValues:
    """Test enum values."""

    def test_time_granularity_values(self):
        """Test TimeGranularity enum values."""
        assert TimeGranularity.DAILY.value == "daily"
        assert TimeGranularity.MONTHLY.value == "monthly"
        assert TimeGranularity.YEARLY.value == "yearly"

    def test_alert_type_values(self):
        """Test AlertType enum values."""
        assert AlertType.DAILY_THRESHOLD.value == "daily_threshold"
        assert AlertType.MONTHLY_THRESHOLD.value == "monthly_threshold"
        assert AlertType.BUDGET_EXCEEDED.value == "budget_exceeded"
        assert AlertType.COST_SPIKE.value == "cost_spike"

    def test_alert_level_values(self):
        """Test AlertLevel enum values."""
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"


class TestModelIntegration:
    """Test basic model integration."""

    def test_full_workflow_simulation(self):
        """Test a basic workflow with all models."""
        # Create a cost data point
        point = CostDataPoint(
            date=date(2024, 1, 15), amount=650.0, currency="USD", service_name="Amazon EC2"
        )

        # Create a cost summary
        summary = CostSummary(
            provider="aws",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_cost=650.0,
            currency="USD",
            data_points=[point],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )

        # Create an alert rule
        rule = AlertRule(
            name="Daily AWS Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            provider="aws",
            threshold_value=500.0,
        )

        # Create an alert
        alert = Alert(
            id="alert-workflow",
            rule_name=rule.name,
            alert_type=rule.alert_type,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Daily cost exceeded threshold",
            timestamp=datetime.now(),
        )

        # Verify all models work together
        assert summary.total_cost > rule.threshold_value
        assert alert.current_value == summary.total_cost
        assert alert.rule_name == rule.name
        assert summary.data_points[0].service_name == "Amazon EC2"
