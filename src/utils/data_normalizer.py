"""
Data normalization utilities for multi-cloud cost monitoring.

Provides unified data structures and normalization functions to standardize
cost data across AWS, Azure, and GCP providers for comparison and analysis.
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Union, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

from ..providers.base import CostDataPoint, CostSummary, TimeGranularity

logger = logging.getLogger(__name__)


class CurrencyCode(Enum):
    """Supported currency codes."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"


@dataclass
class NormalizedCostData:
    """Normalized multi-cloud cost data structure."""
    provider: str
    total_cost: float
    currency: str
    start_date: date
    end_date: date
    granularity: TimeGranularity
    daily_costs: List[Dict[str, Any]] = field(default_factory=list)
    service_breakdown: Dict[str, float] = field(default_factory=dict)
    regional_breakdown: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'provider': self.provider,
            'total_cost': self.total_cost,
            'currency': self.currency,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'granularity': self.granularity.value,
            'daily_costs': self.daily_costs,
            'service_breakdown': self.service_breakdown,
            'regional_breakdown': self.regional_breakdown,
            'metadata': self.metadata
        }


@dataclass
class MultiCloudCostSummary:
    """Aggregated multi-cloud cost summary."""
    total_cost: float
    currency: str
    start_date: date
    end_date: date
    provider_breakdown: Dict[str, float] = field(default_factory=dict)
    combined_daily_costs: List[Dict[str, Any]] = field(default_factory=list)
    combined_service_breakdown: Dict[str, float] = field(default_factory=dict)
    combined_regional_breakdown: Dict[str, float] = field(default_factory=dict)
    combined_account_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    provider_data: Dict[str, NormalizedCostData] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'total_cost': self.total_cost,
            'currency': self.currency,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'provider_breakdown': self.provider_breakdown,
            'combined_daily_costs': self.combined_daily_costs,
            'combined_service_breakdown': self.combined_service_breakdown,
            'combined_regional_breakdown': self.combined_regional_breakdown,
            'combined_account_breakdown': self.combined_account_breakdown,
            'provider_data': {k: v.to_dict() for k, v in self.provider_data.items()}
        }


class ServiceNameNormalizer:
    """Normalizes service names across cloud providers."""

    # Mapping of provider-specific service names to normalized names
    SERVICE_MAPPINGS = {
        'aws': {
            'Amazon EC2-Instance': 'Compute',
            'Amazon Elastic Compute Cloud - Compute': 'Compute',
            'Amazon Simple Storage Service': 'Object Storage',
            'Amazon S3': 'Object Storage',
            'Amazon Relational Database Service': 'Database',
            'Amazon RDS': 'Database',
            'Amazon CloudFront': 'CDN',
            'AWS Lambda': 'Functions',
            'Amazon Lambda': 'Functions',
            'Amazon Elastic Block Store': 'Block Storage',
            'Amazon EBS': 'Block Storage',
            'Amazon Virtual Private Cloud': 'Networking',
            'Amazon VPC': 'Networking',
            'Amazon Route 53': 'DNS',
            'Amazon CloudWatch': 'Monitoring',
            'Amazon DynamoDB': 'NoSQL Database',
            'Amazon ElastiCache': 'Cache',
            'Amazon API Gateway': 'API Gateway',
            'AWS Data Transfer': 'Data Transfer'
        },
        'azure': {
            'Virtual Machines': 'Compute',
            'Microsoft.Compute': 'Compute',
            'Storage': 'Object Storage',
            'Microsoft.Storage': 'Object Storage',
            'SQL Database': 'Database',
            'Microsoft.Sql': 'Database',
            'App Service': 'App Service',
            'Microsoft.Web': 'App Service',
            'Azure Functions': 'Functions',
            'Azure Kubernetes Service': 'Container Service',
            'Microsoft.ContainerService': 'Container Service',
            'Azure Cosmos DB': 'NoSQL Database',
            'Microsoft.DocumentDB': 'NoSQL Database',
            'Azure Cache for Redis': 'Cache',
            'Microsoft.Cache': 'Cache',
            'Networking': 'Networking',
            'Microsoft.Network': 'Networking',
            'Key Vault': 'Key Management',
            'Microsoft.KeyVault': 'Key Management',
            'Application Gateway': 'Load Balancer',
            'Load Balancer': 'Load Balancer',
            'Azure Monitor': 'Monitoring',
            'Log Analytics': 'Logging'
        },
        'gcp': {
            'Compute Engine': 'Compute',
            'Cloud Storage': 'Object Storage',
            'Google Cloud Storage': 'Object Storage',
            'BigQuery': 'Data Warehouse',
            'Cloud SQL': 'Database',
            'App Engine': 'App Service',
            'Cloud Functions': 'Functions',
            'Google Kubernetes Engine': 'Container Service',
            'Kubernetes Engine': 'Container Service',
            'Cloud Run': 'Container Service',
            'Cloud CDN': 'CDN',
            'Cloud Load Balancing': 'Load Balancer',
            'Load Balancing': 'Load Balancer',
            'Cloud DNS': 'DNS',
            'Cloud Pub/Sub': 'Messaging',
            'Cloud Dataflow': 'Data Processing',
            'Firebase': 'Backend as a Service'
        }
    }

    @classmethod
    def normalize(cls, service_name: str, provider: str) -> str:
        """
        Normalize a service name to a common format.

        Args:
            service_name: Original service name
            provider: Cloud provider (aws, azure, gcp)

        Returns:
            Normalized service name
        """
        if not service_name:
            return "Unknown"

        provider = provider.lower()
        mappings = cls.SERVICE_MAPPINGS.get(provider, {})

        # Try exact match first
        if service_name in mappings:
            return mappings[service_name]

        # Try case-insensitive match
        for original, normalized in mappings.items():
            if service_name.lower() == original.lower():
                return normalized

        # Try partial match
        for original, normalized in mappings.items():
            if service_name.lower() in original.lower() or original.lower() in service_name.lower():
                return normalized

        # Return original if no mapping found
        return service_name


class RegionNormalizer:
    """Normalizes region names across cloud providers."""

    # Mapping of provider-specific region names to normalized regions
    REGION_MAPPINGS = {
        'aws': {
            'us-east-1': 'US East (Virginia)',
            'us-east-2': 'US East (Ohio)',
            'us-west-1': 'US West (N. California)',
            'us-west-2': 'US West (Oregon)',
            'eu-west-1': 'Europe (Ireland)',
            'eu-west-2': 'Europe (London)',
            'eu-central-1': 'Europe (Frankfurt)',
            'ap-southeast-1': 'Asia Pacific (Singapore)',
            'ap-southeast-2': 'Asia Pacific (Sydney)',
            'ap-northeast-1': 'Asia Pacific (Tokyo)',
        },
        'azure': {
            'eastus': 'US East (Virginia)',
            'eastus2': 'US East (Virginia)',
            'westus': 'US West (California)',
            'westus2': 'US West (Washington)',
            'northeurope': 'Europe (Ireland)',
            'westeurope': 'Europe (Netherlands)',
            'uksouth': 'Europe (London)',
            'germanywestcentral': 'Europe (Frankfurt)',
            'eastasia': 'Asia Pacific (Hong Kong)',
            'southeastasia': 'Asia Pacific (Singapore)',
            'japaneast': 'Asia Pacific (Tokyo)',
        },
        'gcp': {
            'us-east1': 'US East (South Carolina)',
            'us-east4': 'US East (Virginia)',
            'us-west1': 'US West (Oregon)',
            'us-west2': 'US West (California)',
            'europe-west1': 'Europe (Belgium)',
            'europe-west2': 'Europe (London)',
            'europe-west3': 'Europe (Frankfurt)',
            'asia-southeast1': 'Asia Pacific (Singapore)',
            'asia-northeast1': 'Asia Pacific (Tokyo)',
            'australia-southeast1': 'Asia Pacific (Sydney)',
        }
    }

    @classmethod
    def normalize(cls, region: str, provider: str) -> str:
        """
        Normalize a region name to a common format.

        Args:
            region: Original region name
            provider: Cloud provider (aws, azure, gcp)

        Returns:
            Normalized region name
        """
        if not region:
            return "Unknown"

        provider = provider.lower()
        mappings = cls.REGION_MAPPINGS.get(provider, {})

        return mappings.get(region, region)


class CurrencyConverter:
    """Simple currency converter for cost normalization."""

    # Mock exchange rates - in production, use a real currency API
    EXCHANGE_RATES = {
        'USD': 1.0,
        'EUR': 1.1,
        'GBP': 1.25,
        'JPY': 0.0067,
        'CAD': 0.74,
        'AUD': 0.66
    }

    @classmethod
    def convert(cls, amount: float, from_currency: str, to_currency: str = 'USD') -> float:
        """
        Convert amount between currencies.

        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Converted amount
        """
        if from_currency == to_currency:
            return amount

        from_rate = cls.EXCHANGE_RATES.get(from_currency.upper(), 1.0)
        to_rate = cls.EXCHANGE_RATES.get(to_currency.upper(), 1.0)

        # Convert to USD first, then to target currency
        usd_amount = amount / from_rate
        return usd_amount * to_rate


class CostDataNormalizer:
    """Main class for normalizing multi-cloud cost data."""

    def __init__(self, target_currency: str = 'USD'):
        """
        Initialize the normalizer.

        Args:
            target_currency: Target currency for normalization
        """
        self.target_currency = target_currency.upper()
        self.service_normalizer = ServiceNameNormalizer()
        self.region_normalizer = RegionNormalizer()
        self.currency_converter = CurrencyConverter()
        self.providers = {}

    def set_providers(self, providers: Dict[str, Any]):
        """Set provider instances for accessing cached data like account names."""
        self.providers = providers

    def normalize_cost_summary(self, cost_summary: CostSummary) -> NormalizedCostData:
        """
        Normalize a cost summary from a single provider.

        Args:
            cost_summary: Cost summary to normalize

        Returns:
            Normalized cost data
        """
        # Convert total cost to target currency
        normalized_total = self.currency_converter.convert(
            cost_summary.total_cost,
            cost_summary.currency,
            self.target_currency
        )

        # Process daily costs
        daily_costs = self._normalize_daily_costs(cost_summary)

        # Process service breakdown
        service_breakdown = self._normalize_service_breakdown(cost_summary)

        # Process regional breakdown
        regional_breakdown = self._normalize_regional_breakdown(cost_summary)

        return NormalizedCostData(
            provider=cost_summary.provider,
            total_cost=normalized_total,
            currency=self.target_currency,
            start_date=cost_summary.start_date,
            end_date=cost_summary.end_date,
            granularity=cost_summary.granularity,
            daily_costs=daily_costs,
            service_breakdown=service_breakdown,
            regional_breakdown=regional_breakdown,
            metadata={
                'original_currency': cost_summary.currency,
                'data_points_count': len(cost_summary.data_points),
                'last_updated': cost_summary.last_updated.isoformat()
            }
        )

    def _normalize_daily_costs(self, cost_summary: CostSummary) -> List[Dict[str, Any]]:
        """Normalize daily cost data."""
        daily_totals = defaultdict(float)

        # Aggregate by date
        for point in cost_summary.data_points:
            converted_amount = self.currency_converter.convert(
                point.amount,
                point.currency,
                self.target_currency
            )
            daily_totals[point.date] += converted_amount

        # Convert to list format
        return [
            {
                'date': date_key.isoformat(),
                'cost': amount,
                'currency': self.target_currency
            }
            for date_key, amount in sorted(daily_totals.items())
        ]

    def _normalize_service_breakdown(self, cost_summary: CostSummary) -> Dict[str, float]:
        """Normalize service breakdown data."""
        service_totals = defaultdict(float)

        for point in cost_summary.data_points:
            if point.service_name:
                # Normalize service name
                normalized_service = self.service_normalizer.normalize(
                    point.service_name,
                    cost_summary.provider
                )

                # Convert currency
                converted_amount = self.currency_converter.convert(
                    point.amount,
                    point.currency,
                    self.target_currency
                )

                service_totals[normalized_service] += converted_amount

        return dict(service_totals)

    def _normalize_regional_breakdown(self, cost_summary: CostSummary) -> Dict[str, float]:
        """Normalize regional breakdown data."""
        regional_totals = defaultdict(float)

        for point in cost_summary.data_points:
            if point.region:
                # Normalize region name
                normalized_region = self.region_normalizer.normalize(
                    point.region,
                    cost_summary.provider
                )

                # Convert currency
                converted_amount = self.currency_converter.convert(
                    point.amount,
                    point.currency,
                    self.target_currency
                )

                regional_totals[normalized_region] += converted_amount

        return dict(regional_totals)

    def aggregate_multi_cloud_data(
        self,
        cost_summaries: List[CostSummary]
    ) -> MultiCloudCostSummary:
        """
        Aggregate cost data from multiple cloud providers.

        Args:
            cost_summaries: List of cost summaries from different providers

        Returns:
            Aggregated multi-cloud cost summary
        """
        if not cost_summaries:
            raise ValueError("No cost summaries provided")

        # Find common date range - normalize all dates to date objects for comparison
        start_dates = []
        end_dates = []
        for cs in cost_summaries:
            # Convert datetime objects to date objects for consistent comparison
            start_date_normalized = cs.start_date.date() if isinstance(cs.start_date, datetime) else cs.start_date
            end_date_normalized = cs.end_date.date() if isinstance(cs.end_date, datetime) else cs.end_date
            start_dates.append(start_date_normalized)
            end_dates.append(end_date_normalized)

        start_date = max(start_dates)
        end_date = min(end_dates)

        import time

        # Normalize individual provider data
        normalize_start = time.time()
        normalized_data = {}
        provider_breakdown = {}
        total_cost = 0.0

        for cost_summary in cost_summaries:
            normalized = self.normalize_cost_summary(cost_summary)
            normalized_data[normalized.provider] = normalized
            provider_breakdown[normalized.provider] = normalized.total_cost
            total_cost += normalized.total_cost
        normalize_time = time.time() - normalize_start

        # Aggregate daily costs
        daily_start = time.time()
        combined_daily = self._aggregate_daily_costs(normalized_data.values())
        daily_time = time.time() - daily_start

        # Aggregate service breakdown
        service_start = time.time()
        combined_services = self._aggregate_service_breakdown(normalized_data.values())
        service_time = time.time() - service_start

        # Aggregate regional breakdown
        region_start = time.time()
        combined_regions = self._aggregate_regional_breakdown(normalized_data.values())
        region_time = time.time() - region_start

        # Aggregate account breakdown
        account_start = time.time()
        combined_accounts = self._aggregate_account_breakdown(cost_summaries)
        account_time = time.time() - account_start

        # Log performance breakdown
        total_normalize = normalize_time + daily_time + service_time + region_time + account_time
        if total_normalize > 0.5:  # Only log if it takes more than 500ms
            logger.info(f"🐌 Data normalization performance: normalize:{normalize_time:.3f}s, daily:{daily_time:.3f}s, service:{service_time:.3f}s, region:{region_time:.3f}s, account:{account_time:.3f}s, total:{total_normalize:.3f}s")

        return MultiCloudCostSummary(
            total_cost=total_cost,
            currency=self.target_currency,
            start_date=start_date,
            end_date=end_date,
            provider_breakdown=provider_breakdown,
            combined_daily_costs=combined_daily,
            combined_service_breakdown=combined_services,
            combined_regional_breakdown=combined_regions,
            combined_account_breakdown=combined_accounts,
            provider_data=normalized_data
        )

    def _aggregate_daily_costs(self, normalized_data: List[NormalizedCostData]) -> List[Dict[str, Any]]:
        """Aggregate daily costs across providers."""
        all_dates = set()
        for data in normalized_data:
            for daily_cost in data.daily_costs:
                all_dates.add(daily_cost['date'])

        combined_daily = []
        for date_str in sorted(all_dates):
            total_for_date = 0.0
            provider_costs = {}

            for data in normalized_data:
                for daily_cost in data.daily_costs:
                    if daily_cost['date'] == date_str:
                        total_for_date += daily_cost['cost']
                        provider_costs[data.provider] = daily_cost['cost']
                        break

            combined_daily.append({
                'date': date_str,
                'total_cost': total_for_date,
                'currency': self.target_currency,
                'provider_breakdown': provider_costs
            })

        return combined_daily

    def _aggregate_service_breakdown(self, normalized_data: List[NormalizedCostData]) -> Dict[str, float]:
        """Aggregate service breakdown across providers with provider prefixes."""
        combined_services = defaultdict(float)

        for data in normalized_data:
            provider_prefix = data.provider.upper()
            for service, cost in data.service_breakdown.items():
                # Prefix service name with provider for clarity in multi-cloud view
                service_key = f"{provider_prefix}: {service}"
                combined_services[service_key] += cost

        return dict(combined_services)

    def _aggregate_regional_breakdown(self, normalized_data: List[NormalizedCostData]) -> Dict[str, float]:
        """Aggregate regional breakdown across providers."""
        combined_regions = defaultdict(float)

        for data in normalized_data:
            for region, cost in data.regional_breakdown.items():
                combined_regions[region] += cost

        return dict(combined_regions)

    def _aggregate_account_breakdown(self, cost_summaries: List[CostSummary]) -> Dict[str, Dict[str, Any]]:
        """Aggregate account/project/subscription breakdown across providers."""
        account_totals = defaultdict(float)
        account_details = {}

        # Map of provider to account type label
        provider_labels = {
            'aws': 'AWS Account',
            'azure': 'Azure Subscription',
            'gcp': 'GCP Project'
        }

        for cost_summary in cost_summaries:
            provider = cost_summary.provider.lower()

            for point in cost_summary.data_points:
                if point.account_id:
                    # Convert currency to target currency
                    converted_amount = self.currency_converter.convert(
                        point.amount,
                        point.currency,
                        self.target_currency
                    )

                    # Create unique key for account across providers
                    account_key = f"{provider}:{point.account_id}"
                    account_totals[account_key] += converted_amount


                    # Store account details (only once per account)
                    if account_key not in account_details:
                        # Get account name from tags if available, otherwise use account_id
                        account_name = point.account_id
                        if point.tags and 'subscription_display_name' in point.tags:
                            # Use Azure's subscription display name (includes both name and ID)
                            account_name = point.tags['subscription_display_name']
                        elif point.tags and 'account_name' in point.tags:
                            account_name = point.tags['account_name']
                        elif point.tags and 'project_name' in point.tags:
                            account_name = point.tags['project_name']
                        elif point.tags and 'subscription_name' in point.tags:
                            account_name = point.tags['subscription_name']
                        elif provider == 'aws' and point.account_id:
                            # Try to get account name from AWS provider's cache
                            account_name = self._get_aws_account_name_from_cache(point.account_id)

                        account_details[account_key] = {
                            'account_id': point.account_id,
                            'account_name': account_name,
                            'provider': provider,
                            'provider_label': provider_labels.get(provider, f'{provider.title()} Account'),
                            'currency': self.target_currency
                        }

        # Combine totals with details and sort by cost (descending)
        combined_accounts = {}
        for account_key, total_cost in account_totals.items():
            details = account_details[account_key]
            details['total_cost'] = total_cost
            details['percentage'] = (total_cost / sum(account_totals.values()) * 100) if account_totals else 0
            combined_accounts[account_key] = details

        return combined_accounts

    def _get_aws_account_name_from_cache(self, account_id: str) -> str:
        """Get AWS account name from provider cache or return raw account ID."""
        # Try to get from AWS provider cache
        aws_provider = self.providers.get('aws')
        if aws_provider and hasattr(aws_provider, 'account_names_cache'):
            cached_name = aws_provider.account_names_cache.get(account_id)
            if cached_name and cached_name != account_id:
                # Format as "Name (account_id)" if we have a real name
                return f"{cached_name} ({account_id})"

        # Return raw account ID if no cached name available - will be resolved later
        return account_id

