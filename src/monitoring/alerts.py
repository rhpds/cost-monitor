"""
Alert and threshold monitoring system for multi-cloud cost monitoring.

Provides comprehensive threshold monitoring, alert generation, and notification
capabilities for cost anomalies and budget overruns across cloud providers.
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from ..providers.base import CloudCostProvider, CostSummary
from ..utils.data_normalizer import CostDataNormalizer, MultiCloudCostSummary
from ..config.settings import CloudConfig

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


@dataclass
class AlertRule:
    """Configuration for an alert rule."""
    name: str
    alert_type: AlertType
    provider: Optional[str] = None  # None means all providers
    threshold_value: Optional[float] = None
    percentage_change: Optional[float] = None
    time_window: int = 1  # days
    enabled: bool = True
    alert_level: AlertLevel = AlertLevel.WARNING
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """Represents a cost alert."""
    id: str
    rule_name: str
    alert_type: AlertType
    alert_level: AlertLevel
    provider: str
    current_value: float
    threshold_value: float
    currency: str
    message: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for serialization."""
        return {
            'id': self.id,
            'rule_name': self.rule_name,
            'alert_type': self.alert_type.value,
            'alert_level': self.alert_level.value,
            'provider': self.provider,
            'current_value': self.current_value,
            'threshold_value': self.threshold_value,
            'currency': self.currency,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
            'acknowledged': self.acknowledged,
            'resolved': self.resolved
        }


class ThresholdMonitor:
    """Monitors cost thresholds and generates alerts."""

    def __init__(self, config: CloudConfig):
        self.config = config
        self.normalizer = CostDataNormalizer()
        self.alert_rules: List[AlertRule] = []
        self.active_alerts: List[Alert] = []
        self.alert_history: List[Alert] = []
        self.alert_callbacks: List[Callable[[Alert], None]] = []

        # Load alert rules from configuration
        self._load_alert_rules_from_config()

    def _load_alert_rules_from_config(self):
        """Load alert rules from configuration."""
        # Global threshold rules
        global_warning = self.config.get_threshold('warning')
        global_critical = self.config.get_threshold('critical')

        if global_warning:
            self.alert_rules.append(AlertRule(
                name="global_daily_warning",
                alert_type=AlertType.DAILY_THRESHOLD,
                threshold_value=global_warning,
                alert_level=AlertLevel.WARNING,
                description=f"Daily cost exceeds warning threshold of {global_warning}"
            ))

        if global_critical:
            self.alert_rules.append(AlertRule(
                name="global_daily_critical",
                alert_type=AlertType.DAILY_THRESHOLD,
                threshold_value=global_critical,
                alert_level=AlertLevel.CRITICAL,
                description=f"Daily cost exceeds critical threshold of {global_critical}"
            ))

        # Provider-specific threshold rules
        for provider in self.config.enabled_providers:
            provider_warning = self.config.get_threshold('warning', provider)
            provider_critical = self.config.get_threshold('critical', provider)

            if provider_warning:
                self.alert_rules.append(AlertRule(
                    name=f"{provider}_daily_warning",
                    alert_type=AlertType.DAILY_THRESHOLD,
                    provider=provider,
                    threshold_value=provider_warning,
                    alert_level=AlertLevel.WARNING,
                    description=f"{provider.upper()} daily cost exceeds warning threshold"
                ))

            if provider_critical:
                self.alert_rules.append(AlertRule(
                    name=f"{provider}_daily_critical",
                    alert_type=AlertType.DAILY_THRESHOLD,
                    provider=provider,
                    threshold_value=provider_critical,
                    alert_level=AlertLevel.CRITICAL,
                    description=f"{provider.upper()} daily cost exceeds critical threshold"
                ))

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
        self,
        providers: Dict[str, CloudCostProvider],
        check_date: Optional[date] = None
    ) -> List[Alert]:
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
                daily_summary = await provider.get_cost_data(
                    check_date, end_date
                )
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
        cost_summaries: List[CostSummary]
    ) -> List[Alert]:
        """Check a specific alert rule."""
        alerts = []

        if rule.alert_type == AlertType.DAILY_THRESHOLD:
            alerts.extend(await self._check_daily_threshold(rule, multi_cloud_summary, cost_summaries))
        elif rule.alert_type == AlertType.COST_SPIKE:
            alerts.extend(await self._check_cost_spike(rule, multi_cloud_summary, cost_summaries))
        elif rule.alert_type == AlertType.SERVICE_ANOMALY:
            alerts.extend(await self._check_service_anomaly(rule, multi_cloud_summary, cost_summaries))

        return alerts

    async def _check_daily_threshold(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: List[CostSummary]
    ) -> List[Alert]:
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
                        'provider_breakdown': multi_cloud_summary.provider_breakdown,
                        'threshold_exceeded_by': current_cost - rule.threshold_value
                    }
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
                            metadata={
                                'threshold_exceeded_by': current_cost - rule.threshold_value
                            }
                        )
                        alerts.append(alert)
                    break

        return alerts

    async def _check_cost_spike(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: List[CostSummary]
    ) -> List[Alert]:
        """Check for cost spikes compared to historical data."""
        # This would require historical data comparison
        # For now, return empty list - could be implemented with database storage
        return []

    async def _check_service_anomaly(
        self,
        rule: AlertRule,
        multi_cloud_summary: MultiCloudCostSummary,
        cost_summaries: List[CostSummary]
    ) -> List[Alert]:
        """Check for service-level cost anomalies."""
        # This would require service-level analysis
        # For now, return empty list - could be implemented with statistical analysis
        return []

    def get_active_alerts(
        self,
        provider: Optional[str] = None,
        alert_level: Optional[AlertLevel] = None
    ) -> List[Alert]:
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

    def get_alert_summary(self) -> Dict[str, Any]:
        """Get a summary of current alert status."""
        active_count = len(self.active_alerts)
        critical_count = len([a for a in self.active_alerts if a.alert_level == AlertLevel.CRITICAL])
        warning_count = len([a for a in self.active_alerts if a.alert_level == AlertLevel.WARNING])

        provider_alerts = {}
        for alert in self.active_alerts:
            if alert.provider not in provider_alerts:
                provider_alerts[alert.provider] = 0
            provider_alerts[alert.provider] += 1

        return {
            'total_active_alerts': active_count,
            'critical_alerts': critical_count,
            'warning_alerts': warning_count,
            'alerts_by_provider': provider_alerts,
            'last_check_time': datetime.now().isoformat()
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

    def detect_anomalies(
        self,
        daily_costs: List[float],
        window_size: int = 7
    ) -> List[bool]:
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
            window = daily_costs[i-window_size:i]
            mean_cost = sum(window) / len(window)

            if len(set(window)) == 1:  # All values are the same
                continue

            variance = sum((x - mean_cost) ** 2 for x in window) / len(window)
            std_dev = variance ** 0.5

            # Check if current value is anomalous
            current_cost = daily_costs[i]
            threshold = mean_cost + (self.sensitivity * std_dev)

            if current_cost > threshold:
                anomalies[i] = True

        return anomalies


class BudgetMonitor:
    """Monitors costs against predefined budgets."""

    def __init__(self):
        self.budgets: Dict[str, Dict[str, float]] = {}

    def set_budget(
        self,
        provider: str,
        period: str,
        amount: float,
        currency: str = 'USD'
    ):
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

        self.budgets[provider][period] = {
            'amount': amount,
            'currency': currency
        }

    def check_budget_status(
        self,
        provider: str,
        period: str,
        current_spend: float,
        currency: str = 'USD'
    ) -> Dict[str, Any]:
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
            return {
                'budget_set': False,
                'status': 'no_budget'
            }

        budget_info = self.budgets[provider][period]
        budget_amount = budget_info['amount']

        # Simple currency handling (in production, use real conversion)
        if currency != budget_info['currency']:
            # For now, assume same currency
            pass

        percentage_used = (current_spend / budget_amount) * 100
        remaining = budget_amount - current_spend

        status = 'ok'
        if percentage_used >= 100:
            status = 'exceeded'
        elif percentage_used >= 90:
            status = 'critical'
        elif percentage_used >= 75:
            status = 'warning'

        return {
            'budget_set': True,
            'budget_amount': budget_amount,
            'current_spend': current_spend,
            'remaining': remaining,
            'percentage_used': percentage_used,
            'status': status,
            'currency': budget_info['currency']
        }