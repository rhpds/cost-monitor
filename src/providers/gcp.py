"""
Google Cloud Platform (GCP) Cloud Billing provider implementation.

Provides GCP-specific cost monitoring functionality using the Cloud Billing API.
"""

import logging
import os
import pickle
import hashlib
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union

try:
    from google.cloud import billing_v1
    from google.cloud import bigquery
    from google.auth import default as gcp_default
    from google.auth.exceptions import DefaultCredentialsError
    from google.api_core.exceptions import (
        GoogleAPICallError,
        PermissionDenied,
        NotFound,
        ResourceExhausted
    )
    from google.oauth2 import service_account
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

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
from ..utils.auth import GCPAuthenticator

logger = logging.getLogger(__name__)


class GCPCostProvider(CloudCostProvider):
    """GCP Cloud Billing provider implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.billing_client = None
        self.bigquery_client = None
        self.credentials = None
        self.authenticator = GCPAuthenticator(config)

        # GCP-specific configuration
        import os
        self.project_id = config.get("project_id") or config.get("GCP_PROJECT_ID")
        self.billing_account_id = (
            config.get("billing_account_id") or
            config.get("GCP_BILLING_ACCOUNT_ID") or
            os.environ.get("CLOUDCOST__CLOUDS__GCP__BILLING_ACCOUNT_ID")
        )

        # Billing configuration
        self.billing_config = config.get("billing", {})
        self.currency = self.billing_config.get("currency", "USD")

        # BigQuery dataset for billing export (if available)
        self.bq_dataset = (
            config.get("bigquery_billing_dataset") or
            os.environ.get("CLOUDCOST__CLOUDS__GCP__BIGQUERY_BILLING_DATASET")
        )
        self.bq_table = config.get("bigquery_billing_table", "gcp_billing_export_v1_")

        # Initialize persistent cache
        self._init_cache()

    def _get_provider_name(self) -> str:
        return "gcp"

    def _init_cache(self):
        """Initialize persistent cache for GCP cost data."""
        # Get cache directory from config, with fallback to default
        from ..config.settings import get_config
        config = get_config()
        base_cache_dir = config.cache.get('directory', '~/.cache/cost-monitor')
        self.cache_dir = os.path.join(os.path.expanduser(base_cache_dir), 'gcp')
        os.makedirs(self.cache_dir, exist_ok=True)
        # Cache files for 24 hours (GCP billing updates hourly)
        self.cache_max_age_hours = 24
        logger.debug(f"GCP cache initialized at: {self.cache_dir}")

    def _get_cache_key(self, start_date: date, end_date: date, granularity: str, project_id: str) -> str:
        """Generate a unique cache key for cost data request."""
        key_data = f"{start_date.isoformat()}:{end_date.isoformat()}:{granularity}:{project_id}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cache_file_path(self, cache_key: str) -> str:
        """Get the full path for a cache file."""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")

    def _get_cache_data_date(self, cache_file_path: str) -> Optional[date]:
        """Extract the data date from cached cost data."""
        try:
            with open(cache_file_path, 'rb') as f:
                cached_data = pickle.load(f)

            # If cached data contains cost data points, extract the first date
            if cached_data and len(cached_data) > 0:
                first_point = cached_data[0]
                if hasattr(first_point, 'date') and isinstance(first_point.date, date):
                    return first_point.date
                elif isinstance(first_point, dict) and 'date' in first_point:
                    if isinstance(first_point['date'], date):
                        return first_point['date']
                    elif isinstance(first_point['date'], str):
                        return datetime.strptime(first_point['date'], '%Y-%m-%d').date()
            return None
        except (FileNotFoundError, pickle.PickleError, ValueError, AttributeError) as e:
            logger.debug(f"💾 GCP: Could not extract date from cache file {cache_file_path}: {e}")
            return None

    def _is_cache_valid(self, cache_file_path: str) -> bool:
        """Check if cache file exists and is not too old."""
        if not os.path.exists(cache_file_path):
            return False

        # Extract date from cache file to determine data age
        data_date = self._get_cache_data_date(cache_file_path)

        if data_date:
            # Calculate how old the data is (not the cache file age)
            data_age_hours = (datetime.now().date() - data_date).total_seconds() / 3600

            # PERMANENT CACHING: Historical data (>48 hours old) never expires
            if data_age_hours >= 48:
                logger.debug(f"💾 GCP: Permanent cache for {data_date} ({data_age_hours:.1f}h old)")
                return True

            # Extended cache for day-old data (24-48 hours)
            elif data_age_hours >= 24:
                logger.debug(f"💾 GCP: Extended cache for {data_date} ({data_age_hours:.1f}h old)")
                return True

        # For recent data (<24 hours) or if we can't extract date, use original logic
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file_path))
        is_valid = file_age.total_seconds() < (self.cache_max_age_hours * 3600)
        logger.debug(f"💾 GCP: Recent data cache valid: {is_valid} (age: {file_age.total_seconds()/3600:.1f}h)")
        return is_valid

    def _save_to_cache(self, cache_key: str, data: List[CostDataPoint]) -> None:
        """Save cost data to cache."""
        try:
            # Ensure cache directory exists before saving
            os.makedirs(self.cache_dir, exist_ok=True)

            cache_file_path = self._get_cache_file_path(cache_key)
            logger.info(f"🟡 GCP: Attempting to save cache to: {cache_file_path}")
            logger.info(f"🟡 GCP: Cache directory: {self.cache_dir}")
            logger.info(f"🟡 GCP: Data points to save: {len(data)}")

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
            logger.info(f"✅ GCP: Successfully saved {len(data)} cost data points to cache: {cache_key}")
            logger.info(f"✅ GCP: Cache file size: {os.path.getsize(cache_file_path)} bytes")
        except Exception as e:
            logger.error(f"❌ GCP: Failed to save data to cache: {e}")
            import traceback
            logger.error(f"❌ GCP: Traceback: {traceback.format_exc()}")

    def _load_from_cache(self, cache_key: str) -> Optional[List[CostDataPoint]]:
        """Load cost data from cache."""
        try:
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

                logger.info(f"Loaded {len(data_points)} GCP cost data points from cache: {cache_key}")
                return data_points
        except Exception as e:
            logger.warning(f"Failed to load GCP data from cache: {e}")
        return None

    def _cleanup_old_cache_files(self):
        """Clean up cache files older than max age, but preserve historical data."""
        try:
            now = datetime.now()
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.pkl'):
                    file_path = os.path.join(self.cache_dir, filename)

                    # Check if this is historical data that should be preserved
                    data_date = self._get_cache_data_date(file_path)
                    if data_date:
                        data_age_hours = (datetime.now().date() - data_date).total_seconds() / 3600

                        # Never delete historical data (>48 hours old)
                        if data_age_hours >= 48:
                            logger.debug(f"💾 GCP: Preserving permanent cache for {data_date} ({filename})")
                            continue

                    # For recent data or files we can't parse, use original cleanup logic
                    file_age = now - datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_age.total_seconds() > (self.cache_max_age_hours * 3600):
                        os.remove(file_path)
                        logger.debug(f"Removed old GCP cache file: {filename}")
        except Exception as e:
            logger.warning(f"Failed to cleanup old GCP cache files: {e}")

    def _get_cache_key_for_date(self, target_date: date, granularity: str, group_by: List[str], project_id: str) -> str:
        """Generate a unique cache key for a single date's cost data."""
        key_data = f"{target_date.isoformat()}:{granularity}:{':'.join(sorted(group_by))}:{project_id}"
        cache_key = hashlib.md5(key_data.encode()).hexdigest()
        logger.debug(f"🟢 GCP: Daily cache key: {target_date} -> {cache_key}")
        return cache_key

    def _save_daily_cache(self, target_date: date, granularity: str, group_by: List[str], project_id: str, data: List[CostDataPoint]) -> None:
        """Save daily cost data to cache."""
        try:
            # Ensure cache directory exists before saving
            os.makedirs(self.cache_dir, exist_ok=True)

            cache_key = self._get_cache_key_for_date(target_date, granularity, group_by, project_id)
            cache_file_path = self._get_cache_file_path(cache_key)
            logger.debug(f"🟢 GCP: Saving daily cache for {target_date}: {len(data)} data points")

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
            logger.debug(f"✅ GCP: Saved {len(data)} cost data points for {target_date}: {cache_key}")
        except Exception as e:
            logger.error(f"❌ GCP: Failed to save daily cache for {target_date}: {e}")

    def _load_daily_cache(self, target_date: date, granularity: str, group_by: List[str], project_id: str) -> Optional[List[CostDataPoint]]:
        """Load daily cost data from cache."""
        try:
            cache_key = self._get_cache_key_for_date(target_date, granularity, group_by, project_id)
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

                logger.debug(f"📖 GCP: Loaded {len(data_points)} cached data points for {target_date}")
                return data_points
        except Exception as e:
            logger.debug(f"❌ GCP: Failed to load daily cache for {target_date}: {e}")
        return None

    async def authenticate(self) -> bool:
        """Authenticate with GCP using various methods."""
        try:
            auth_result = await self.authenticator.authenticate()

            if auth_result.success:
                self.credentials = auth_result.credentials
                self._create_clients()
                self._authenticated = True
                logger.info(f"GCP authentication successful using {auth_result.method}")

                # Clean up old cache files on successful authentication
                self._cleanup_old_cache_files()

                return True
            else:
                logger.error(f"GCP authentication failed: {auth_result.error_message}")
                raise AuthenticationError(f"GCP authentication failed: {auth_result.error_message}")

        except Exception as e:
            logger.error(f"GCP authentication error: {e}")
            raise AuthenticationError(f"GCP authentication error: {e}")

    def _create_clients(self):
        """Create GCP clients with proper configuration."""
        if not self.credentials:
            raise ConfigurationError("No authenticated GCP credentials available")

        # Create billing client
        self.billing_client = billing_v1.CloudBillingClient(credentials=self.credentials)

        # Create BigQuery client if billing export is configured
        if self.bq_dataset:
            self.bigquery_client = bigquery.Client(
                credentials=self.credentials,
                project=self.project_id
            )

    async def test_connection(self) -> bool:
        """Test the connection to GCP Cloud Billing API."""
        try:
            await self.ensure_authenticated()

            # Test billing API access
            request = billing_v1.ListBillingAccountsRequest()
            billing_accounts = self.billing_client.list_billing_accounts(request=request)

            # Try to iterate through at least one account
            for account in billing_accounts:
                break

            # Test BigQuery access if configured
            if self.bigquery_client and self.bq_dataset:
                dataset_ref = self.bigquery_client.dataset(self.bq_dataset)
                self.bigquery_client.get_dataset(dataset_ref)

            return True

        except PermissionDenied as e:
            logger.error(f"GCP permission denied: {e}")
            return False
        except NotFound as e:
            logger.warning(f"GCP resource not found (may be expected): {e}")
            return True  # Connection works, resource doesn't exist
        except ResourceExhausted as e:
            logger.warning("GCP API quota exhausted")
            return True  # Connection works, just rate limited
        except Exception as e:
            logger.error(f"GCP connection test error: {e}")
            return False

    async def get_cost_data(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """Retrieve cost data from GCP."""
        await self.ensure_authenticated()

        # Validate and normalize dates
        start_date, end_date = self.validate_date_range(start_date, end_date)

        # Prepare request parameters
        granularity_str = "DAILY" if granularity == TimeGranularity.DAILY else "MONTHLY"
        group_dimensions = group_by or []
        project_id = self.project_id or "default"

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
            cached_data_for_date = self._load_daily_cache(target_date, granularity_str, group_dimensions, project_id)
            if cached_data_for_date:
                all_cached_data.extend(cached_data_for_date)
                logger.debug(f"🟢 GCP: Cache HIT for {target_date}")
            else:
                missing_dates.append(target_date)
                logger.debug(f"🟢 GCP: Cache MISS for {target_date}")

        # If we have complete cached data for all dates, return it
        if not missing_dates:
            logger.info(f"🟢 GCP: Using fully cached data for {start_date.date()} to {end_date.date()}")
            return CostSummary(
                provider=self._get_provider_name(),
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                total_cost=sum(point.amount for point in all_cached_data),
                currency=self.currency,
                data_points=all_cached_data,
                last_updated=datetime.now()
            )

        # If we're missing some dates, we need to fetch fresh data
        logger.info(f"🟢 GCP: Cache PARTIAL - missing {len(missing_dates)} dates, fetching fresh data")

        try:
            logger.info(f"🟢 GCP: Fetching fresh cost data for {start_date} to {end_date}")
            # Use BigQuery billing export if available, otherwise use Cloud Billing API
            if self.bigquery_client and self.bq_dataset:
                logger.info(f"🟢 GCP: Using BigQuery billing export")
                cost_summary = await self._get_cost_data_from_bigquery(
                    start_date, end_date, granularity, group_by, filter_by
                )
            else:
                logger.info(f"🟢 GCP: Using Cloud Billing API")
                cost_summary = await self._get_cost_data_from_api(
                    start_date, end_date, granularity, group_by, filter_by
                )

            logger.info(f"🟢 GCP: Parsed {len(cost_summary.data_points)} data points, total cost: ${cost_summary.total_cost}")

            # Save daily cache - group data points by date and save separately
            daily_data = {}
            for point in cost_summary.data_points:
                point_date = point.date
                if point_date not in daily_data:
                    daily_data[point_date] = []
                daily_data[point_date].append(point)

            # Save each day's data to its own cache file
            for day_date, day_data_points in daily_data.items():
                self._save_daily_cache(day_date, granularity_str, group_dimensions, project_id, day_data_points)

            logger.info(f"🟢 GCP: Saved daily cache for {len(daily_data)} dates")
            return cost_summary

        except GoogleAPICallError as e:
            self._handle_gcp_error(e)
        except Exception as e:
            logger.error(f"GCP cost data retrieval failed: {e}")
            raise APIError(f"GCP cost data retrieval failed: {e}", provider=self.provider_name)

    async def _get_cost_data_from_bigquery(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """Get cost data from BigQuery billing export."""
        table_name = f"{self.bq_table}{self.billing_account_id.replace('-', '_')}"

        # Build SQL query
        date_format = "%Y-%m-%d" if granularity == TimeGranularity.DAILY else "%Y-%m"
        date_column = "usage_start_time" if granularity == TimeGranularity.DAILY else "EXTRACT(YEAR_MONTH FROM usage_start_time)"

        select_columns = [
            f"FORMAT_DATE('{date_format}', DATE({date_column})) as usage_date",
            "SUM(cost) as total_cost",
            "currency",
            # Always include service information for better cost breakdown
            "service.description as service_name",
            # Always include project information for account breakdown
            "project.id as project_id"
        ]

        group_columns = ["usage_date", "currency", "service.description", "project.id"]

        # Add additional grouping columns if requested
        if group_by:
            for dim in group_by:
                if dim.upper() == 'SERVICE':
                    # Service already included above
                    pass
                elif dim.upper() == 'PROJECT':
                    # Project already included above
                    pass
                elif dim.upper() == 'LOCATION':
                    select_columns.append("location.location as location")
                    group_columns.append("location.location")

        # Build WHERE clause
        where_conditions = [
            f"DATE(usage_start_time) >= '{start_date.date()}'",
            f"DATE(usage_end_time) <= '{end_date.date()}'"
        ]

        if filter_by:
            if 'services' in filter_by:
                services_list = "', '".join(filter_by['services'])
                where_conditions.append(f"service.description IN ('{services_list}')")
            if 'projects' in filter_by:
                projects_list = "', '".join(filter_by['projects'])
                where_conditions.append(f"project.id IN ('{projects_list}')")

        query = f"""
            SELECT {', '.join(select_columns)}
            FROM `{self.project_id}.{self.bq_dataset}.{table_name}`
            WHERE {' AND '.join(where_conditions)}
            GROUP BY {', '.join(group_columns)}
            ORDER BY usage_date
        """

        try:
            query_job = self.bigquery_client.query(query)
            results = query_job.result()

            return self._parse_bigquery_results(results, start_date, end_date, granularity, group_by)

        except Exception as e:
            logger.error(f"BigQuery cost query failed: {e}")
            raise APIError(f"BigQuery cost query failed: {e}", provider=self.provider_name)

    async def _get_cost_data_from_api(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None
    ) -> CostSummary:
        """Get cost data from Cloud Billing API (limited functionality)."""
        # Note: The Cloud Billing API has limited cost querying capabilities
        # Most detailed billing data requires BigQuery export

        logger.warning(
            "Using Cloud Billing API for cost data. For detailed cost analysis, "
            "consider enabling BigQuery billing export."
        )

        # Get basic project billing info
        if not self.project_id:
            raise ConfigurationError("Project ID required for GCP cost monitoring")

        project_name = f"projects/{self.project_id}"

        try:
            project_billing_info = self.billing_client.get_project_billing_info(name=project_name)

            if not project_billing_info.billing_enabled:
                logger.warning(f"Billing is not enabled for project {self.project_id}")

            # Since the API doesn't provide detailed cost data, we return a basic summary
            # In a real implementation, you would need BigQuery export for detailed data
            return CostSummary(
                provider=self.provider_name,
                start_date=start_date.date(),
                end_date=end_date.date(),
                total_cost=0.0,  # Cannot get actual costs without BigQuery export
                currency=self.currency,
                data_points=[],
                granularity=granularity,
                last_updated=datetime.now()
            )

        except Exception as e:
            logger.error(f"GCP API cost query failed: {e}")
            raise APIError(f"GCP API cost query failed: {e}", provider=self.provider_name)

    def _parse_bigquery_results(
        self,
        results,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: Optional[List[str]] = None
    ) -> CostSummary:
        """Parse BigQuery results into our standard format."""
        data_points = []
        total_cost = 0.0
        currency = self.currency

        # Determine aggregation strategy based on group_by parameter
        # For account breakdown, we want project-level data; for service breakdown, we aggregate across projects
        group_by = group_by or []
        include_projects = 'PROJECT' in [dim.upper() for dim in group_by]

        # Deduplication tracking: aggregate costs based on grouping requirements
        aggregated_costs = {}

        for row in results:
            # Parse date
            usage_date = datetime.strptime(row['usage_date'], '%Y-%m-%d').date()

            # Parse cost
            cost_amount = float(row['total_cost'] or 0)
            row_currency = row.get('currency', self.currency)

            # Parse service information
            service_name = row.get('service_name')
            project_id = row.get('project_id')
            location = row.get('location')

            # Create aggregation key based on grouping requirements
            normalized_service = self.normalize_service_name(service_name) if service_name else 'Unknown'

            if include_projects:
                # For account breakdown: aggregate by (date, service, project) to preserve individual projects
                agg_key = (usage_date, normalized_service, project_id or 'unknown-project')
            else:
                # For service breakdown: aggregate by (date, service) to combine across projects
                agg_key = (usage_date, normalized_service)

            if agg_key not in aggregated_costs:
                aggregated_costs[agg_key] = {
                    'amount': 0.0,
                    'currency': row_currency,
                    'projects': set(),
                    'location': location
                }

            aggregated_costs[agg_key]['amount'] += cost_amount
            if project_id:
                aggregated_costs[agg_key]['projects'].add(project_id)

            # Use the currency from the data
            if row_currency:
                currency = row_currency

        # Create data points from aggregated costs
        for agg_key, cost_data in aggregated_costs.items():
            amount = cost_data['amount']
            if amount > 0:  # Only include non-zero costs
                if include_projects:
                    # Project-level breakdown: agg_key is (date, service, project)
                    date_val, service_name, project_id = agg_key
                    account_id = project_id  # Use actual project ID as account ID
                else:
                    # Service-level breakdown: agg_key is (date, service)
                    date_val, service_name = agg_key
                    projects = cost_data['projects']
                    account_id = list(projects)[0] if len(projects) == 1 else f"MultiProject({len(projects)})"

                data_point = CostDataPoint(
                    date=date_val,
                    amount=amount,
                    currency=cost_data['currency'],
                    service_name=service_name,
                    account_id=account_id,
                    region=cost_data['location'],
                    tags={
                        'project_count': len(cost_data['projects']),
                        'projects': list(cost_data['projects'])[:5]  # Store up to 5 project names
                    }
                )

                data_points.append(data_point)
                total_cost += amount

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
                service_name=None
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
        """Get list of supported GCP regions."""
        return [
            'us-central1', 'us-east1', 'us-east4', 'us-west1', 'us-west2', 'us-west3', 'us-west4',
            'northamerica-northeast1', 'northamerica-northeast2',
            'europe-north1', 'europe-west1', 'europe-west2', 'europe-west3', 'europe-west4', 'europe-west6',
            'asia-east1', 'asia-east2', 'asia-northeast1', 'asia-northeast2', 'asia-northeast3',
            'asia-south1', 'asia-southeast1', 'asia-southeast2',
            'australia-southeast1', 'southamerica-east1'
        ]

    def get_supported_services(self) -> List[str]:
        """Get list of supported GCP services for cost monitoring."""
        return [
            'Compute Engine', 'Cloud Storage', 'BigQuery', 'Cloud SQL',
            'App Engine', 'Cloud Functions', 'Kubernetes Engine', 'Cloud Run',
            'Cloud CDN', 'Cloud Load Balancing', 'Cloud DNS', 'Cloud Firewall',
            'Cloud Pub/Sub', 'Cloud Dataflow', 'Cloud Dataproc', 'Cloud Composer',
            'Cloud Vision API', 'Cloud Speech API', 'Cloud Natural Language API',
            'Cloud Translation API', 'Cloud AutoML', 'Firebase'
        ]

    def normalize_service_name(self, service_name: str) -> str:
        """Normalize GCP service names to a consistent format."""
        if not service_name:
            return "Unknown"

        # GCP-specific service name normalization
        service_mapping = {
            'Compute Engine': 'Compute Engine',
            'Google Cloud Storage': 'Cloud Storage',
            'BigQuery': 'BigQuery',
            'Cloud SQL': 'Cloud SQL',
            'App Engine': 'App Engine',
            'Cloud Functions': 'Cloud Functions',
            'Google Kubernetes Engine': 'Kubernetes Engine',
            'Cloud Run': 'Cloud Run',
            'Cloud CDN': 'Cloud CDN',
            'Cloud Load Balancing': 'Load Balancing'
        }

        return service_mapping.get(service_name, service_name)

    def _handle_gcp_error(self, error: "GoogleAPICallError"):
        """Handle GCP API errors appropriately."""
        if isinstance(error, ResourceExhausted):
            raise RateLimitError(
                f"GCP API quota exceeded: {error}",
                provider=self.provider_name
            )
        elif isinstance(error, PermissionDenied):
            raise AuthenticationError(f"GCP permission denied: {error}")
        elif isinstance(error, NotFound):
            raise ConfigurationError(f"GCP resource not found: {error}")
        else:
            raise APIError(
                f"GCP API error: {error}",
                provider=self.provider_name
            )

    async def get_billing_accounts(self) -> List[Dict[str, str]]:
        """Get available billing accounts."""
        await self.ensure_authenticated()

        try:
            request = billing_v1.ListBillingAccountsRequest()
            billing_accounts = self.billing_client.list_billing_accounts(request=request)

            accounts = []
            for account in billing_accounts:
                accounts.append({
                    'name': account.name,
                    'display_name': account.display_name,
                    'open': account.open,
                    'master_billing_account': account.master_billing_account
                })

            return accounts

        except Exception as e:
            logger.error(f"Failed to get GCP billing accounts: {e}")
            raise APIError(f"Failed to get GCP billing accounts: {e}", provider=self.provider_name)

    async def get_projects_for_billing_account(self, billing_account: str) -> List[Dict[str, str]]:
        """Get projects associated with a billing account."""
        await self.ensure_authenticated()

        try:
            request = billing_v1.ListProjectBillingInfoRequest(
                name=billing_account
            )
            projects = self.billing_client.list_project_billing_info(request=request)

            project_list = []
            for project in projects:
                project_list.append({
                    'name': project.name,
                    'project_id': project.project_id,
                    'billing_account_name': project.billing_account_name,
                    'billing_enabled': project.billing_enabled
                })

            return project_list

        except Exception as e:
            logger.error(f"Failed to get GCP projects: {e}")
            raise APIError(f"Failed to get GCP projects: {e}", provider=self.provider_name)


# Register the GCP provider with the factory
if GCP_AVAILABLE:
    ProviderFactory.register_provider("gcp", GCPCostProvider)
else:
    logger.warning("GCP SDK not available, GCP provider not registered")