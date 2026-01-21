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
    from azure.storage.blob import BlobServiceClient
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.costmanagement import CostManagementClient
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
        self.blob_service_client = None

        # Export configuration for cost data
        self.export_config = config.get("export", {})
        self.storage_account_name = self.export_config.get("storage_account")
        self.export_name = self.export_config.get("export_name")
        self.container_name = self.export_config.get("container", "cost-exports")

        # Azure subscription configuration
        self.subscription_id = config.get("subscription_id")

        # Export data supports both daily and monthly granularities
        # MONTHLY is handled with client-side aggregation of daily data

        # Initialize persistent CSV cache
        self._init_csv_cache()

    def _get_provider_name(self) -> str:
        return "azure"

    def _init_csv_cache(self):
        """Initialize persistent CSV file cache."""
        self.cache_dir = os.path.expanduser("~/.cache/cost-monitor/azure")
        os.makedirs(self.cache_dir, exist_ok=True)
        # Cache files for 30 days, older files will be cleaned up
        self.cache_max_age_days = 30
        logger.debug(f"Azure CSV cache initialized at: {self.cache_dir}")

    def _get_file_cache_key(self, blob_path: str, file_size: int = None, last_modified: str = None) -> str:
        """Generate a unique cache key for a blob file."""
        # Use blob path + size + last_modified to create unique key
        key_data = f"{blob_path}:{file_size}:{last_modified}"
        return hashlib.md5(key_data.encode()).hexdigest()

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

    def _save_to_cache(self, cache_key: str, data: List[Dict]) -> None:
        """Save processed CSV data to cache."""
        try:
            # Ensure cache directory exists before saving
            os.makedirs(self.cache_dir, exist_ok=True)

            cache_file_path = self._get_cache_file_path(cache_key)
            with open(cache_file_path, 'wb') as f:
                pickle.dump(data, f)
            logger.debug(f"Saved {len(data)} rows to cache: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to save to cache: {e}")

    def _load_from_cache(self, cache_key: str) -> Optional[List[Dict]]:
        """Load processed CSV data from cache."""
        try:
            cache_file_path = self._get_cache_file_path(cache_key)
            if self._is_cache_valid(cache_file_path):
                with open(cache_file_path, 'rb') as f:
                    data = pickle.load(f)
                logger.info(f"Loaded {len(data)} rows from cache: {cache_key}")
                return data
        except Exception as e:
            logger.warning(f"Failed to load from cache: {e}")
        return None

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
        """Create Azure Blob Storage client for export data access."""
        if not self.credentials:
            raise ConfigurationError("No authenticated Azure credentials available")

        # Validate export configuration
        if not self.storage_account_name or not self.export_name:
            raise ConfigurationError("Export configuration requires storage_account and export_name")

        # Create Blob Storage client for export data access
        account_url = f"https://{self.storage_account_name}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(
            account_url=account_url,
            credential=self.credentials
        )
        logger.info(f"Initialized Azure Blob Storage client for account: {self.storage_account_name}")
        logger.info(f"Using export: {self.export_name} from container: {self.container_name}")

    async def test_connection(self) -> bool:
        """Test the connection to Azure Blob Storage for export access."""
        try:
            await self.ensure_authenticated()

            if not self.blob_service_client:
                logger.error("Blob Storage client not initialized")
                return False

            # Test blob storage access by listing containers
            containers = list(self.blob_service_client.list_containers(results_per_page=1))
            logger.info("Azure Blob Storage connection successful")
            return True

        except Exception as e:
            logger.error(f"Azure Blob Storage connection test failed: {e}")
            return False

    async def get_cost_data(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
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
        cost_summary = await self._get_cost_management_data(start_date, end_date, granularity, group_by=group_dimensions, filter_by=filter_by)

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
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """Get cost data using Azure Cost Management REST API directly."""
        import asyncio

        # Get subscription ID from config
        subscription_id = self.config.get('subscription_id')
        if not subscription_id:
            raise ConfigurationError("Azure subscription_id is required for Cost Management API")

        # Create Cost Management client
        cost_mgmt_client = CostManagementClient(self.credentials)

        # Build query parameters
        query_definition = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": start_date.strftime('%Y-%m-%dT00:00:00+00:00'),
                "to": end_date.strftime('%Y-%m-%dT23:59:59+00:00')
            },
            "dataSet": {
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
                    query_definition["dataSet"]["grouping"].append({
                        "type": "Dimension",
                        "name": "ServiceName"
                    })
                elif dimension.lower() == 'resource':
                    query_definition["dataSet"]["grouping"].append({
                        "type": "Dimension",
                        "name": "ResourceGroup"
                    })

        try:
            # Execute query in a thread since the Azure SDK is synchronous
            def _execute_query():
                scope = f"/subscriptions/{subscription_id}"
                return cost_mgmt_client.query.usage(scope, query_definition)

            query_result = await asyncio.get_event_loop().run_in_executor(None, _execute_query)

            # Parse the result
            data_points = []
            total_cost = 0.0
            currency = "USD"

            if hasattr(query_result, 'rows') and query_result.rows:
                for row in query_result.rows:
                    # Row format: [cost, date, service_name, ...]
                    cost_amount = float(row[0]) if row[0] is not None else 0.0

                    # Handle date field - can be string or integer from Azure API
                    date_value = row[1]
                    if isinstance(date_value, int):
                        date_str = str(date_value)
                    else:
                        date_str = str(date_value)
                    row_date = datetime.strptime(date_str, '%Y%m%d').date()

                    service_name = row[2] if len(row) > 2 else "Unknown"

                    data_points.append(CostDataPoint(
                        date=row_date,
                        amount=cost_amount,
                        currency=currency,
                        service_name=service_name,
                        account_id=subscription_id,
                        region=None,
                        tags={'source': 'cost_management_api'}
                    ))
                    total_cost += cost_amount

            logger.info(f"🟡 Azure: Retrieved {len(data_points)} data points via Cost Management API, total: ${total_cost}")

            # Debug: Show some sample data points
            if data_points:
                logger.info(f"🟡 Azure: Sample data points:")
                for i, point in enumerate(data_points[:3]):
                    logger.info(f"🟡 Azure:   {i+1}. {point.date}: ${point.amount:.2f} - {point.service_name}")

            return CostSummary(
                total_cost=total_cost,
                currency=currency,
                data_points=data_points,
                period_start=start_date.date(),
                period_end=end_date.date(),
                granularity=granularity,
                last_updated=datetime.now()
            )

        except Exception as e:
            logger.error(f"🟡 Azure: Cost Management API error: {e}")
            # Fallback to export data if REST API fails
            logger.warning("🟡 Azure: Falling back to export data retrieval")
            return await self._get_export_cost_data(start_date, end_date, granularity, group_by, filter_by)

    async def _get_export_cost_data(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """Get cost data from Azure Cost Management exports stored in Azure Blob Storage."""
        if not self.blob_service_client:
            raise ConfigurationError("Blob Storage client not initialized for export access")

        logger.info(f"Reading Azure cost data from exports in storage account: {self.storage_account_name}")

        try:
            # Find the most recent export data that covers our date range
            export_data = await self._find_and_read_export_data(start_date, end_date)

            if not export_data:
                logger.warning("No export data found for the specified date range")
                return CostSummary(
                    provider=self.provider_name,
                    start_date=start_date.date(),
                    end_date=end_date.date(),
                    total_cost=0.0,
                    currency='USD',
                    data_points=[],
                    granularity=granularity,
                    last_updated=datetime.now()
                )

            # Parse the export data into our standard format
            return await self._parse_export_data(export_data, start_date, end_date, granularity, group_by)

        except Exception as e:
            logger.error(f"Failed to read Azure export data: {e}")
            raise APIError(f"Failed to read Azure export data: {e}", provider=self.provider_name)

    async def _find_and_read_export_data(self, start_date: datetime, end_date: datetime) -> Optional[List[Dict]]:
        """Find and read the most recent export data that covers the requested date range."""
        try:
            # List containers to find export data
            container_names = await self._get_export_containers()

            for container_name in container_names:
                logger.debug(f"Checking container: {container_name}")

                # Look for export folders in the container
                export_folders = await self._list_export_folders(container_name, start_date, end_date)

                if export_folders:
                    # Use ALL export folders that have overlap with the requested date range
                    all_data = []

                    # Process ALL export folders to get complete data
                    processed_folders = 0

                    for folder in export_folders:
                        logger.info(f"Using export folder: {folder} in container: {container_name}")
                        folder_data = await self._read_export_folder(container_name, folder)
                        if folder_data:
                            all_data.extend(folder_data)
                            processed_folders += 1
                        else:
                            logger.warning(f"No data found in export folder: {folder}")

                    logger.info(f"Processed {processed_folders} export folders total")

                    return all_data

            return None

        except Exception as e:
            logger.error(f"Error finding export data: {e}")
            raise

    async def _get_export_containers(self) -> List[str]:
        """Get list of containers that might contain export data."""
        try:
            containers = []
            container_list = self.blob_service_client.list_containers()

            # Look for containers that might contain our export
            target_containers = [self.container_name, 'cost-exports', 'exports']

            for container in container_list:
                if container.name in target_containers or self.export_name.lower() in container.name.lower():
                    containers.append(container.name)
                    logger.debug(f"Found potential export container: {container.name}")

            # If no specific containers found, try the configured container
            if not containers and self.container_name:
                containers = [self.container_name]

            return containers

        except Exception as e:
            logger.error(f"Error listing containers: {e}")
            return []

    async def _list_export_folders(self, container_name: str, start_date: datetime, end_date: datetime) -> List[str]:
        """List export folders in a container that contain data for our date range."""
        import re
        from datetime import datetime as dt, timedelta

        try:
            blob_list = self.blob_service_client.get_container_client(container_name).list_blobs()
            folder_candidates = []

            # Look for folders that match our export name and parse date ranges
            for blob in blob_list:
                blob_path = blob.name
                if self.export_name in blob_path and '/' in blob_path:
                    # Extract folder path - look for date range pattern
                    path_parts = blob_path.split('/')

                    # Look for date range patterns like YYYYMMDD-YYYYMMDD in path parts
                    for part in path_parts:
                        date_range_match = re.match(r'(\d{8})-(\d{8})', part)
                        if date_range_match:
                            try:
                                folder_start_str = date_range_match.group(1)
                                folder_end_str = date_range_match.group(2)

                                # Parse folder date range
                                folder_start = dt.strptime(folder_start_str, '%Y%m%d').date()
                                folder_end = dt.strptime(folder_end_str, '%Y%m%d').date()

                                # Check if this folder's date range overlaps with our requested range
                                requested_start = start_date.date() if hasattr(start_date, 'date') else start_date
                                requested_end = end_date.date() if hasattr(end_date, 'date') else end_date

                                # Check for overlap: folder_start <= requested_end and folder_end >= requested_start
                                if folder_start <= requested_end and folder_end >= requested_start:
                                    # Build folder path up to the date range part
                                    folder_path_parts = []
                                    for i, path_part in enumerate(path_parts):
                                        folder_path_parts.append(path_part)
                                        if path_part == part:  # Found the date range part
                                            break

                                    if len(folder_path_parts) >= 2:
                                        # Use path up to the date range directory
                                        folder_path = '/'.join(folder_path_parts[:-1])  # Exclude the date range part for now

                                        folder_candidates.append({
                                            'path': folder_path,
                                            'date_range_folder': part,
                                            'start_date': folder_start,
                                            'end_date': folder_end,
                                            'overlap_days': min(folder_end, requested_end) - max(folder_start, requested_start) + timedelta(days=1),
                                            'recency_score': folder_end  # More recent end dates score higher
                                        })

                                        logger.debug(f"Found relevant export folder: {folder_path}/{part} "
                                                   f"(covers {folder_start} to {folder_end})")
                                        break

                            except ValueError as e:
                                logger.debug(f"Could not parse date range from {part}: {e}")
                                continue

            # Sort candidates by overlap first (most overlap), then by recency
            # This ensures we get the export with the best coverage for the requested date range
            folder_candidates.sort(key=lambda x: (-x['overlap_days'].days, -x['recency_score'].toordinal()))

            # Return the full folder paths including date range
            result_folders = []
            for candidate in folder_candidates:
                full_path = f"{candidate['path']}/{candidate['date_range_folder']}"
                result_folders.append(full_path)
                logger.debug(f"Export folder candidate: {full_path} "
                            f"(covers {candidate['start_date']} to {candidate['end_date']}, "
                            f"overlap: {candidate['overlap_days'].days} days)")

            if not result_folders:
                logger.warning(f"No export folders found covering date range {start_date.date()} to {end_date.date()}")

                # Fall back to finding any export folders for debugging
                fallback_folders = set()
                for blob in blob_list:
                    blob_path = blob.name
                    if self.export_name in blob_path and '/' in blob_path:
                        path_parts = blob_path.split('/')
                        if len(path_parts) >= 3:
                            folder_path = '/'.join(path_parts[:3])  # Include more path parts for debugging
                            fallback_folders.add(folder_path)

                if fallback_folders:
                    logger.info(f"Available export folders (may not cover requested dates): {sorted(fallback_folders)}")
                    result_folders = sorted(list(fallback_folders))

            return result_folders

        except Exception as e:
            logger.error(f"Error listing export folders in container {container_name}: {e}")
            return []

    async def _read_export_folder(self, container_name: str, folder_path: str) -> List[Dict]:
        """Read all cost data from an export folder."""
        try:
            container_client = self.blob_service_client.get_container_client(container_name)

            # First, look for manifest.json to understand the file structure
            manifest_path = f"{folder_path}/manifest.json"
            manifest_data = None

            try:
                manifest_blob = container_client.download_blob(manifest_path)
                manifest_content = manifest_blob.readall().decode('utf-8')
                manifest_data = json.loads(manifest_content)
                logger.debug(f"Found manifest file: {manifest_path}")
            except Exception:
                logger.debug(f"No manifest file found at {manifest_path}, will scan for CSV files")

            # Get list of data files
            data_files = []
            if manifest_data and 'blobs' in manifest_data:
                # Use manifest to identify data files
                for blob_info in manifest_data['blobs']:
                    if blob_info.get('blobName', '').endswith('.csv'):
                        data_files.append(blob_info['blobName'])
            else:
                # Scan for CSV files in the folder
                blob_list = container_client.list_blobs(name_starts_with=folder_path + '/')
                for blob in blob_list:
                    if blob.name.endswith('.csv') and 'manifest' not in blob.name.lower():
                        data_files.append(blob.name)

            logger.info(f"Found {len(data_files)} data files in {folder_path}")

            # Read and combine all data files
            all_data = []
            max_files = len(data_files)  # Process ALL export files to get complete data

            for i, data_file in enumerate(data_files[:max_files]):
                try:
                    logger.debug(f"Processing file {i+1}/{max_files}: {data_file}")

                    # Get blob properties for cache key generation and integrity verification
                    blob_props = container_client.get_blob_client(data_file).get_blob_properties()
                    file_size = blob_props.size or 0
                    last_modified = str(blob_props.last_modified)

                    # Get Azure blob checksums for integrity verification
                    etag = blob_props.etag.strip('"') if blob_props.etag else None
                    content_md5 = blob_props.content_settings.content_md5 if blob_props.content_settings else None

                    logger.info(f"Blob {data_file}: size={file_size}, etag={etag}, content_md5={content_md5}")

                    # Generate cache key with integrity information
                    integrity_info = f"{etag}:{base64.b64encode(content_md5).decode() if content_md5 else 'no-md5'}"
                    cache_key = self._get_file_cache_key(data_file, file_size, f"{last_modified}:{integrity_info}")

                    # Try to load from cache first
                    cached_data = self._load_from_cache(cache_key)
                    if cached_data is not None:
                        logger.info(f"Using cached data for {data_file} ({len(cached_data)} rows)")
                        all_data.extend(cached_data)
                    else:
                        # Download and process the file
                        blob_data = container_client.download_blob(data_file)

                        # Read entire file to get complete data (removed file size limits)
                        logger.info(f"Reading complete file ({file_size} bytes): {data_file}")
                        raw_content = blob_data.readall()

                        # Verify file integrity using Azure checksums (if enabled)
                        verify_checksums = self.export_config.get("verify_checksums", True)
                        if verify_checksums:
                            integrity_ok = self._verify_file_integrity(
                                data_content=raw_content,
                                etag=etag,
                                content_md5=content_md5,
                                file_path=data_file
                            )
                        else:
                            logger.debug(f"Checksum verification disabled for {data_file}")
                            integrity_ok = True

                        if not integrity_ok:
                            logger.error(f"❌ File integrity verification failed for {data_file}")
                            # Remove any potentially corrupt cached data for this file
                            try:
                                cache_file_path = self._get_cache_file_path(cache_key)
                                if os.path.exists(cache_file_path):
                                    os.remove(cache_file_path)
                                    logger.info(f"🗑️  Removed potentially corrupt cache file for {data_file}")
                            except Exception as e:
                                logger.warning(f"Failed to remove corrupt cache file: {e}")
                            continue

                        csv_content = raw_content.decode('utf-8', errors='ignore')

                        # Parse CSV content
                        csv_reader = csv.DictReader(io.StringIO(csv_content))
                        file_data = list(csv_reader)

                        # Save to cache for future use (only if integrity verification passed)
                        self._save_to_cache(cache_key, file_data)

                        all_data.extend(file_data)
                        logger.debug(f"Read and cached {len(file_data)} rows from {data_file}")

                    # Break early if we have enough data to prevent excessive processing
                    if len(all_data) > 200000:  # Much higher limit to capture complete daily data
                        logger.info(f"Processed {len(all_data)} rows, stopping early to prevent excessive processing")
                        break

                except Exception as e:
                    logger.warning(f"Error reading data file {data_file}: {e}")
                    continue

            logger.info(f"Total rows read from export: {len(all_data)}")
            return all_data

        except Exception as e:
            logger.error(f"Error reading export folder {folder_path}: {e}")
            return []

    async def _parse_export_data(self, export_data: List[Dict], start_date: datetime, end_date: datetime, granularity: TimeGranularity, group_by: Optional[List[str]] = None) -> CostSummary:
        """Parse export data into our standard CostSummary format."""
        try:
            logger.info(f"Parsing {len(export_data)} export data rows for date range {start_date.date()} to {end_date.date()}")
            data_points = []
            total_cost = 0.0
            currencies = set()

            # Group data by date and by service
            daily_costs = {}
            service_date_costs = {}  # Track costs by (date, service) combination

            # Deduplication tracking: prevent counting the same cost multiple times
            # Key: (date, resource_id, meter_id, cost_amount, subscription_id)
            seen_costs = set()

            # Debug: Check first few rows to understand data structure
            if export_data:
                sample_row = export_data[0]
                logger.debug(f"Sample row keys: {list(sample_row.keys())}")
                date_fields = ['date', 'billingPeriodStartDate', 'servicePeriodStartDate']
                cost_fields = ['costInBillingCurrency', 'costInPricingCurrency', 'costInUsd', 'paygCostInBillingCurrency']
                logger.debug(f"Sample date fields: {[(field, sample_row.get(field)) for field in date_fields if field in sample_row]}")
                logger.debug(f"Sample cost fields: {[(field, sample_row.get(field)) for field in cost_fields if field in sample_row]}")

            rows_processed = 0
            rows_with_date = 0
            rows_in_range = 0
            rows_with_cost = 0

            for row in export_data:
                try:
                    rows_processed += 1

                    # Extract date from the export data
                    # Azure exports use lowercase field names: 'date', 'billingPeriodStartDate', 'servicePeriodStartDate'
                    date_str = row.get('date') or row.get('billingPeriodStartDate') or row.get('servicePeriodStartDate')
                    if not date_str:
                        continue
                    rows_with_date += 1

                    # Parse the date
                    if isinstance(date_str, str):
                        # Try different date formats
                        for date_format in ['%Y-%m-%d', '%m/%d/%Y', '%Y%m%d']:
                            try:
                                row_date = datetime.strptime(date_str, date_format).date()
                                break
                            except ValueError:
                                continue
                        else:
                            if rows_processed <= 3:  # Only log first few parsing failures
                                logger.warning(f"Could not parse date: '{date_str}'")
                            continue
                    else:
                        row_date = date_str.date() if hasattr(date_str, 'date') else date_str

                    # Check if date is in our range
                    # Handle both datetime and date objects safely
                    start_date_obj = start_date.date() if isinstance(start_date, datetime) else start_date
                    end_date_obj = end_date.date() if isinstance(end_date, datetime) else end_date
                    if row_date < start_date_obj or row_date > end_date_obj:
                        continue
                    rows_in_range += 1

                    # Extract cost amount - use only costInBillingCurrency to avoid duplication
                    # Analysis shows costInBillingCurrency, costInPricingCurrency, and costInUsd
                    # often contain identical values, causing 3x cost inflation
                    cost_amount = 0.0
                    if 'costInBillingCurrency' in row and row['costInBillingCurrency']:
                        try:
                            cost_amount = float(row['costInBillingCurrency'])
                            if cost_amount != 0:
                                rows_with_cost += 1
                        except (ValueError, TypeError):
                            cost_amount = 0.0

                    # Extract currency
                    currency = row.get('billingCurrency', 'USD')
                    # Ensure currency is not empty
                    if not currency or currency.strip() == '':
                        currency = 'USD'
                    currencies.add(currency)

                    # Extract service information - try different fields in order of preference
                    service_name = (row.get('serviceFamily') or
                                   row.get('consumedService') or
                                   row.get('meterCategory') or
                                   'Unknown')

                    # Normalize the service name
                    normalized_service = self.normalize_service_name(service_name)

                    # Extract subscription information from the row data
                    # Azure export data contains subscription info for each row
                    subscription_id = (row.get('subscriptionId') or
                                     row.get('subscriptionGuid') or
                                     row.get('subscription_id') or
                                     row.get('SubscriptionId') or
                                     self.subscription_id or  # Fallback to config
                                     'unknown')

                    # Extract subscription name for display purposes
                    subscription_name = (row.get('subscriptionName') or
                                       row.get('subscription_name') or
                                       row.get('SubscriptionName') or
                                       subscription_id)  # Fallback to ID if name not available

                    # Create deduplication key to prevent counting the same cost multiple times
                    resource_id = row.get('ResourceId') or row.get('resourceId') or 'unknown'
                    meter_id = row.get('meterId') or 'unknown'
                    dedup_key = (row_date, resource_id, meter_id, cost_amount, subscription_id)

                    # Skip if we've already processed this exact cost
                    if dedup_key in seen_costs:
                        continue
                    seen_costs.add(dedup_key)

                    # Add to daily totals (for backward compatibility)
                    if row_date not in daily_costs:
                        daily_costs[row_date] = 0.0
                    daily_costs[row_date] += cost_amount

                    # Add to service-date-subscription combination tracking
                    service_date_subscription_key = (row_date, normalized_service, subscription_id)
                    if service_date_subscription_key not in service_date_costs:
                        service_date_costs[service_date_subscription_key] = {
                            'cost': 0.0,
                            'subscription_name': subscription_name
                        }
                    service_date_costs[service_date_subscription_key]['cost'] += cost_amount

                except Exception as e:
                    if rows_processed <= 3:  # Only log first few errors
                        logger.warning(f"Error parsing export row: {e}")
                    continue

            logger.info(f"Export parsing stats: {rows_processed} rows processed, {rows_with_date} had dates, {rows_in_range} in date range, {rows_with_cost} had non-zero costs")
            logger.info(f"Found {len(service_date_costs)} unique service-date combinations")
            logger.info(f"Date range requested: {start_date.date()} to {end_date.date()}")

            # Log sample of processed data for debugging
            if service_date_costs:
                sample_dates = sorted(set(date_key for (date_key, _, _) in service_date_costs.keys()))[:10]
                logger.info(f"Sample dates with costs: {sample_dates}")

            # Log subscription breakdown
            if service_date_costs:
                subscription_totals = {}
                for (_, _, subscription_id), cost_data in service_date_costs.items():
                    subscription_totals[subscription_id] = subscription_totals.get(subscription_id, 0.0) + cost_data['cost']
                logger.info(f"Found {len(subscription_totals)} unique subscriptions with costs")
                top_subscriptions = sorted(subscription_totals.items(), key=lambda x: x[1], reverse=True)[:5]
                logger.debug(f"Top 5 subscriptions by cost: {top_subscriptions}")

            # Log any dates that had zero costs
            if daily_costs:
                zero_cost_dates = [date_key for date_key, cost in daily_costs.items() if cost == 0]
                if zero_cost_dates:
                    logger.info(f"Found {len(zero_cost_dates)} dates with zero costs: {sorted(zero_cost_dates)[:10]}")
                non_zero_dates = [date_key for date_key, cost in daily_costs.items() if cost > 0]
                logger.info(f"Found {len(non_zero_dates)} dates with non-zero costs: {sorted(non_zero_dates)}")

            # Log top services for debugging
            if service_date_costs:
                service_totals = {}
                for (_, service_name, _), cost_data in service_date_costs.items():
                    service_totals[service_name] = service_totals.get(service_name, 0.0) + cost_data['cost']
                top_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:5]
                logger.debug(f"Top 5 services by cost: {top_services}")

            # Determine the currency to use before processing data points
            final_currency = 'USD'  # Default fallback
            if currencies:
                first_currency = list(currencies)[0]
                if first_currency and first_currency.strip():
                    final_currency = first_currency

            # Check if we need service-level breakdown
            group_by = group_by or []
            if 'SERVICE' in group_by:
                # Return service-level data points for service breakdown
                logger.info(f"Returning service-level breakdown with {len(service_date_costs)} service-date combinations")
                for (cost_date, service_name, subscription_id), cost_data in service_date_costs.items():
                    if cost_data['cost'] > 0:
                        data_points.append(CostDataPoint(
                            date=cost_date,
                            amount=cost_data['cost'],
                            currency=final_currency,
                            service_name=service_name,
                            account_id=subscription_id,
                            region=None,
                            tags={
                                'data_source': 'azure_export',
                                'aggregation_level': 'service_daily',
                                'subscription_name': cost_data['subscription_name']
                            }
                        ))
                        total_cost += cost_data['cost']
            else:
                # Convert daily costs to data points (aggregated by date only to avoid double-counting)
                # Note: Using daily_costs instead of service_date_costs prevents cost inflation
                # from counting the same cost multiple times across different service breakdowns
                for cost_date, daily_cost in daily_costs.items():
                    if daily_cost > 0:  # Only include dates with actual costs
                        data_points.append(CostDataPoint(
                            date=cost_date,
                            amount=daily_cost,
                            currency=final_currency,
                            service_name='All Services',  # Aggregated across all services
                            account_id=None,  # Multiple subscriptions aggregated
                            region=None,      # Region aggregated
                            tags={
                                'data_source': 'azure_export',
                                'aggregation_level': 'daily_total'
                            }
                        ))
                        total_cost += daily_cost

            # Sort data points by date
            data_points.sort(key=lambda x: x.date)

            logger.info(f"Parsed {len(data_points)} daily cost data points, total: ${total_cost:.2f}")

            return CostSummary(
                provider=self.provider_name,
                start_date=start_date.date(),
                end_date=end_date.date(),
                total_cost=total_cost,
                currency=final_currency,  # Use the same currency as data points
                data_points=data_points,
                granularity=granularity,
                last_updated=datetime.now()
            )

        except Exception as e:
            logger.error(f"Error parsing export data: {e}")
            raise

    async def debug_cost_data_for_date(self, target_date: str = "2024-12-01"):
        """Debug function to examine raw cost data for a specific date."""
        from datetime import datetime, timedelta

        logger.info(f"🔍 Debugging Azure cost data for {target_date}")

        try:
            # Parse target date
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            start_date = target_dt
            end_date = target_dt + timedelta(days=1)

            # Get raw export data - need to use the internal method that returns raw CSV data
            logger.info("Fetching raw export data...")
            raw_export_data = await self._find_and_read_export_data(start_date, end_date)

            if not raw_export_data:
                logger.error("No export data found!")
                return

            # Analyze rows for target date
            target_date_str = target_date
            matching_rows = []
            cost_field_analysis = {}

            for row in raw_export_data:
                # Check if row is for target date
                row_date = row.get('date') or row.get('billingPeriodStartDate') or row.get('servicePeriodStartDate')
                if row_date and row_date.startswith(target_date_str):
                    matching_rows.append(row)

                    # Analyze cost fields for this row
                    cost_fields = ['costInBillingCurrency', 'costInPricingCurrency', 'costInUsd', 'paygCostInBillingCurrency']
                    for field in cost_fields:
                        if field in row and row[field]:
                            try:
                                value = float(row[field])
                                if value != 0:
                                    if field not in cost_field_analysis:
                                        cost_field_analysis[field] = {'count': 0, 'total': 0.0, 'min': float('inf'), 'max': float('-inf'), 'examples': []}

                                    cost_field_analysis[field]['count'] += 1
                                    cost_field_analysis[field]['total'] += value
                                    cost_field_analysis[field]['min'] = min(cost_field_analysis[field]['min'], value)
                                    cost_field_analysis[field]['max'] = max(cost_field_analysis[field]['max'], value)

                                    # Store first few examples
                                    if len(cost_field_analysis[field]['examples']) < 5:
                                        cost_field_analysis[field]['examples'].append({
                                            'value': value,
                                            'service': row.get('serviceFamily') or row.get('consumedService') or 'Unknown',
                                            'subscription': row.get('subscriptionName') or row.get('subscriptionId') or 'Unknown'
                                        })
                            except (ValueError, TypeError):
                                continue

            logger.info(f"Found {len(matching_rows)} rows for {target_date}")

            # Print cost field analysis
            total_calculated_cost = 0.0
            logger.info("=== Cost Field Analysis ===")
            for field, stats in cost_field_analysis.items():
                logger.info(f"{field}:")
                logger.info(f"  Count: {stats['count']} rows")
                logger.info(f"  Total: ${stats['total']:.2f}")
                logger.info(f"  Min: ${stats['min']:.2f}")
                logger.info(f"  Max: ${stats['max']:.2f}")
                logger.info(f"  Examples: {stats['examples'][:3]}")

                # This is what the current code would use (first non-zero field)
                if total_calculated_cost == 0.0:
                    total_calculated_cost = stats['total']
                    logger.info(f"  *** This field would be used by current logic ***")
                logger.info("")

            logger.info(f"Current logic would calculate total cost: ${total_calculated_cost:.2f}")
            logger.info(f"Expected cost (from Azure console): $1215.22")
            logger.info(f"Discrepancy: ${total_calculated_cost - 1215.22:.2f}")

            # Show sample rows
            logger.info("=== Sample Rows ===")
            for i, row in enumerate(matching_rows[:3]):
                logger.info(f"Row {i+1}:")
                for field in ['date', 'serviceFamily', 'consumedService', 'subscriptionName'] + ['costInBillingCurrency', 'costInPricingCurrency', 'costInUsd', 'paygCostInBillingCurrency']:
                    if field in row:
                        logger.info(f"  {field}: {row[field]}")
                logger.info("")

        except Exception as e:
            logger.error(f"Debug function error: {e}")
            import traceback
            logger.error(traceback.format_exc())


# Register the Azure provider with the factory
if AZURE_AVAILABLE:
    ProviderFactory.register_provider("azure", AzureCostProvider)
else:
    logger.warning("Azure SDK not available, Azure provider not registered")