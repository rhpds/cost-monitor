"""
Google Cloud Platform (GCP) Cloud Billing provider implementation.

Provides GCP-specific cost monitoring functionality using the Cloud Billing API.
"""

import logging
from datetime import date, datetime
from typing import Any

try:
    from google.api_core.exceptions import (
        GoogleAPICallError,
        NotFound,
        PermissionDenied,
        ResourceExhausted,
    )
    from google.cloud import bigquery, billing_v1

    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

from ..utils.auth import GCPAuthenticator
from .base import (
    APIError,
    AuthenticationError,
    CloudCostProvider,
    ConfigurationError,
    CostDataPoint,
    CostSummary,
    ProviderFactory,
    RateLimitError,
    TimeGranularity,
)

logger = logging.getLogger(__name__)


class GCPCostProvider(CloudCostProvider):
    """GCP Cloud Billing provider implementation."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.billing_client = None
        self.bigquery_client = None
        self.credentials = None
        self.authenticator = GCPAuthenticator(config)

        # GCP-specific configuration
        import os

        self.project_id = config.get("project_id") or config.get("GCP_PROJECT_ID")
        self.billing_account_id = (
            config.get("billing_account_id")
            or config.get("GCP_BILLING_ACCOUNT_ID")
            or os.environ.get("CLOUDCOST__CLOUDS__GCP__BILLING_ACCOUNT_ID")
        )

        # Billing configuration
        self.billing_config = config.get("billing", {})
        self.currency = self.billing_config.get("currency", "USD")

        # BigQuery dataset for billing export (if available)
        self.bq_dataset = config.get("bigquery_billing_dataset") or os.environ.get(
            "CLOUDCOST__CLOUDS__GCP__BIGQUERY_BILLING_DATASET"
        )
        self.bq_table = config.get("bigquery_billing_table", "gcp_billing_export_v1_")

        # Cache initialization removed - using PostgreSQL instead

    def _get_provider_name(self) -> str:
        return "gcp"

    async def authenticate(self) -> bool:
        """Authenticate with GCP using various methods."""
        try:
            auth_result = await self.authenticator.authenticate()

            if auth_result.success:
                self.credentials = auth_result.credentials
                self._create_clients()
                self._authenticated = True
                logger.info(f"GCP authentication successful using {auth_result.method}")

                # GCP authentication successful
                logger.info("GCP provider ready - using in-memory processing only")

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
                credentials=self.credentials, project=self.project_id
            )

    async def test_connection(self) -> bool:
        """Test the connection to GCP Cloud Billing API."""
        try:
            await self.ensure_authenticated()

            # Test billing API access
            if not self.billing_client:
                raise ValueError("GCP billing client not initialized")
            request = billing_v1.ListBillingAccountsRequest()  # type: ignore[unreachable]
            billing_accounts = self.billing_client.list_billing_accounts(request=request)

            # Try to iterate through at least one account
            for _account in billing_accounts:
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
        except ResourceExhausted:
            logger.warning("GCP API quota exhausted")
            return True  # Connection works, just rate limited
        except Exception as e:
            logger.error(f"GCP connection test error: {e}")
            return False

    async def get_cost_data(
        self,
        start_date: datetime | date,
        end_date: datetime | date,
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: list[str] | None = None,
        filter_by: dict[str, Any] | None = None,
    ) -> CostSummary:
        """Retrieve cost data from GCP."""
        await self.ensure_authenticated()

        # Validate and normalize dates
        start_date, end_date = self.validate_date_range(start_date, end_date)

        # Get fresh data from API (no caching)
        try:
            logger.info(f"🟢 GCP: Fetching fresh cost data for {start_date} to {end_date}")
            # Use BigQuery billing export if available, otherwise use Cloud Billing API
            if self.bigquery_client and self.bq_dataset:  # type: ignore[unreachable]
                logger.info("🟢 GCP: Using BigQuery billing export")  # type: ignore[unreachable]
                cost_summary = await self._get_cost_data_from_bigquery(
                    start_date, end_date, granularity, group_by, filter_by
                )
            else:
                logger.info("🟢 GCP: Using Cloud Billing API")
                cost_summary = await self._get_cost_data_from_api(
                    start_date, end_date, granularity, group_by, filter_by
                )

            logger.info(
                f"🟢 GCP: Parsed {len(cost_summary.data_points)} data points, total cost: ${cost_summary.total_cost}"
            )

            # Save daily cache - group data points by date and save separately
            daily_data: dict[date, list[CostDataPoint]] = {}
            for point in cost_summary.data_points:
                point_date = point.date
                if point_date not in daily_data:
                    daily_data[point_date] = []
                daily_data[point_date].append(point)

            logger.info(f"🟢 GCP: Processed {len(daily_data)} dates")
            return cost_summary

        except GoogleAPICallError as e:
            self._handle_gcp_error(e)
            raise  # Re-raise after handling
        except Exception as e:
            logger.error(f"GCP cost data retrieval failed: {e}")
            raise APIError(f"GCP cost data retrieval failed: {e}", provider=self.provider_name)

    async def _get_cost_data_from_bigquery(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: list[str] | None = None,
        filter_by: dict[str, Any] | None = None,
    ) -> CostSummary:
        """Get cost data from BigQuery billing export."""
        if not self.billing_account_id:
            raise ValueError("GCP billing account ID not set")
        table_name = f"{self.bq_table}{self.billing_account_id.replace('-', '_')}"

        # Build SQL query
        date_format = "%Y-%m-%d" if granularity == TimeGranularity.DAILY else "%Y-%m"
        date_column = (
            "usage_start_time"
            if granularity == TimeGranularity.DAILY
            else "EXTRACT(YEAR_MONTH FROM usage_start_time)"
        )

        select_columns = [
            f"FORMAT_DATE('{date_format}', DATE({date_column})) as usage_date",
            "SUM(cost) as total_cost",
            "currency",
            # Always include service information for better cost breakdown
            "service.description as service_name",
            # Always include project information for account breakdown
            "project.id as project_id",
        ]

        group_columns = ["usage_date", "currency", "service.description", "project.id"]

        # Add additional grouping columns if requested
        if group_by:
            for dim in group_by:
                if dim.upper() == "SERVICE":
                    # Service already included above
                    pass
                elif dim.upper() == "PROJECT":
                    # Project already included above
                    pass
                elif dim.upper() == "LOCATION":
                    select_columns.append("location.location as location")
                    group_columns.append("location.location")

        # Build WHERE clause
        where_conditions = [
            f"DATE(usage_start_time) >= '{start_date.date()}'",
            f"DATE(usage_end_time) <= '{end_date.date()}'",
        ]

        if filter_by:
            if "services" in filter_by:
                services_list = "', '".join(filter_by["services"])
                where_conditions.append(f"service.description IN ('{services_list}')")
            if "projects" in filter_by:
                projects_list = "', '".join(filter_by["projects"])
                where_conditions.append(f"project.id IN ('{projects_list}')")

        query = f"""
            SELECT {', '.join(select_columns)}
            FROM `{self.project_id}.{self.bq_dataset}.{table_name}`
            WHERE {' AND '.join(where_conditions)}
            GROUP BY {', '.join(group_columns)}
            ORDER BY usage_date
        """

        try:
            if not self.bigquery_client:
                raise ValueError("GCP BigQuery client not initialized")
            query_job = self.bigquery_client.query(query)  # type: ignore[unreachable]
            results = query_job.result()

            return self._parse_bigquery_results(
                results, start_date, end_date, granularity, group_by
            )

        except Exception as e:
            logger.error(f"BigQuery cost query failed: {e}")
            raise APIError(f"BigQuery cost query failed: {e}", provider=self.provider_name)

    async def _get_cost_data_from_api(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_by: list[str] | None = None,
        filter_by: dict[str, Any] | None = None,
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
            if not self.billing_client:
                raise ValueError("GCP billing client not initialized")
            project_billing_info = self.billing_client.get_project_billing_info(name=project_name)  # type: ignore[unreachable]

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
                last_updated=datetime.now(),
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
        group_by: list[str] | None = None,
    ) -> CostSummary:
        """Parse BigQuery results into our standard format."""
        data_points = []
        total_cost = 0.0
        currency = self.currency

        # Determine aggregation strategy based on group_by parameter
        # For account breakdown, we want project-level data; for service breakdown, we aggregate across projects
        group_by = group_by or []
        include_projects = "PROJECT" in [dim.upper() for dim in group_by]

        # Deduplication tracking: aggregate costs based on grouping requirements
        aggregated_costs: dict[tuple[date, str] | tuple[date, str, str], dict[str, Any]] = {}

        for row in results:
            # Parse date
            usage_date = datetime.strptime(row["usage_date"], "%Y-%m-%d").date()

            # Parse cost
            cost_amount = float(row["total_cost"] or 0)
            row_currency = row.get("currency", self.currency)

            # Parse service information
            service_name = row.get("service_name")
            project_id = row.get("project_id")
            location = row.get("location")

            # Create aggregation key based on grouping requirements
            normalized_service = (
                self.normalize_service_name(service_name) if service_name else "Unknown"
            )

            if include_projects:
                # For account breakdown: aggregate by (date, service, project) to preserve individual projects
                agg_key: tuple[date, str] | tuple[date, str, str] = (
                    usage_date,
                    normalized_service,
                    project_id or "unknown-project",
                )
            else:
                # For service breakdown: aggregate by (date, service) to combine across projects
                agg_key = (usage_date, normalized_service)

            if agg_key not in aggregated_costs:
                aggregated_costs[agg_key] = {
                    "amount": 0.0,
                    "currency": row_currency,
                    "projects": set(),
                    "location": location,
                }

            aggregated_costs[agg_key]["amount"] += cost_amount
            if project_id:
                aggregated_costs[agg_key]["projects"].add(project_id)

            # Use the currency from the data
            if row_currency:
                currency = row_currency

        # Create data points from aggregated costs
        for agg_key, cost_data in aggregated_costs.items():
            amount = cost_data["amount"]
            if amount > 0:  # Only include non-zero costs
                if include_projects:
                    # Project-level breakdown: agg_key is (date, service, project)
                    assert len(agg_key) == 3, "Expected 3-tuple for project breakdown"
                    date_val, service_name, project_id = agg_key
                    account_id = project_id  # Use actual project ID as account ID
                else:
                    # Service-level breakdown: agg_key is (date, service)
                    assert len(agg_key) == 2, "Expected 2-tuple for service breakdown"
                    date_val, service_name = agg_key
                    projects = cost_data["projects"]
                    account_id = (
                        list(projects)[0]
                        if len(projects) == 1
                        else f"MultiProject({len(projects)})"
                    )

                data_point = CostDataPoint(
                    date=date_val,
                    amount=amount,
                    currency=cost_data["currency"],
                    service_name=service_name,
                    account_id=account_id,
                    account_name=account_id,  # For GCP, use project ID as account name
                    region=cost_data["location"],
                    tags={
                        "project_count": str(len(cost_data["projects"])),
                        "projects": ",".join(
                            list(cost_data["projects"])[:5]
                        ),  # Store up to 5 project names as comma-separated
                    },
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
            last_updated=datetime.now(),
        )

    async def get_current_month_cost(self) -> float:
        """Get the current month's total cost."""
        now = datetime.now()
        start_of_month = now.replace(day=1).date()
        end_date = now.date()

        cost_summary = await self.get_cost_data(start_of_month, end_date)
        return cost_summary.total_cost

    async def get_daily_costs(
        self, start_date: datetime | date, end_date: datetime | date
    ) -> list[CostDataPoint]:
        """Get daily cost breakdown for the specified period."""
        cost_summary = await self.get_cost_data(
            start_date, end_date, granularity=TimeGranularity.DAILY
        )

        # Group by date and sum costs
        daily_costs: dict[date, dict[str, Any]] = {}
        for point in cost_summary.data_points:
            date_key = point.date
            if date_key not in daily_costs:
                daily_costs[date_key] = {"amount": 0.0, "currency": point.currency}
            daily_costs[date_key]["amount"] += point.amount

        return [
            CostDataPoint(
                date=date_key,
                amount=float(data["amount"]),
                currency=str(data["currency"]),
                service_name=None,
            )
            for date_key, data in daily_costs.items()
        ]

    async def get_service_costs(
        self, start_date: datetime | date, end_date: datetime | date, top_n: int = 10
    ) -> dict[str, float]:
        """Get cost breakdown by service for the specified period."""
        cost_summary = await self.get_cost_data(start_date, end_date, group_by=["SERVICE"])

        # Aggregate costs by service
        service_costs: dict[str, float] = {}
        for point in cost_summary.data_points:
            if point.service_name:
                service_name = point.service_name
                service_costs[service_name] = service_costs.get(service_name, 0.0) + point.amount

        # Sort by cost and return top N
        sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)

        return dict(sorted_services[:top_n])

    def get_supported_regions(self) -> list[str]:
        """Get list of supported GCP regions."""
        return [
            "us-central1",
            "us-east1",
            "us-east4",
            "us-west1",
            "us-west2",
            "us-west3",
            "us-west4",
            "northamerica-northeast1",
            "northamerica-northeast2",
            "europe-north1",
            "europe-west1",
            "europe-west2",
            "europe-west3",
            "europe-west4",
            "europe-west6",
            "asia-east1",
            "asia-east2",
            "asia-northeast1",
            "asia-northeast2",
            "asia-northeast3",
            "asia-south1",
            "asia-southeast1",
            "asia-southeast2",
            "australia-southeast1",
            "southamerica-east1",
        ]

    def get_supported_services(self) -> list[str]:
        """Get list of supported GCP services for cost monitoring."""
        return [
            "Compute Engine",
            "Cloud Storage",
            "BigQuery",
            "Cloud SQL",
            "App Engine",
            "Cloud Functions",
            "Kubernetes Engine",
            "Cloud Run",
            "Cloud CDN",
            "Cloud Load Balancing",
            "Cloud DNS",
            "Cloud Firewall",
            "Cloud Pub/Sub",
            "Cloud Dataflow",
            "Cloud Dataproc",
            "Cloud Composer",
            "Cloud Vision API",
            "Cloud Speech API",
            "Cloud Natural Language API",
            "Cloud Translation API",
            "Cloud AutoML",
            "Firebase",
        ]

    def normalize_service_name(self, service_name: str) -> str:
        """Normalize GCP service names to a consistent format."""
        if not service_name:
            return "Unknown"

        # GCP-specific service name normalization
        service_mapping = {
            "Compute Engine": "Compute Engine",
            "Google Cloud Storage": "Cloud Storage",
            "BigQuery": "BigQuery",
            "Cloud SQL": "Cloud SQL",
            "App Engine": "App Engine",
            "Cloud Functions": "Cloud Functions",
            "Google Kubernetes Engine": "Kubernetes Engine",
            "Cloud Run": "Cloud Run",
            "Cloud CDN": "Cloud CDN",
            "Cloud Load Balancing": "Load Balancing",
        }

        return service_mapping.get(service_name, service_name)

    def _handle_gcp_error(self, error: "GoogleAPICallError"):
        """Handle GCP API errors appropriately."""
        if isinstance(error, ResourceExhausted):
            raise RateLimitError(f"GCP API quota exceeded: {error}", provider=self.provider_name)
        elif isinstance(error, PermissionDenied):
            raise AuthenticationError(f"GCP permission denied: {error}")
        elif isinstance(error, NotFound):
            raise ConfigurationError(f"GCP resource not found: {error}")
        else:
            raise APIError(f"GCP API error: {error}", provider=self.provider_name)

    async def get_billing_accounts(self) -> list[dict[str, str]]:
        """Get available billing accounts."""
        await self.ensure_authenticated()

        try:
            if not self.billing_client:
                raise ValueError("GCP billing client not initialized")
            request = billing_v1.ListBillingAccountsRequest()  # type: ignore[unreachable]
            billing_accounts = self.billing_client.list_billing_accounts(request=request)

            accounts = []
            for account in billing_accounts:
                accounts.append(
                    {
                        "name": account.name,
                        "display_name": account.display_name,
                        "open": account.open,
                        "master_billing_account": account.master_billing_account,
                    }
                )

            return accounts

        except Exception as e:
            logger.error(f"Failed to get GCP billing accounts: {e}")
            raise APIError(f"Failed to get GCP billing accounts: {e}", provider=self.provider_name)

    async def get_projects_for_billing_account(self, billing_account: str) -> list[dict[str, str]]:
        """Get projects associated with a billing account."""
        await self.ensure_authenticated()

        try:
            if not self.billing_client:
                raise ValueError("GCP billing client not initialized")
            request = billing_v1.ListProjectBillingInfoRequest(name=billing_account)  # type: ignore[unreachable]
            projects = self.billing_client.list_project_billing_info(request=request)

            project_list = []
            for project in projects:
                project_list.append(
                    {
                        "name": project.name,
                        "project_id": project.project_id,
                        "billing_account_name": project.billing_account_name,
                        "billing_enabled": project.billing_enabled,
                    }
                )

            return project_list

        except Exception as e:
            logger.error(f"Failed to get GCP projects: {e}")
            raise APIError(f"Failed to get GCP projects: {e}", provider=self.provider_name)


# Register the GCP provider with the factory
if GCP_AVAILABLE:
    ProviderFactory.register_provider("gcp", GCPCostProvider)
else:
    logger.warning("GCP SDK not available, GCP provider not registered")
