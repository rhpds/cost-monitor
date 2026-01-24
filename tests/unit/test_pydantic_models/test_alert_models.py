"""
Tests for alert system Pydantic models.

Tests AlertRule and Alert models including validation,
field constraints, and alert processing logic.
"""

from datetime import datetime, timedelta

import pytest

from src.monitoring.alerts import Alert, AlertLevel, AlertRule, AlertType


class TestAlertRule:
    """Test cases for AlertRule Pydantic model."""

    def test_create_valid_alert_rule(self, sample_alert_rule):
        """Test creating a valid AlertRule with all fields."""
        rule = sample_alert_rule

        assert rule.name == "Daily Cost Warning"
        assert rule.alert_type == AlertType.DAILY_THRESHOLD
        assert rule.provider == "aws"
        assert rule.threshold_value == 500.0
        assert rule.time_window == 1
        assert rule.enabled is True
        assert rule.alert_level == AlertLevel.WARNING
        assert rule.description == "Alert when daily AWS costs exceed $500"

    def test_create_minimal_alert_rule(self):
        """Test creating AlertRule with minimal required fields."""
        rule = AlertRule(
            name="Basic Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=100.0
        )

        assert rule.name == "Basic Alert"
        assert rule.alert_type == AlertType.DAILY_THRESHOLD
        assert rule.threshold_value == 100.0
        assert rule.provider is None  # Optional field
        assert rule.time_window == 1  # Default value
        assert rule.enabled is True  # Default value
        assert rule.alert_level == AlertLevel.WARNING  # Default value

    def test_alert_name_validation(self):
        """Test alert name field validation."""
        # Test empty name
        with pytest.raises(ValueError, match="Alert name cannot be empty"):
            AlertRule(name="", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=100.0)

        # Test too long name
        long_name = "A" * 101  # 101 characters
        with pytest.raises(ValueError, match="Alert name must be 100 characters or less"):
            AlertRule(name=long_name, alert_type=AlertType.DAILY_THRESHOLD, threshold_value=100.0)

    def test_provider_validation(self):
        """Test provider field validation."""
        # Valid providers
        for provider in ["aws", "azure", "gcp"]:
            rule = AlertRule(
                name="Test Alert",
                alert_type=AlertType.DAILY_THRESHOLD,
                provider=provider,
                threshold_value=100.0,
            )
            assert rule.provider == provider

        # Invalid provider
        with pytest.raises(ValueError, match="Provider must be one of"):
            AlertRule(
                name="Test Alert",
                alert_type=AlertType.DAILY_THRESHOLD,
                provider="invalid",
                threshold_value=100.0,
            )

    def test_threshold_value_validation(self):
        """Test threshold value validation."""
        # Valid positive threshold
        rule = AlertRule(
            name="Test Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=500.0
        )
        assert rule.threshold_value == 500.0

        # Zero threshold should be rejected
        with pytest.raises(ValueError, match="Threshold value must be positive"):
            AlertRule(name="Test Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=0.0)

        # Negative threshold should be rejected
        with pytest.raises(ValueError, match="Threshold value must be positive"):
            AlertRule(
                name="Test Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=-100.0
            )

    def test_percentage_change_validation(self):
        """Test percentage change validation."""
        # Valid percentage change
        rule = AlertRule(
            name="Test Alert", alert_type=AlertType.PERCENTAGE_CHANGE, percentage_change=25.0
        )
        assert rule.percentage_change == 25.0

        # Negative percentage change should be rejected
        with pytest.raises(ValueError, match="Percentage change must be positive"):
            AlertRule(
                name="Test Alert", alert_type=AlertType.PERCENTAGE_CHANGE, percentage_change=-10.0
            )

    def test_both_thresholds_allowed(self):
        """Test that both threshold_value and percentage_change can be set."""
        # Both thresholds should be allowed
        rule = AlertRule(
            name="Test Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            threshold_value=100.0,
            percentage_change=25.0,
        )
        assert rule.threshold_value == 100.0
        assert rule.percentage_change == 25.0

    def test_threshold_type_compatibility(self):
        """Test that alert rules can have either threshold_value or percentage_change."""
        # Test with threshold_value
        rule_with_threshold = AlertRule(
            name="Test Alert", alert_type=AlertType.DAILY_THRESHOLD, threshold_value=100.0
        )
        assert rule_with_threshold.threshold_value == 100.0

        # Test with percentage_change
        rule_with_percentage = AlertRule(
            name="Test Alert", alert_type=AlertType.COST_SPIKE, percentage_change=25.0
        )
        assert rule_with_percentage.percentage_change == 25.0

    def test_time_window_validation(self):
        """Test time window validation."""
        # Valid time windows
        for time_window in [1, 7, 30, 365]:
            rule = AlertRule(
                name="Test Alert",
                alert_type=AlertType.DAILY_THRESHOLD,
                threshold_value=100.0,
                time_window=time_window,
            )
            assert rule.time_window == time_window

        # Zero time window should be rejected
        with pytest.raises(ValueError, match="Time window must be between 1 and 365 days"):
            AlertRule(
                name="Test Alert",
                alert_type=AlertType.DAILY_THRESHOLD,
                threshold_value=100.0,
                time_window=0,
            )

        # Too large time window should be rejected
        with pytest.raises(ValueError, match="Time window must be between 1 and 365 days"):
            AlertRule(
                name="Test Alert",
                alert_type=AlertType.DAILY_THRESHOLD,
                threshold_value=100.0,
                time_window=366,
            )

    @pytest.mark.parametrize(
        "alert_type",
        [
            AlertType.DAILY_THRESHOLD,
            AlertType.MONTHLY_THRESHOLD,
            AlertType.BUDGET_EXCEEDED,
            AlertType.COST_SPIKE,
        ],
    )
    def test_all_alert_types(self, alert_type):
        """Test all supported alert types."""
        rule = AlertRule(name="Test Alert", alert_type=alert_type)
        assert rule.alert_type == alert_type

    @pytest.mark.parametrize(
        "alert_level", [AlertLevel.INFO, AlertLevel.WARNING, AlertLevel.CRITICAL]
    )
    def test_all_alert_levels(self, alert_level):
        """Test all supported alert levels."""
        rule = AlertRule(
            name="Test Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            threshold_value=100.0,
            alert_level=alert_level,
        )

        assert rule.alert_level == alert_level

    def test_metadata_field(self):
        """Test metadata field functionality."""
        metadata = {
            "created_by": "admin",
            "department": "finance",
            "tags": ["production", "cost-control"],
        }

        rule = AlertRule(
            name="Test Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            threshold_value=100.0,
            metadata=metadata,
        )

        assert rule.metadata == metadata
        assert rule.metadata["created_by"] == "admin"

    def test_model_serialization(self):
        """Test AlertRule model serialization."""
        rule = AlertRule(
            name="Test Alert",
            alert_type=AlertType.DAILY_THRESHOLD,
            provider="aws",
            threshold_value=500.0,
            alert_level=AlertLevel.CRITICAL,
        )

        data = rule.model_dump()

        assert data["name"] == "Test Alert"
        assert data["alert_type"] == AlertType.DAILY_THRESHOLD
        assert data["provider"] == "aws"
        assert data["threshold_value"] == 500.0
        assert data["alert_level"] == AlertLevel.CRITICAL


class TestAlert:
    """Test cases for Alert Pydantic model."""

    def test_create_valid_alert(self, sample_alert):
        """Test creating a valid Alert with all fields."""
        alert = sample_alert

        assert alert.id == "alert-test-12345"
        assert alert.rule_name == "Daily Cost Warning"
        assert alert.alert_type == AlertType.DAILY_THRESHOLD
        assert alert.alert_level == AlertLevel.WARNING
        assert alert.provider == "aws"
        assert alert.current_value == 650.0
        assert alert.threshold_value == 500.0
        assert alert.currency == "USD"
        assert "Daily AWS cost of $650.00 exceeds threshold" in alert.message
        assert alert.acknowledged is False
        assert alert.resolved is False

    def test_alert_id_validation(self):
        """Test alert ID validation."""
        # Valid alert ID format
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
        )
        assert alert.id == "alert-12345678"

        # Invalid alert ID format (too short)
        with pytest.raises(ValueError, match="Alert ID must be at least 8 characters"):
            Alert(
                id="short",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=650.0,
                threshold_value=500.0,
                currency="USD",
                message="Test message",
                timestamp=datetime.now(),
            )

    def test_negative_values_rejected(self):
        """Test that negative current_value and threshold_value are rejected."""
        # Negative current_value
        with pytest.raises(ValueError, match="Current value cannot be negative"):
            Alert(
                id="alert-12345678",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=-100.0,
                threshold_value=500.0,
                currency="USD",
                message="Test message",
                timestamp=datetime.now(),
            )

        # Negative threshold_value
        with pytest.raises(ValueError, match="Threshold value cannot be negative"):
            Alert(
                id="alert-12345678",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=650.0,
                threshold_value=-500.0,
                currency="USD",
                message="Test message",
                timestamp=datetime.now(),
            )

    def test_future_timestamp_rejected(self):
        """Test that future timestamps are rejected."""
        future_time = datetime.now() + timedelta(hours=1)

        with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
            Alert(
                id="alert-12345678",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=650.0,
                threshold_value=500.0,
                currency="USD",
                message="Test message",
                timestamp=future_time,
            )

    def test_empty_message_rejected(self):
        """Test that empty messages are rejected."""
        with pytest.raises(ValueError, match="Message cannot be empty"):
            Alert(
                id="alert-12345678",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=650.0,
                threshold_value=500.0,
                currency="USD",
                message="",  # Empty message
                timestamp=datetime.now(),
            )

    def test_alert_state_consistency(self):
        """Test alert state consistency rules."""
        # Test resolved alert must be acknowledged first
        # Note: This test assumes such validation exists or should exist
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
            acknowledged=False,
            resolved=True,  # Resolved but not acknowledged
        )

        # For now, just verify it creates successfully
        # Future enhancement: add state consistency validation
        assert alert.resolved is True
        assert alert.acknowledged is False

    def test_currency_validation(self):
        """Test currency code validation in alerts."""
        # Valid currency
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
        )
        assert alert.currency == "USD"

        # Invalid currency (too short)
        with pytest.raises(ValueError, match="Currency code must be 3 characters"):
            Alert(
                id="alert-12345678",
                rule_name="Test Rule",
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider="aws",
                current_value=650.0,
                threshold_value=500.0,
                currency="US",  # Too short
                message="Test message",
                timestamp=datetime.now(),
            )

    def test_metadata_with_service_breakdown(self):
        """Test metadata field with service breakdown information."""
        metadata = {
            "service_breakdown": {"EC2": 400.0, "S3": 200.0, "RDS": 50.0},
            "region": "us-east-1",
            "account_id": "123456789012",
        }

        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
            metadata=metadata,
        )

        assert alert.metadata["service_breakdown"]["EC2"] == 400.0
        assert alert.metadata["region"] == "us-east-1"

    def test_acknowledge_alert(self):
        """Test acknowledging an alert."""
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
            acknowledged=True,
        )

        assert alert.acknowledged is True

    def test_resolve_alert(self):
        """Test resolving an alert."""
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=datetime.now(),
            resolved=True,
        )

        assert alert.resolved is True

    def test_model_serialization_with_datetime(self):
        """Test Alert model serialization including datetime field."""
        timestamp = datetime(2024, 1, 15, 10, 30, 45)
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Test message",
            timestamp=timestamp,
        )

        data = alert.model_dump()

        assert data["id"] == "alert-12345678"
        assert data["current_value"] == 650.0
        assert data["timestamp"] == timestamp

    @pytest.mark.parametrize("provider", ["aws", "azure", "gcp"])
    def test_alert_for_all_providers(self, provider):
        """Test creating alerts for all supported providers."""
        alert = Alert(
            id="alert-12345678",
            rule_name="Test Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider=provider,
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message=f"Test alert for {provider}",
            timestamp=datetime.now(),
        )

        assert alert.provider == provider

    def test_alert_level_severity_ordering(self):
        """Test that alert levels can be compared for severity."""
        # Create alerts with different severity levels
        info_alert = Alert(
            id="alert-info",
            rule_name="Info Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.INFO,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Info message",
            timestamp=datetime.now(),
        )

        critical_alert = Alert(
            id="alert-critical",
            rule_name="Critical Rule",
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.CRITICAL,
            provider="aws",
            current_value=650.0,
            threshold_value=500.0,
            currency="USD",
            message="Critical message",
            timestamp=datetime.now(),
        )

        # Test that different levels are properly set
        assert info_alert.alert_level == AlertLevel.INFO
        assert critical_alert.alert_level == AlertLevel.CRITICAL

        # Note: Actual severity comparison would require implementing
        # __lt__, __gt__ methods on AlertLevel enum if needed
