"""
Prometheus metrics export functionality for multi-cloud cost monitoring.

Provides functionality to export cost data as Prometheus metrics that can be
scraped by Prometheus or pushed to Prometheus pushgateway for batch processing.
"""

import asyncio
import logging
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from io import StringIO
import requests

from ..config.settings import get_config
from ..providers.base import ProviderFactory
from ..utils.auth import MultiCloudAuthManager
from ..utils.data_normalizer import CostDataNormalizer
from ..providers.base import TimeGranularity

logger = logging.getLogger(__name__)


@dataclass
class PrometheusConfig:
    """Configuration for Prometheus export."""
    pushgateway_url: Optional[str] = None
    job_name: str = "cost_monitor"
    instance: str = "cost_monitor"
    metrics_prefix: str = "cloud_cost"
    include_labels: bool = True
    pushgateway_timeout: int = 30


class PrometheusMetricsGenerator:
    """Generate Prometheus metrics from cost data."""

    def __init__(self, config: PrometheusConfig = None):
        self.config = config or PrometheusConfig()

    def generate_metrics(
        self,
        cost_data: Dict[str, Any],
        timestamp: Optional[int] = None
    ) -> str:
        """
        Generate Prometheus metrics text format from cost data.

        Args:
            cost_data: Normalized cost data dictionary
            timestamp: Unix timestamp for metrics (defaults to current time)

        Returns:
            Prometheus metrics text format
        """
        if timestamp is None:
            timestamp = int(time.time())

        metrics = StringIO()
        prefix = self.config.metrics_prefix

        # Total cost metric
        if 'total_cost' in cost_data:
            metrics.write(f"# HELP {prefix}_total Total cloud cost across all providers\n")
            metrics.write(f"# TYPE {prefix}_total gauge\n")
            metrics.write(f'{prefix}_total{{currency="{cost_data.get("currency", "USD")}"}} {cost_data["total_cost"]} {timestamp}\n\n')

        # Provider breakdown
        if 'provider_breakdown' in cost_data:
            metrics.write(f"# HELP {prefix}_provider_total Cost by cloud provider\n")
            metrics.write(f"# TYPE {prefix}_provider_total gauge\n")
            for provider, cost in cost_data['provider_breakdown'].items():
                currency = cost_data.get('currency', 'USD')
                metrics.write(f'{prefix}_provider_total{{provider="{provider}",currency="{currency}"}} {cost} {timestamp}\n')
            metrics.write("\n")

        # Service breakdown
        if 'combined_service_breakdown' in cost_data or 'service_breakdown' in cost_data:
            service_data = cost_data.get('combined_service_breakdown', cost_data.get('service_breakdown', {}))
            if service_data:
                metrics.write(f"# HELP {prefix}_service_total Cost by service\n")
                metrics.write(f"# TYPE {prefix}_service_total gauge\n")
                for service, cost in service_data.items():
                    # Parse provider from service name if it's prefixed
                    if ': ' in service:
                        provider, service_name = service.split(': ', 1)
                        provider = provider.lower()
                    else:
                        provider = cost_data.get('provider', 'unknown')
                        service_name = service

                    currency = cost_data.get('currency', 'USD')
                    # Sanitize service name for Prometheus
                    service_clean = self._sanitize_label_value(service_name)
                    metrics.write(f'{prefix}_service_total{{provider="{provider}",service="{service_clean}",currency="{currency}"}} {cost} {timestamp}\n')
                metrics.write("\n")

        # Regional breakdown
        if 'combined_regional_breakdown' in cost_data or 'regional_breakdown' in cost_data:
            regional_data = cost_data.get('combined_regional_breakdown', cost_data.get('regional_breakdown', {}))
            if regional_data:
                metrics.write(f"# HELP {prefix}_region_total Cost by region\n")
                metrics.write(f"# TYPE {prefix}_region_total gauge\n")
                for region, cost in regional_data.items():
                    currency = cost_data.get('currency', 'USD')
                    region_clean = self._sanitize_label_value(region)
                    metrics.write(f'{prefix}_region_total{{region="{region_clean}",currency="{currency}"}} {cost} {timestamp}\n')
                metrics.write("\n")

        # Account breakdown
        if 'combined_account_breakdown' in cost_data:
            metrics.write(f"# HELP {prefix}_account_total Cost by account/subscription/project\n")
            metrics.write(f"# TYPE {prefix}_account_total gauge\n")
            for account_key, account_data in cost_data['combined_account_breakdown'].items():
                provider = account_data.get('provider', 'unknown')
                account_id = account_data.get('account_id', account_key)
                account_name = self._sanitize_label_value(account_data.get('account_name', account_id))
                cost = account_data.get('total_cost', 0)
                currency = account_data.get('currency', 'USD')

                metrics.write(f'{prefix}_account_total{{provider="{provider}",account_id="{account_id}",account_name="{account_name}",currency="{currency}"}} {cost} {timestamp}\n')
            metrics.write("\n")

        # Daily cost trend metrics (for the last 7 days)
        if 'combined_daily_costs' in cost_data:
            daily_costs = cost_data['combined_daily_costs']
            if daily_costs:
                metrics.write(f"# HELP {prefix}_daily_total Daily cost totals\n")
                metrics.write(f"# TYPE {prefix}_daily_total gauge\n")

                # Only include recent days to avoid too many metrics
                recent_days = daily_costs[-7:] if len(daily_costs) > 7 else daily_costs

                for daily_data in recent_days:
                    date_str = daily_data.get('date', '')
                    total_cost = daily_data.get('total_cost', 0)
                    currency = daily_data.get('currency', 'USD')

                    # Convert date to timestamp
                    try:
                        day_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        day_timestamp = int(day_date.timestamp())
                    except (ValueError, AttributeError):
                        day_timestamp = timestamp

                    metrics.write(f'{prefix}_daily_total{{date="{date_str}",currency="{currency}"}} {total_cost} {day_timestamp}\n')

                    # Provider breakdown for daily costs
                    provider_costs = daily_data.get('provider_breakdown', {})
                    for provider, provider_cost in provider_costs.items():
                        metrics.write(f'{prefix}_daily_provider_total{{date="{date_str}",provider="{provider}",currency="{currency}"}} {provider_cost} {day_timestamp}\n')

                metrics.write("\n")

        # Meta metrics
        metrics.write(f"# HELP {prefix}_last_update_timestamp Timestamp of last cost data update\n")
        metrics.write(f"# TYPE {prefix}_last_update_timestamp gauge\n")
        metrics.write(f'{prefix}_last_update_timestamp {timestamp} {timestamp}\n\n')

        if 'start_date' in cost_data and 'end_date' in cost_data:
            metrics.write(f"# HELP {prefix}_data_range_days Number of days covered by the cost data\n")
            metrics.write(f"# TYPE {prefix}_data_range_days gauge\n")
            try:
                start = datetime.fromisoformat(cost_data['start_date'].replace('Z', '+00:00'))
                end = datetime.fromisoformat(cost_data['end_date'].replace('Z', '+00:00'))
                days = (end - start).days + 1
                metrics.write(f'{prefix}_data_range_days {days} {timestamp}\n\n')
            except (ValueError, AttributeError):
                pass

        return metrics.getvalue()

    def _sanitize_label_value(self, value: str) -> str:
        """Sanitize label values for Prometheus."""
        if not value:
            return "unknown"

        # Replace problematic characters
        sanitized = value.replace('"', '\\"').replace('\n', ' ').replace('\r', ' ')
        # Truncate if too long
        return sanitized[:100] if len(sanitized) > 100 else sanitized


class PrometheusExporter:
    """Export cost data to Prometheus."""

    def __init__(self, prometheus_config: PrometheusConfig = None):
        self.config = prometheus_config or PrometheusConfig()
        self.metrics_generator = PrometheusMetricsGenerator(self.config)

    async def export_current_costs(
        self,
        providers: Optional[List[str]] = None,
        days_back: int = 7,
        currency: str = 'USD'
    ) -> str:
        """
        Export current cost data as Prometheus metrics.

        Args:
            providers: List of providers to include (default: all enabled)
            days_back: Number of days of data to include
            currency: Target currency for normalization

        Returns:
            Prometheus metrics text format
        """
        # Load configuration and set up components
        config = get_config()
        auth_manager = MultiCloudAuthManager()
        normalizer = CostDataNormalizer(target_currency=currency)

        # Determine date range
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        # Determine providers to query
        providers_to_query = providers if providers else config.enabled_providers

        # Authenticate and collect cost data
        cost_summaries = []
        authenticated_providers = {}

        for provider_name in providers_to_query:
            if not config.is_provider_enabled(provider_name):
                logger.warning(f"Provider {provider_name} is not enabled, skipping")
                continue

            provider_config = config.get_provider_config(provider_name)
            try:
                provider_instance = ProviderFactory.create_provider(provider_name, provider_config)
                auth_result = await auth_manager.authenticate_provider(provider_name, provider_config)

                if auth_result.success:
                    authenticated_providers[provider_name] = provider_instance
                    cost_summary = await provider_instance.get_cost_data(
                        start_date, end_date, TimeGranularity.DAILY
                    )
                    cost_summaries.append(cost_summary)
                    logger.info(f"Collected cost data for {provider_name}: ${cost_summary.total_cost:.2f}")
                else:
                    logger.error(f"Failed to authenticate {provider_name}: {auth_result.error_message}")

            except Exception as e:
                logger.error(f"Error collecting data for {provider_name}: {e}")

        if not cost_summaries:
            raise ValueError("No cost data available for export")

        # Set providers in normalizer for account name resolution
        normalizer.set_providers(authenticated_providers)

        # Normalize and aggregate data
        if len(cost_summaries) > 1:
            multi_cloud_summary = normalizer.aggregate_multi_cloud_data(cost_summaries)
            cost_data = multi_cloud_summary.to_dict()
        else:
            normalized_data = normalizer.normalize_cost_summary(cost_summaries[0])
            cost_data = normalized_data.to_dict()

        # Generate Prometheus metrics
        metrics_text = self.metrics_generator.generate_metrics(cost_data)

        logger.info(f"Generated Prometheus metrics for {len(cost_summaries)} providers, "
                   f"total cost: ${cost_data['total_cost']:.2f} {currency}")

        return metrics_text

    async def push_to_pushgateway(
        self,
        metrics_text: str,
        pushgateway_url: Optional[str] = None
    ) -> bool:
        """
        Push metrics to Prometheus Pushgateway.

        Args:
            metrics_text: Prometheus metrics in text format
            pushgateway_url: URL of the Pushgateway (overrides config)

        Returns:
            True if push was successful
        """
        url = pushgateway_url or self.config.pushgateway_url
        if not url:
            raise ValueError("Pushgateway URL not configured")

        # Construct push URL
        push_url = f"{url}/metrics/job/{self.config.job_name}/instance/{self.config.instance}"

        try:
            response = requests.post(
                push_url,
                data=metrics_text,
                headers={'Content-Type': 'text/plain; version=0.0.4'},
                timeout=self.config.pushgateway_timeout
            )
            response.raise_for_status()

            logger.info(f"Successfully pushed metrics to Pushgateway: {push_url}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to push metrics to Pushgateway: {e}")
            return False

    def save_metrics_to_file(self, metrics_text: str, filename: str) -> bool:
        """
        Save metrics to a file.

        Args:
            metrics_text: Prometheus metrics text
            filename: Output filename

        Returns:
            True if save was successful
        """
        try:
            with open(filename, 'w') as f:
                f.write(metrics_text)

            logger.info(f"Metrics saved to file: {filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to save metrics to file: {e}")
            return False


async def export_prometheus_metrics(
    output_file: Optional[str] = None,
    pushgateway_url: Optional[str] = None,
    providers: Optional[List[str]] = None,
    days_back: int = 7,
    currency: str = 'USD',
    job_name: str = 'cost_monitor',
    instance: str = 'cost_monitor'
) -> bool:
    """
    Export cost data as Prometheus metrics.

    Args:
        output_file: File to save metrics to (optional)
        pushgateway_url: Pushgateway URL to push metrics to (optional)
        providers: Providers to include (default: all enabled)
        days_back: Days of historical data to include
        currency: Target currency
        job_name: Prometheus job name
        instance: Prometheus instance name

    Returns:
        True if export was successful
    """
    try:
        # Set up exporter
        prometheus_config = PrometheusConfig(
            pushgateway_url=pushgateway_url,
            job_name=job_name,
            instance=instance
        )
        exporter = PrometheusExporter(prometheus_config)

        # Export metrics
        metrics_text = await exporter.export_current_costs(
            providers=providers,
            days_back=days_back,
            currency=currency
        )

        success = True

        # Save to file if specified
        if output_file:
            file_success = exporter.save_metrics_to_file(metrics_text, output_file)
            success = success and file_success

        # Push to Pushgateway if specified
        if pushgateway_url:
            push_success = await exporter.push_to_pushgateway(metrics_text, pushgateway_url)
            success = success and push_success

        # Print metrics if no output specified
        if not output_file and not pushgateway_url:
            print(metrics_text)

        return success

    except Exception as e:
        logger.error(f"Prometheus export failed: {e}")
        return False