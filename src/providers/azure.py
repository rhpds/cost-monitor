"""
Azure Cost Management provider implementation.

Provides Azure-specific cost monitoring functionality using the Azure Cost Management API.
"""

import logging
import json
import csv
import io
import os
import hashlib
import pickle
import base64
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union

try:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.subscription import SubscriptionClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

from .base import (
    CloudCostProvider,
    CostDataPoint,
    CostSummary,
    TimeGranularity,
    AuthenticationError,
    APIError,
    RateLimitError,
    ConfigurationError,
    ProviderFactory
)
from ..utils.auth import AzureAuthenticator

logger = logging.getLogger(__name__)


class AzureCostProvider(CloudCostProvider):
    """Azure Cost Management provider implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.credentials = None
        self.authenticator = AzureAuthenticator(config)

        # Azure subscription configuration (optional - will auto-discover if not provided)
        self.subscription_id = config.get("subscription_id")

        # Initialize persistent cache for cost data
        self._init_cache()

    def _get_provider_name(self) -> str:
        return "azure"

    def _init_cache(self):
        """Initialize persistent cache for cost data."""
        self.cache_dir = os.path.expanduser("~/.cache/cost-monitor/azure")
        os.makedirs(self.cache_dir, exist_ok=True)
        # Cache files for 30 days, older files will be cleaned up
        self.cache_max_age_days = 30
        logger.debug(f"Azure cache initialized at: {self.cache_dir}")

    def _get_cache_file_path(self, cache_key: str) -> str:
        """Get the full path for a cache file."""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")

    def _is_cache_valid(self, cache_file_path: str) -> bool:
        """Check if cache file exists and is not too old."""
        if not os.path.exists(cache_file_path):
            return False

        # Check age
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file_path))
        return file_age.days < self.cache_max_age_days

    def _cleanup_old_cache_files(self):
        """Clean up cache files older than max age."""
        try:
            now = datetime.now()
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.pkl'):
                    file_path = os.path.join(self.cache_dir, filename)
                    file_age = now - datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_age.days > self.cache_max_age_days:
                        os.remove(file_path)
                        logger.debug(f"Removed old cache file: {filename}")
        except Exception as e:
            logger.warning(f"Failed to cleanup old cache files: {e}")

    def _get_cache_key_for_date(self, target_date: date, granularity: str, group_by: List[str] = None) -> str:
        """Generate a unique cache key for a single date's cost data."""
        group_by = group_by or []
        key_data = f"{target_date.isoformat()}:{granularity}:{':'.join(sorted(group_by))}"
        cache_key = hashlib.md5(key_data.encode()).hexdigest()
        logger.debug(f"🟡 Azure: Daily cache key: {target_date} -> {cache_key}")
        return cache_key

    def _save_daily_cache(self, target_date: date, granularity: str, group_by: List[str], data: List[CostDataPoint]) -> None:
        """Save daily cost data to cache."""
        try:
            # Ensure cache directory exists before saving
            os.makedirs(self.cache_dir, exist_ok=True)

            cache_key = self._get_cache_key_for_date(target_date, granularity, group_by)
            cache_file_path = self._get_cache_file_path(cache_key)
            logger.debug(f"🟡 Azure: Saving daily cache for {target_date}: {len(data)} data points")

            # Convert to serializable format
            serializable_data = [
                {
                    'date': point.date.isoformat(),
                    'amount': point.amount,
                    'currency': point.currency,
                    'service_name': point.service_name,
                    'account_id': point.account_id,
                    'resource_id': point.resource_id,
                    'region': point.region,
                    'tags': point.tags or {}
                }
                for point in data
            ]
            with open(cache_file_path, 'wb') as f:
                pickle.dump(serializable_data, f)
            logger.debug(f"✅ Azure: Saved {len(data)} cost data points for {target_date}: {cache_key}")
        except Exception as e:
            logger.error(f"❌ Azure: Failed to save daily cache for {target_date}: {e}")

    def _load_daily_cache(self, target_date: date, granularity: str, group_by: List[str]) -> Optional[List[CostDataPoint]]:
        """Load daily cost data from cache."""
        try:
            cache_key = self._get_cache_key_for_date(target_date, granularity, group_by)
            cache_file_path = self._get_cache_file_path(cache_key)
            if self._is_cache_valid(cache_file_path):
                with open(cache_file_path, 'rb') as f:
                    serializable_data = pickle.load(f)

                # Convert back to CostDataPoint objects
                data_points = []
                for item in serializable_data:
                    data_points.append(CostDataPoint(
                        date=datetime.fromisoformat(item['date']).date(),
                        amount=item['amount'],
                        currency=item['currency'],
                        service_name=item.get('service_name'),
                        account_id=item.get('account_id'),
                        resource_id=item.get('resource_id'),
                        region=item.get('region'),
                        tags=item.get('tags', {})
                    ))

                logger.debug(f"📖 Azure: Loaded {len(data_points)} cached data points for {target_date}")
                return data_points
        except Exception as e:
            logger.debug(f"❌ Azure: Failed to load daily cache for {target_date}: {e}")
        return None

    def _verify_file_integrity(self, data_content: bytes, etag: str = None, content_md5: bytes = None, file_path: str = "") -> bool:
        """
        Verify file integrity using Azure-provided checksums.

        Args:
            data_content: The raw file content as bytes
            etag: Azure blob ETag (can be used for consistency checking)
            content_md5: Azure-provided MD5 hash of the content
            file_path: File path for logging purposes

        Returns:
            True if integrity verification passed or no checksums available, False if verification failed
        """
        try:
            # If we have content MD5 from Azure, verify it
            if content_md5:
                import base64

                # Calculate MD5 of downloaded content
                calculated_md5 = hashlib.md5(data_content).digest()

                # Compare with Azure-provided MD5
                if calculated_md5 == content_md5:
                    logger.info(f"✅ MD5 verification passed for {file_path}")
                    return True
                else:
                    logger.error(f"❌ MD5 verification FAILED for {file_path}")
                    logger.error(f"   Expected: {base64.b64encode(content_md5).decode()}")
                    logger.error(f"   Calculated: {base64.b64encode(calculated_md5).decode()}")
                    return False

            # If no MD5 but we have ETag, log it for reference
            if etag:
                logger.info(f"ℹ️  No MD5 available, but ETag present for integrity reference: {etag[:16]}...")
            else:
                logger.debug(f"No checksums available for {file_path}, skipping integrity verification")

            return True  # Pass if no checksums available

        except Exception as e:
            logger.warning(f"Error during integrity verification for {file_path}: {e}")
            return True  # Don't fail the download due to verification issues

    async def authenticate(self) -> bool:
        """Authenticate with Azure using various methods."""
        try:
            auth_result = await self.authenticator.authenticate()

            if auth_result.success:
                self.credentials = auth_result.credentials
                self._create_cost_management_client()
                self._authenticated = True
                logger.info(f"Azure authentication successful using {auth_result.method}")

                # Clean up old cache files on successful authentication
                self._cleanup_old_cache_files()

                return True
            else:
                logger.error(f"Azure authentication failed: {auth_result.error_message}")
                raise AuthenticationError(f"Azure authentication failed: {auth_result.error_message}")

        except Exception as e:
            logger.error(f"Azure authentication error: {e}")
            raise AuthenticationError(f"Azure authentication error: {e}")

    def _create_cost_management_client(self):
        """Initialize Azure Cost Management API client."""
        if not self.credentials:
            raise ConfigurationError("No authenticated Azure credentials available")

        logger.info("Azure Cost Management API client ready for subscription discovery and querying")

    async def test_connection(self) -> bool:
        """Test the connection to Azure Cost Management API."""
        try:
            await self.ensure_authenticated()

            # Test by trying to list subscriptions
            from azure.mgmt.subscription import SubscriptionClient
            subscription_client = SubscriptionClient(self.credentials)

            # Try to list at least one subscription to verify access
            subscriptions = list(subscription_client.subscriptions.list(top=1))
            logger.info(f"Azure Cost Management API connection successful - found {len(subscriptions)} accessible subscription(s)")
            return True

        except Exception as e:
            logger.error(f"Azure Cost Management API connection test failed: {e}")
            return False

    async def get_cost_data(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None,
        subscription_id: Optional[str] = None
    ) -> CostSummary:
        """Retrieve cost data from Azure Cost Management exports."""
        await self.ensure_authenticated()

        # Validate and normalize dates
        start_date, end_date = self.validate_date_range(start_date, end_date)

        # Prepare request parameters
        granularity_str = "DAILY" if granularity == TimeGranularity.DAILY else "MONTHLY"
        # Default to service-level grouping for dashboard compatibility (like AWS)
        if group_by is None or len(group_by) == 0:
            group_dimensions = ['SERVICE']
        else:
            group_dimensions = group_by

        # Generate list of dates in the range
        date_list = []
        current_date = start_date.date()
        end_date_obj = end_date.date()

        while current_date <= end_date_obj:
            date_list.append(current_date)
            current_date += timedelta(days=1)

        # Try to load cached data for each day
        all_cached_data = []
        missing_dates = []

        for target_date in date_list:
            cached_data_for_date = self._load_daily_cache(target_date, granularity_str, group_dimensions)
            if cached_data_for_date:
                all_cached_data.extend(cached_data_for_date)
                logger.debug(f"🟡 Azure: Cache HIT for {target_date}")
            else:
                missing_dates.append(target_date)
                logger.debug(f"🟡 Azure: Cache MISS for {target_date}")

        # If we have complete cached data for all dates, return it
        if not missing_dates:
            logger.info(f"🟡 Azure: Using fully cached data for {start_date.date()} to {end_date.date()}")
            return CostSummary(
                provider=self._get_provider_name(),
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                total_cost=sum(point.amount for point in all_cached_data),
                currency="USD",
                data_points=all_cached_data,
                last_updated=datetime.now()
            )

        # If we're missing some dates, we need to fetch fresh data
        logger.info(f"🟡 Azure: Cache PARTIAL - missing {len(missing_dates)} dates, fetching fresh data")

        # Use Azure Cost Management REST API for direct cost data retrieval
        cost_summary = await self._get_cost_management_data(start_date, end_date, granularity, group_by=group_dimensions, filter_by=filter_by, subscription_id=subscription_id)

        logger.info(f"🟡 Azure: Parsed {len(cost_summary.data_points)} data points, total cost: ${cost_summary.total_cost}")

        # Save daily cache - group data points by date and save separately
        daily_data = {}
        for point in cost_summary.data_points:
            point_date = point.date
            if point_date not in daily_data:
                daily_data[point_date] = []
            daily_data[point_date].append(point)

        # Save each day's data to its own cache file
        for day_date, day_data_points in daily_data.items():
            self._save_daily_cache(day_date, granularity_str, group_dimensions, day_data_points)

        logger.info(f"🟡 Azure: Saved daily cache for {len(daily_data)} dates")
        return cost_summary

    async def get_current_month_cost(self) -> float:
        """Get the current month's total cost."""
        now = datetime.now()
        start_of_month = now.replace(day=1).date()
        end_date = now.date()

        cost_summary = await self.get_cost_data(start_of_month, end_date)
        return cost_summary.total_cost

    async def get_daily_costs(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date]
    ) -> List[CostDataPoint]:
        """Get daily cost breakdown for the specified period."""
        cost_summary = await self.get_cost_data(
            start_date,
            end_date,
            granularity=TimeGranularity.DAILY
        )

        # Group by date and sum costs
        daily_costs = {}
        for point in cost_summary.data_points:
            date_key = point.date
            if date_key not in daily_costs:
                daily_costs[date_key] = {'amount': 0.0, 'currency': point.currency}
            daily_costs[date_key]['amount'] += point.amount

        return [
            CostDataPoint(
                date=date_key,
                amount=data['amount'],
                currency=data['currency'],
                service_name=None,
                account_id=self.subscription_id,
                region=None,
                tags=None
            )
            for date_key, data in daily_costs.items()
        ]

    async def get_service_costs(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        top_n: int = 10
    ) -> Dict[str, float]:
        """Get cost breakdown by service for the specified period."""
        cost_summary = await self.get_cost_data(
            start_date,
            end_date,
            group_by=['SERVICE']
        )

        # Aggregate costs by service
        service_costs = {}
        for point in cost_summary.data_points:
            if point.service_name:
                service_name = point.service_name
                service_costs[service_name] = service_costs.get(service_name, 0.0) + point.amount

        # Sort by cost and return top N
        sorted_services = sorted(
            service_costs.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return dict(sorted_services[:top_n])

    def get_supported_regions(self) -> List[str]:
        """Get list of supported Azure regions."""
        return [
            'eastus', 'eastus2', 'westus', 'westus2', 'westus3',
            'centralus', 'northcentralus', 'southcentralus', 'westcentralus',
            'canadacentral', 'canadaeast',
            'northeurope', 'westeurope', 'uksouth', 'ukwest',
            'francecentral', 'francesouth', 'germanywestcentral',
            'switzerlandnorth', 'switzerlandwest', 'norwayeast', 'norwaywest',
            'eastasia', 'southeastasia', 'japaneast', 'japanwest',
            'koreacentral', 'koreasouth', 'australiaeast', 'australiasoutheast',
            'australiacentral', 'australiacentral2',
            'southafricanorth', 'southafricawest',
            'brazilsouth', 'brazilsoutheast'
        ]

    def get_supported_services(self) -> List[str]:
        """Get list of supported Azure services for cost monitoring."""
        return [
            'Virtual Machines', 'Storage', 'SQL Database', 'App Service',
            'Azure Functions', 'Azure Kubernetes Service', 'Container Instances',
            'Azure Cache for Redis', 'Azure Cosmos DB', 'Event Hubs',
            'Service Bus', 'Application Gateway', 'Load Balancer',
            'VPN Gateway', 'Azure Firewall', 'Azure Monitor',
            'Log Analytics', 'Application Insights', 'Azure Active Directory',
            'Key Vault', 'Azure DevOps', 'Azure Backup'
        ]

    def normalize_service_name(self, service_name: str) -> str:
        """Normalize Azure service names to a consistent format."""
        if not service_name:
            return "Unknown"

        # Clean up the service name
        service_name = service_name.strip()

        # Azure-specific service name normalization
        service_mapping = {
            # Resource provider mappings
            'Microsoft.Compute': 'Virtual Machines',
            'Microsoft.Storage': 'Storage',
            'Microsoft.Sql': 'SQL Database',
            'Microsoft.Web': 'App Service',
            'Microsoft.ContainerService': 'Azure Kubernetes Service',
            'Microsoft.DocumentDB': 'Azure Cosmos DB',
            'Microsoft.Cache': 'Azure Cache for Redis',
            'Microsoft.Network': 'Networking',
            'Microsoft.KeyVault': 'Key Vault',
            'Microsoft.ContainerInstance': 'Container Instances',
            'Microsoft.Functions': 'Azure Functions',
            'Microsoft.ServiceBus': 'Service Bus',
            'Microsoft.EventHub': 'Event Hubs',
            'Microsoft.Monitor': 'Azure Monitor',
            'Microsoft.Insights': 'Application Insights',
            'Microsoft.OperationalInsights': 'Log Analytics',
            'Microsoft.Authorization': 'Azure Active Directory',
            'Microsoft.RecoveryServices': 'Azure Backup',
            'Microsoft.Automation': 'Azure Automation',
            'Microsoft.DataFactory': 'Data Factory',
            'Microsoft.Logic': 'Logic Apps',
            'Microsoft.CognitiveServices': 'Cognitive Services',
            'Microsoft.MachineLearningServices': 'Machine Learning',
            'Microsoft.Synapse': 'Azure Synapse',
            'Microsoft.HDInsight': 'HDInsight',
            'Microsoft.StreamAnalytics': 'Stream Analytics',
            'Microsoft.PowerBIDedicated': 'Power BI Embedded',

            # Service family name mappings (more user-friendly names)
            'Compute': 'Virtual Machines',
            'Storage': 'Storage',
            'Databases': 'SQL Database',
            'Analytics': 'Analytics Services',
            'Networking': 'Networking',
            'Security': 'Security Services',
            'Identity': 'Azure Active Directory',
            'Developer Tools': 'Developer Services',
            'Integration': 'Integration Services',
            'Management Tools': 'Management Services',
            'AI + Machine Learning': 'AI & ML Services',
            'Internet of Things': 'IoT Services',

            # Meter category mappings
            'Virtual Machines': 'Virtual Machines',
            'Storage': 'Storage',
            'SQL Database': 'SQL Database',
            'App Service': 'App Service',
            'Functions': 'Azure Functions',
            'Container Instances': 'Container Instances',
            'Kubernetes Service': 'Azure Kubernetes Service',
            'Azure Database for MySQL': 'MySQL Database',
            'Azure Database for PostgreSQL': 'PostgreSQL Database',
            'Cosmos DB': 'Azure Cosmos DB',
            'Cache for Redis': 'Azure Cache for Redis',
            'CDN': 'Content Delivery Network',
            'Application Gateway': 'Application Gateway',
            'Load Balancer': 'Load Balancer',
            'VPN Gateway': 'VPN Gateway',
            'ExpressRoute': 'ExpressRoute',
            'Firewall': 'Azure Firewall',
            'Key Vault': 'Key Vault',
            'Monitor': 'Azure Monitor',
            'Log Analytics': 'Log Analytics',
            'Application Insights': 'Application Insights',
            'Service Bus': 'Service Bus',
            'Event Hubs': 'Event Hubs',
            'Data Factory': 'Data Factory',
            'Logic Apps': 'Logic Apps',
            'Cognitive Services': 'Cognitive Services',
            'Machine Learning': 'Machine Learning',
            'Synapse Analytics': 'Azure Synapse',
            'HDInsight': 'HDInsight',
            'Stream Analytics': 'Stream Analytics'
        }

        # Try exact match first
        normalized = service_mapping.get(service_name, service_name)

        # If no exact match, try partial matching for complex service names
        if normalized == service_name:
            for key, value in service_mapping.items():
                if key.lower() in service_name.lower():
                    normalized = value
                    break

        return normalized

    def _aggregate_to_monthly(self, daily_data_points: List[CostDataPoint]) -> List[CostDataPoint]:
        """Aggregate daily data points into monthly buckets."""
        from collections import defaultdict

        # Group by year-month
        monthly_aggregates = defaultdict(lambda: {
            'total_cost': 0.0,
            'currency': 'USD',
            'services': defaultdict(float),
            'regions': defaultdict(float),
            'first_date': None
        })

        for point in daily_data_points:
            # Create year-month key
            year_month = (point.date.year, point.date.month)

            # Aggregate costs
            monthly_aggregates[year_month]['total_cost'] += point.amount
            if point.currency:
                monthly_aggregates[year_month]['currency'] = point.currency

            if point.service_name:
                monthly_aggregates[year_month]['services'][point.service_name] += point.amount
            if point.region:
                monthly_aggregates[year_month]['regions'][point.region] += point.amount

            # Keep track of the first date in the month for the data point
            if not monthly_aggregates[year_month]['first_date']:
                monthly_aggregates[year_month]['first_date'] = point.date.replace(day=1)

        # Convert aggregates back to CostDataPoint objects
        monthly_points = []
        for (year, month), data in monthly_aggregates.items():
            # Use the first day of the month for monthly data points
            month_date = date(year, month, 1)

            monthly_point = CostDataPoint(
                date=month_date,
                amount=data['total_cost'],
                currency=data['currency'],
                service_name=None,  # Individual services are aggregated
                account_id=self.subscription_id,
                region=None,  # Individual regions are aggregated
                tags={
                    'aggregated_services': dict(data['services']),
                    'aggregated_regions': dict(data['regions']),
                    'aggregation_type': 'monthly_from_daily'
                }
            )
            monthly_points.append(monthly_point)

        # Sort by date
        monthly_points.sort(key=lambda x: x.date)
        return monthly_points

    async def _get_cost_management_data(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None,
        subscription_id: Optional[str] = None
    ) -> CostSummary:
        """Get cost data by discovering and querying all available Azure subscriptions individually."""
        import asyncio
        from azure.mgmt.subscription import SubscriptionClient

        # Create clients
        cost_mgmt_client = CostManagementClient(self.credentials)
        subscription_client = SubscriptionClient(self.credentials)

        # Build base query definition
        query_definition = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": start_date,
                "to": end_date
            },
            "dataset": {
                "granularity": "Daily" if granularity == TimeGranularity.DAILY else "Monthly",
                "aggregation": {
                    "totalCost": {
                        "name": "Cost",
                        "function": "Sum"
                    }
                },
                "grouping": []
            }
        }

        # Add grouping dimensions
        if group_by:
            for dimension in group_by:
                if dimension.lower() == 'service':
                    query_definition["dataset"]["grouping"].append({
                        "type": "Dimension",
                        "name": "ServiceName"
                    })
                elif dimension.lower() == 'resource':
                    query_definition["dataset"]["grouping"].append({
                        "type": "Dimension",
                        "name": "ResourceGroup"
                    })

        try:
            # Discover all available subscriptions
            logger.info("🔍 Azure: Discovering available subscriptions...")

            subscriptions = []
            if subscription_id:
                # If specific subscription provided, use only that one
                subscriptions.append({'id': subscription_id, 'name': f'Subscription-{subscription_id}'})
                logger.info(f"🎯 Azure: Using specified subscription: {subscription_id}")
            else:
                # Discover all enabled subscriptions
                for subscription in subscription_client.subscriptions.list():
                    state = subscription.state.value if hasattr(subscription.state, 'value') else str(subscription.state)
                    if state == 'Enabled':
                        subscriptions.append({
                            'id': subscription.subscription_id,
                            'name': subscription.display_name
                        })

                logger.info(f"📊 Azure: Discovered {len(subscriptions)} enabled subscriptions")

            # Implement parallel processing with rate limiting
            semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent requests

            async def query_subscription_with_rate_limit(sub_info):
                async with semaphore:
                    return await self._query_single_subscription(
                        cost_mgmt_client, sub_info, query_definition, start_date, end_date
                    )

            # Execute queries in parallel
            logger.info(f"⚡ Azure: Querying {len(subscriptions)} subscriptions in parallel (max 10 concurrent)...")

            results = await asyncio.gather(
                *[query_subscription_with_rate_limit(sub) for sub in subscriptions],
                return_exceptions=True
            )

            # Process results
            data_points = []
            total_cost = 0.0
            currency = "USD"
            successful_queries = 0
            failed_queries = 0

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_queries += 1
                    logger.warning(f"❌ Azure: Query {i+1} failed: {result}")
                    continue

                if result:
                    successful_queries += 1
                    sub_data_points, sub_cost = result
                    data_points.extend(sub_data_points)
                    total_cost += sub_cost

            logger.info(f"📈 Azure: Completed queries - ✅ {successful_queries} successful, ❌ {failed_queries} failed")
            logger.info(f"💰 Azure: Retrieved {len(data_points)} total data points, ${total_cost:.2f} total cost")

            # Debug: Show sample data points
            if data_points:
                logger.info(f"🔍 Azure: Sample data points:")
                for i, point in enumerate(data_points[:5]):
                    logger.info(f"  {i+1}. {point.date}: ${point.amount:.2f} - {point.service_name} ({point.account_id})")

            return CostSummary(
                provider=self.provider_name,
                start_date=start_date.date(),
                end_date=end_date.date(),
                total_cost=total_cost,
                currency=currency,
                data_points=data_points,
                granularity=granularity,
                last_updated=datetime.now()
            )

        except Exception as e:
            logger.error(f"🟡 Azure: Cost Management API error: {e}")
            raise APIError(f"Azure Cost Management API error: {e}", provider=self.provider_name)

    async def _query_single_subscription(self, cost_mgmt_client, subscription_info, query_definition, start_date, end_date):
        """Query cost data for a single Azure subscription."""
        import asyncio

        subscription_id = subscription_info['id']
        subscription_name = subscription_info['name']

        try:
            scope = f"/subscriptions/{subscription_id}"

            # Execute the query synchronously in thread pool to avoid blocking
            def _execute_query():
                try:
                    return cost_mgmt_client.query.usage(scope=scope, parameters=query_definition)
                except Exception as e:
                    logger.debug(f"🟡 Azure: Query failed for {subscription_name}: {e}")
                    return None

            result = await asyncio.get_event_loop().run_in_executor(None, _execute_query)

            if not result or not hasattr(result, 'rows') or not result.rows:
                return None  # No data for this subscription

            # Process the query result
            data_points = []
            subscription_cost = 0.0

            for row in result.rows:
                cost_amount = float(row[0]) if row[0] is not None else 0.0
                if cost_amount <= 0:
                    continue

                # Handle date field - Azure API returns date as YYYYMMDD integer or string
                date_value = row[1] if len(row) > 1 else None
                if date_value:
                    try:
                        if isinstance(date_value, int):
                            date_str = str(date_value)
                        else:
                            date_str = str(date_value)
                        row_date = datetime.strptime(date_str, '%Y%m%d').date()
                    except (ValueError, TypeError):
                        logger.debug(f"🟡 Azure: Could not parse date: {date_value}")
                        continue
                else:
                    continue

                # Extract service name
                service_name = row[2] if len(row) > 2 else "Unknown"

                data_points.append(CostDataPoint(
                    date=row_date,
                    amount=cost_amount,
                    currency="USD",
                    service_name=service_name,
                    account_id=subscription_id,
                    region=None,
                    tags={
                        'source': 'cost_management_api',
                        'subscription_name': subscription_name,
                        'subscription_id': subscription_id
                    }
                ))

                subscription_cost += cost_amount

            if data_points:
                logger.debug(f"🟡 Azure: {subscription_name}: ${subscription_cost:.2f} ({len(data_points)} entries)")
                return data_points, subscription_cost
            else:
                return None

        except Exception as e:
            logger.debug(f"🟡 Azure: Error querying {subscription_name}: {e}")
            raise e  # Re-raise to be caught by asyncio.gather


# Register the Azure provider with the factory
if AZURE_AVAILABLE:
    ProviderFactory.register_provider("azure", AzureCostProvider)
else:
    logger.warning("Azure SDK not available, Azure provider not registered")
