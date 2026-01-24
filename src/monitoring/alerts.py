"""
Alert and threshold monitoring system for multi-cloud cost monitoring.

Provides comprehensive threshold monitoring, alert generation, and notification
capabilities for cost anomalies and budget overruns across cloud providers.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config.settings import CloudConfig
from ..providers.base import CloudCostProvider, CostSummary
from ..utils.data_normalizer import CostDataNormalizer, MultiCloudCostSummary

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(Enum):
    """Types of cost alerts."""

    DAILY_THRESHOLD = "daily_threshold"
    MONTHLY_THRESHOLD = "monthly_threshold"
    BUDGET_EXCEEDED = "budget_exceeded"
    COST_SPIKE = "cost_spike"
    COST_TREND = "cost_trend"
    SERVICE_ANOMALY = "service_anomaly"


class AlertRule(BaseModel):
    """Configuration for an alert rule with comprehensive validation."""

    name: str = Field(..., min_length=1, max_length=100, description="Alert rule name")
    alert_type: AlertType = Field(..., description="Type of alert rule")
    provider: str | None = Field(None, description="Cloud provider (None means all providers)")
    threshold_value: float | None = Field(None, gt=0, description="Absolute threshold value")
    percentage_change: float | None = Field(None, gt=0, description="Percentage change threshold")
    time_window: int = Field(1, gt=0, le=365, description="Time window in days")
    enabled: bool = Field(True, description="Whether the rule is enabled")
    alert_level: AlertLevel = Field(AlertLevel.WARNING, description="Alert severity level")
    description: str | None = Field(None, max_length=500, description="Optional rule description")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        """Validate provider name."""
        if v is None:
            return v

        normalized = v.lower().strip()
        valid_providers = {"aws", "azure", "gcp"}

        if normalized not in valid_providers:
            raise ValueError(
                f'Invalid provider "{v}". Must be one of: {", ".join(sorted(valid_providers))}'
            )
        return normalized

    @field_validator("name", "description")
    @classmethod
    def validate_strings(cls, v: str | None) -> str | None:
        """Validate and clean string fields."""
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @model_validator(mode="after")
    def validate_alert_rule(self):
        """Validate alert rule logic and constraints."""
        # Ensure at least one threshold is set for threshold-based alerts
        threshold_types = {
            AlertType.DAILY_THRESHOLD,
            AlertType.MONTHLY_THRESHOLD,
            AlertType.BUDGET_EXCEEDED,
        }

        if self.alert_type in threshold_types:
            if self.threshold_value is None and self.percentage_change is None:
                raise ValueError(
                    f"Alert type {self.alert_type.value} requires either threshold_value or percentage_change"
                )

            # Ensure mutual exclusivity
            if self.threshold_value is not None and self.percentage_change is not None:
                raise ValueError("threshold_value and percentage_change are mutually exclusive")

        # For spike and trend detection, percentage_change is typically used
        change_types = {AlertType.COST_SPIKE, AlertType.COST_TREND}
        if self.alert_type in change_types and self.percentage_change is None:
            raise ValueError(
                f"Alert type {self.alert_type.value} typically requires percentage_change"
            )

        # Validate time window ranges for different alert types
        if self.alert_type == AlertType.DAILY_THRESHOLD and self.time_window > 1:
            # Warning: daily thresholds typically use time_window=1
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Daily threshold with time_window={self.time_window} may not behave as expected"
            )

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class Alert(BaseModel):
    """Represents a cost alert with comprehensive validation."""

    id: str = Field(..., min_length=1, max_length=50, description="Unique alert identifier")
    rule_name: str = Field(..., min_length=1, max_length=100, description="Name of the alert rule")
    alert_type: AlertType = Field(..., description="Type of alert")
    alert_level: AlertLevel = Field(..., description="Alert severity level")
    provider: str = Field(..., description="Cloud provider or 'all'")
    current_value: float = Field(..., ge=0, description="Current cost value")
    threshold_value: float = Field(..., ge=0, description="Threshold that was exceeded")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code")
    message: str = Field(..., min_length=1, max_length=1000, description="Alert message")
    timestamp: datetime = Field(..., description="When the alert was generated")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    acknowledged: bool = Field(False, description="Whether alert has been acknowledged")
    resolved: bool = Field(False, description="Whether alert has been resolved")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate alert ID format."""
        if not v or not v.strip():
            raise ValueError("Alert ID cannot be empty")

        # Allow various ID formats (UUID, short hash, etc.)
        cleaned = v.strip()

        # Basic validation - alphanumeric with some special chars
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
            raise ValueError(
                "Alert ID can only contain alphanumeric characters, underscores, and dashes"
            )

        return cleaned

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name."""
        normalized = v.lower().strip()
        valid_providers = {"aws", "azure", "gcp", "all"}

        if normalized not in valid_providers:
            raise ValueError(
                f'Invalid provider "{v}". Must be one of: {", ".join(sorted(valid_providers))}'
            )
        return normalized

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate and normalize currency code."""
        if not v or not v.strip():
            raise ValueError("Currency must be specified")

        normalized = v.upper().strip()

        # Common ISO 4217 currency codes
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
            # Allow any 3-letter code but warn
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown currency code in alert: {normalized}")

        return normalized

    @field_validator("message", "rule_name")
    @classmethod
    def validate_text_fields(cls, v: str) -> str:
        """Validate and clean text fields."""
        if not v or not v.strip():
            raise ValueError("Text field cannot be empty")
        return v.strip()

    @field_validator("current_value", "threshold_value")
    @classmethod
    def validate_values(cls, v: float) -> float:
        """Validate cost values."""
        if v < 0:
            raise ValueError("Cost values cannot be negative")
        if v > 1e12:  # 1 trillion
            raise ValueError("Cost value exceeds reasonable limits")
        return v

    @model_validator(mode="after")
    def validate_alert_state(self):
        """Validate alert state consistency and business rules."""
        # Validate timestamp is not too far in the future (allow small clock skew)
        now = datetime.now()
        max_future = now + timedelta(minutes=5)

        if self.timestamp > max_future:
            raise ValueError(f"Alert timestamp {self.timestamp} cannot be in the future")

        # Validate state consistency
        if self.resolved and not self.acknowledged:
            # Auto-acknowledge resolved alerts
            self.acknowledged = True

        # Validate alert makes sense (current > threshold for cost alerts)
        threshold_types = {
            AlertType.DAILY_THRESHOLD,
            AlertType.MONTHLY_THRESHOLD,
            AlertType.BUDGET_EXCEEDED,
        }

        if self.alert_type in threshold_types and self.current_value <= self.threshold_value:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Alert {self.id}: current_value ({self.current_value}) <= threshold_value ({self.threshold_value})"
            )

        # Validate metadata
        if self.metadata:
            for key, _value in self.metadata.items():
                if not isinstance(key, str):
                    raise ValueError(f"Metadata keys must be strings, got {type(key)}")

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary for serialization."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class ThresholdMonitor:
    """Monitors cost thresholds and generates alerts."""

    def __init__(self, config: CloudConfig):
        self.config = config
        self.normalizer = CostDataNormalizer()
        self.alert_rules: list[AlertRule] = []
        self.active_alerts: list[Alert] = []
        self.alert_history: list[Alert] = []
        self.alert_callbacks: list[Callable[[Alert], None]] = []

        # Load alert rules from configuration
        self._load_alert_rules_from_config()

    def _load_alert_rules_from_config(self):
        """Load alert rules from configuration."""
        # Global threshold rules
        global_warning = self.config.get_threshold("warning")
        global_critical = self.config.get_threshold("critical")

        if global_warning:
            self.alert_rules.append(
                AlertRule(
                    name="global_daily_warning",
                    alert_type=AlertType.DAILY_THRESHOLD,
                    threshold_value=global_warning,
                    alert_level=AlertLevel.WARNING,
                    description=f"Daily cost exceeds warning threshold of {global_warning}",
                )
            )

        if global_critical:
            self.alert_rules.append(
                AlertRule(
                    name="global_daily_critical",
                    alert_type=AlertType.DAILY_THRESHOLD,
                    threshold_value=global_critical,
                    alert_level=AlertLevel.CRITICAL,
                    description=f"Daily cost exceeds critical threshold of {global_critical}",
                )
            )

        # Provider-specific threshold rules
        for provider in self.config.enabled_providers:
            provider_warning = self.config.get_threshold("warning", provider)
            provider_critical = self.config.get_threshold("critical", provider)

            if provider_warning:
                self.alert_rules.append(
                    AlertRule(
                        name=f"{provider}_daily_warning",
                        alert_type=AlertType.DAILY_THRESHOLD,
                        provider=provider,
                        threshold_value=provider_warning,
                        alert_level=AlertLevel.WARNING,
                        description=f"{provider.upper()} daily cost exceeds warning threshold",
                    )
                )

            if provider_critical:
                self.alert_rules.append(
                    AlertRule(
                        name=f"{provider}_daily_critical",
                        alert_type=AlertType.DAILY_THRESHOLD,
                        provider=provider,
                        threshold_value=provider_critical,
                        alert_level=AlertLevel.CRITICAL,
                        description=f"{provider.upper()} daily cost exceeds critical threshold",
                    )
                )

    def add_alert_rule(self, rule: AlertRule):
        """Add a custom alert rule."""
        self.alert_rules.append(rule)
        logger.info(f"Added alert rule: {rule.name}")

    def remove_alert_rule(self, rule_name: str) -> bool:
        """Remove an alert rule by name."""
        original_count = len(self.alert_rules)
        self.alert_rules = [rule for rule in self.alert_rules if rule.name != rule_name]
        removed = len(self.alert_rules) < original_count

        if removed:
            logger.info(f"Removed alert rule: {rule_name}")

        return removed

    def add_alert_callback(self, callback: Callable[[Alert], None]):
        """Add a callback function to be called when an alert is generated."""
        self.alert_callbacks.append(callback)

    async def check_thresholds(
        self, providers: dict[str, CloudCostProvider], check_date: date | None = None
    ) -> list[Alert]:
        """
        Check all configured thresholds against current costs.

        Args:
            providers: Dictionary of authenticated cloud providers
            check_date: Date to check (defaults to today)

        Returns:
            List of generated alerts
        """
        if check_date is None:
            check_date = date.today()

        new_alerts = []

        # Get cost data for all providers
        cost_summaries = []
        for provider_name, provider in providers.items():
            try:
                if not await provider.is_authenticated():
                    continue

                # Get daily costs (AWS requires start < end, so add one day to end date)
                end_date = check_date + timedelta(days=1)
                daily_summary = await provider.get_cost_data(check_date, end_date)
                cost_summaries.append(daily_summary)

            except Exception as e:
                logger.error(f"Failed to get cost data for {provider_name}: {e}")
                continue

        if not cost_summaries:
            logger.warning("No cost data available for threshold checking")
            return []

        # Normalize and aggregate data
        multi_cloud_summary = self.normalizer.aggregate_multi_cloud_data(cost_summaries)

        # Check each alert rule
        for rule in self.alert_rules:
            if not rule.enabled:
                continue

            try:
                alerts = await self._check_rule(rule, multi_cloud_summary, cost_summaries)
                new_alerts.extend(alerts)
            except Exception as e:
                logger.error(f"Error checking rule {rule.name}: {e}")

        # Store and notify about new alerts
        for alert in new_alerts:
            self.active_alerts.append(alert)
            self.alert_history.append(alert)

            # Call alert callbacks
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error(f"Error in alert callback: {e}")

        return new_alerts

    async def _check_rule(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: list[CostSummary],
    ) -> list[Alert]:
        """Check a specific alert rule."""
        alerts = []

        if rule.alert_type == AlertType.DAILY_THRESHOLD:
            alerts.extend(
                await self._check_daily_threshold(rule, multi_cloud_summary, cost_summaries)
            )
        elif rule.alert_type == AlertType.COST_SPIKE:
            alerts.extend(await self._check_cost_spike(rule, multi_cloud_summary, cost_summaries))
        elif rule.alert_type == AlertType.SERVICE_ANOMALY:
            alerts.extend(
                await self._check_service_anomaly(rule, multi_cloud_summary, cost_summaries)
            )

        return alerts

    async def _check_daily_threshold(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: list[CostSummary],
    ) -> list[Alert]:
        """Check daily cost thresholds."""
        alerts = []

        if rule.provider is None:
            # Global threshold - check total across all providers
            current_cost = multi_cloud_summary.total_cost
            if current_cost > rule.threshold_value:
                alert = Alert(
                    id=self._generate_alert_id(),
                    rule_name=rule.name,
                    alert_type=rule.alert_type,
                    alert_level=rule.alert_level,
                    provider="all",
                    current_value=current_cost,
                    threshold_value=rule.threshold_value,
                    currency=multi_cloud_summary.currency,
                    message=f"Total daily cost ${current_cost:.2f} exceeds threshold ${rule.threshold_value:.2f}",
                    timestamp=datetime.now(),
                    metadata={
                        "provider_breakdown": multi_cloud_summary.provider_breakdown,
                        "threshold_exceeded_by": current_cost - rule.threshold_value,
                    },
                )
                alerts.append(alert)
        else:
            # Provider-specific threshold
            for summary in cost_summaries:
                if summary.provider == rule.provider:
                    current_cost = summary.total_cost
                    if current_cost > rule.threshold_value:
                        alert = Alert(
                            id=self._generate_alert_id(),
                            rule_name=rule.name,
                            alert_type=rule.alert_type,
                            alert_level=rule.alert_level,
                            provider=summary.provider,
                            current_value=current_cost,
                            threshold_value=rule.threshold_value,
                            currency=summary.currency,
                            message=f"{summary.provider.upper()} daily cost ${current_cost:.2f} exceeds threshold ${rule.threshold_value:.2f}",
                            timestamp=datetime.now(),
                            metadata={"threshold_exceeded_by": current_cost - rule.threshold_value},
                        )
                        alerts.append(alert)
                    break

        return alerts

    async def _check_cost_spike(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: list[CostSummary],
    ) -> list[Alert]:
        """Check for cost spikes compared to historical data."""
        # This would require historical data comparison
        # For now, return empty list - could be implemented with database storage
        return []

    async def _check_service_anomaly(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: list[CostSummary],
    ) -> list[Alert]:
        """Check for service-level cost anomalies."""
        # This would require service-level analysis
        # For now, return empty list - could be implemented with statistical analysis
        return []

    def get_active_alerts(
        self, provider: str | None = None, alert_level: AlertLevel | None = None
    ) -> list[Alert]:
        """Get currently active alerts with optional filtering."""
        alerts = self.active_alerts

        if provider:
            alerts = [a for a in alerts if a.provider == provider or a.provider == "all"]

        if alert_level:
            alerts = [a for a in alerts if a.alert_level == alert_level]

        return alerts

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self.active_alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                logger.info(f"Alert {alert_id} acknowledged")
                return True
        return False

    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert."""
        for i, alert in enumerate(self.active_alerts):
            if alert.id == alert_id:
                alert.resolved = True
                # Move to history and remove from active
                self.active_alerts.pop(i)
                logger.info(f"Alert {alert_id} resolved")
                return True
        return False

    def clear_resolved_alerts(self):
        """Remove resolved alerts from active alerts list."""
        self.active_alerts = [a for a in self.active_alerts if not a.resolved]

    def get_alert_summary(self) -> dict[str, Any]:
        """Get a summary of current alert status."""
        active_count = len(self.active_alerts)
        critical_count = len(
            [a for a in self.active_alerts if a.alert_level == AlertLevel.CRITICAL]
        )
        warning_count = len([a for a in self.active_alerts if a.alert_level == AlertLevel.WARNING])

        provider_alerts = {}
        for alert in self.active_alerts:
            if alert.provider not in provider_alerts:
                provider_alerts[alert.provider] = 0
            provider_alerts[alert.provider] += 1

        return {
            "total_active_alerts": active_count,
            "critical_alerts": critical_count,
            "warning_alerts": warning_count,
            "alerts_by_provider": provider_alerts,
            "last_check_time": datetime.now().isoformat(),
        }

    def _generate_alert_id(self) -> str:
        """Generate a unique alert ID."""
        import uuid

        return str(uuid.uuid4())[:8]


class CostAnomalyDetector:
    """Detects cost anomalies using statistical analysis."""

    def __init__(self, sensitivity: float = 2.0):
        """
        Initialize the anomaly detector.

        Args:
            sensitivity: Standard deviation multiplier for anomaly detection
        """
        self.sensitivity = sensitivity

    def detect_anomalies(self, daily_costs: list[float], window_size: int = 7) -> list[bool]:
        """
        Detect anomalies in daily cost data.

        Args:
            daily_costs: List of daily cost values
            window_size: Size of rolling window for comparison

        Returns:
            List of boolean values indicating anomalies
        """
        if len(daily_costs) < window_size + 1:
            return [False] * len(daily_costs)

        anomalies = [False] * len(daily_costs)

        for i in range(window_size, len(daily_costs)):
            # Calculate mean and std dev of previous window
            window = daily_costs[i - window_size : i]
            mean_cost = sum(window) / len(window)

            if len(set(window)) == 1:  # All values are the same
                continue

            variance = sum((x - mean_cost) ** 2 for x in window) / len(window)
            std_dev = variance**0.5

            # Check if current value is anomalous
            current_cost = daily_costs[i]
            threshold = mean_cost + (self.sensitivity * std_dev)

            if current_cost > threshold:
                anomalies[i] = True

        return anomalies


class BudgetMonitor:
    """Monitors costs against predefined budgets."""

    def __init__(self):
        self.budgets: dict[str, dict[str, float]] = {}

    def set_budget(self, provider: str, period: str, amount: float, currency: str = "USD"):
        """
        Set a budget for a provider and time period.

        Args:
            provider: Cloud provider name
            period: Budget period (monthly, yearly)
            amount: Budget amount
            currency: Budget currency
        """
        if provider not in self.budgets:
            self.budgets[provider] = {}

        self.budgets[provider][period] = {"amount": amount, "currency": currency}

    def check_budget_status(
        self, provider: str, period: str, current_spend: float, currency: str = "USD"
    ) -> dict[str, Any]:
        """
        Check budget status for a provider and period.

        Args:
            provider: Cloud provider name
            period: Budget period
            current_spend: Current spending amount
            currency: Spending currency

        Returns:
            Dictionary with budget status information
        """
        if provider not in self.budgets or period not in self.budgets[provider]:
            return {"budget_set": False, "status": "no_budget"}

        budget_info = self.budgets[provider][period]
        budget_amount = budget_info["amount"]

        # Simple currency handling (in production, use real conversion)
        if currency != budget_info["currency"]:
            # For now, assume same currency
            pass

        percentage_used = (current_spend / budget_amount) * 100
        remaining = budget_amount - current_spend

        status = "ok"
        if percentage_used >= 100:
            status = "exceeded"
        elif percentage_used >= 90:
            status = "critical"
        elif percentage_used >= 75:
            status = "warning"

        return {
            "budget_set": True,
            "budget_amount": budget_amount,
            "current_spend": current_spend,
            "remaining": remaining,
            "percentage_used": percentage_used,
            "status": status,
            "currency": budget_info["currency"],
        }
