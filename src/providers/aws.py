"""
AWS Cost Explorer provider implementation.

Provides AWS-specific cost monitoring functionality using the AWS Cost Explorer API.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta
from typing import Any

try:
    from botocore.config import Config
    from botocore.exceptions import ClientError

    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False

from ..utils.auth import AWSAuthenticator
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


class AWSCostProvider(CloudCostProvider):
    """AWS Cost Explorer provider implementation."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.session = None
        self.cost_explorer_client = None
        self.organizations_client = None

        # Convert DynaBox to regular dict to ensure proper access in authenticator
        if hasattr(config, "get") and hasattr(config, "keys"):
            # Convert Box/DynaBox to regular dict
            auth_config = {}
            for key in config:
                auth_config[key] = config.get(key)
        else:
            auth_config = config

        logger.debug(
            f"🔵 AWS: Auth config - has access_key_id: {bool(auth_config.get('access_key_id'))}"
        )
        self.authenticator = AWSAuthenticator(auth_config)

        # AWS-specific configuration
        self.region = config.get("region", "us-east-1")
        self.granularity_mapping = {
            TimeGranularity.DAILY: "DAILY",
            TimeGranularity.MONTHLY: "MONTHLY",
        }

        # Cache for account names to avoid repeated API calls (in-memory only)
        self.account_names_cache: dict[str, str] = {}

        # Cost Explorer configuration
        self.ce_config = config.get("cost_explorer", {})
        raw_metrics = self.ce_config.get("metrics", ["BlendedCost"])
        # Deduplicate metrics list while preserving order
        self.default_metrics = list(dict.fromkeys(raw_metrics))
        raw_group_by = self.ce_config.get("group_by", ["SERVICE", "LINKED_ACCOUNT"])
        # Deduplicate group_by list while preserving order
        self.default_group_by = list(dict.fromkeys(raw_group_by))

    def _get_provider_name(self) -> str:
        return "aws"

    def validate_date_range(
        self, start_date: datetime | date, end_date: datetime | date
    ) -> tuple[datetime, datetime]:
        """
        AWS-specific date validation that excludes current day due to 24-hour data lag.

        AWS Cost Explorer data has a 24-hour lag, meaning today's costs aren't available
        until tomorrow. This method automatically excludes the current day from requests
        to avoid caching zero values that would persist for 24 hours.
        """
        # Convert dates to datetime if needed
        if isinstance(start_date, date) and not isinstance(start_date, datetime):
            start_date = datetime.combine(start_date, datetime.min.time())
        if isinstance(end_date, date) and not isinstance(end_date, datetime):
            end_date = datetime.combine(end_date, datetime.max.time())

        # AWS-specific: Exclude current day due to 24-hour data lag
        today = date.today()
        yesterday = today - timedelta(days=1)

        # If end_date includes today, cap it at yesterday
        if end_date.date() >= today:
            end_date = datetime.combine(yesterday, datetime.max.time())
            logger.info(
                f"🔵 AWS: Capped end_date to {yesterday} due to 24-hour data lag (was: {end_date.date()})"
            )

        # Handle single-day queries - AWS requires start < end
        if start_date.date() == end_date.date():
            # For same-day queries, extend end date to next day to satisfy API requirements
            next_day = end_date.date() + timedelta(days=1)
            # But never extend beyond yesterday to avoid including today
            if next_day >= today:
                # Instead of extending to today, adjust start time to ensure start < end
                start_date = datetime.combine(start_date.date(), datetime.min.time())
                end_date = datetime.combine(end_date.date(), datetime.max.time())
            else:
                end_date = datetime.combine(next_day, datetime.min.time())

        # Validate range after initial adjustments, but before final date overrides
        if start_date >= end_date:
            # Handle edge case where adjustments result in invalid range
            logger.info(
                f"🔵 AWS: Date range conflict after adjustment, using single-day range for {yesterday}"
            )
            start_date = datetime.combine(yesterday, datetime.min.time())
            end_date = datetime.combine(yesterday, datetime.max.time())

        # Check if dates are too far in the future (should be yesterday or earlier now)
        start_date_for_comparison = (
            start_date.date() if isinstance(start_date, datetime) else start_date
        )
        if start_date_for_comparison > yesterday:
            # Override start date to latest available data instead of failing
            logger.info(
                f"🔵 AWS: Requested start date {start_date_for_comparison} adjusted to {yesterday} (latest available due to 24-hour lag)"
            )
            start_date = datetime.combine(yesterday, datetime.min.time())

        # Also ensure end date is not beyond yesterday
        end_date_for_comparison = end_date.date() if isinstance(end_date, datetime) else end_date
        if end_date_for_comparison > yesterday:
            logger.info(
                f"🔵 AWS: Requested end date {end_date_for_comparison} adjusted to {yesterday} (latest available due to 24-hour lag)"
            )
            end_date = datetime.combine(yesterday, datetime.max.time())

        # Final validation after all adjustments
        if start_date >= end_date:
            logger.info("🔵 AWS: Final range validation failed, using yesterday as single-day range")
            start_date = datetime.combine(yesterday, datetime.min.time())
            end_date = datetime.combine(yesterday, datetime.max.time())

        return start_date, end_date

    async def authenticate(self) -> bool:
        """Authenticate with AWS using various methods."""
        try:
            auth_result = await self.authenticator.authenticate()

            if auth_result.success:
                self.session = auth_result.credentials
                self._create_cost_explorer_client()
                self._authenticated = True
                logger.info(f"AWS authentication successful using {auth_result.method}")

                # Cache cleanup removed - using PostgreSQL instead

                return True
            else:
                logger.error(f"AWS authentication failed: {auth_result.error_message}")
                raise AuthenticationError(f"AWS authentication failed: {auth_result.error_message}")

        except Exception as e:
            logger.error(f"AWS authentication error: {e}")
            raise AuthenticationError(f"AWS authentication error: {e}")

    def _create_cost_explorer_client(self):
        """Create AWS Cost Explorer client with proper configuration."""
        if not self.session:
            raise ConfigurationError("No authenticated AWS session available")

        # Cost Explorer is only available in us-east-1
        config = Config(region_name="us-east-1", retries={"max_attempts": 3, "mode": "adaptive"})

        self.cost_explorer_client = self.session.client("ce", config=config)

        # Create Organizations client for account name resolution
        # Organizations is also only available in us-east-1
        try:
            self.organizations_client = self.session.client("organizations", config=config)
        except Exception as e:
            # Organizations access might not be available (not in org or no permissions)
            logger.debug(f"Could not create Organizations client: {e}")
            self.organizations_client = None

    async def test_connection(self) -> bool:
        """Test the connection to AWS Cost Explorer API."""
        try:
            await self.ensure_authenticated()

            # Test with a minimal API call
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=1)

            if not self.cost_explorer_client:
                raise ValueError("AWS Cost Explorer client not initialized")
            self.cost_explorer_client.get_cost_and_usage(  # type: ignore[unreachable]
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                Granularity="DAILY",
                Metrics=["BlendedCost"],
            )
            return True

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "Throttling":
                logger.warning("AWS Cost Explorer API throttled")
                return True  # Connection is working, just rate limited
            else:
                logger.error(f"AWS Cost Explorer connection test failed: {e}")
                return False
        except Exception as e:
            logger.error(f"AWS connection test error: {e}")
            return False

    def _prepare_cost_request_params(
        self,
        start_date: datetime | date,
        end_date: datetime | date,
        granularity: TimeGranularity,
        group_by: list[str] | None,
        filter_by: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Prepare request parameters for Cost Explorer API."""
        request_params = {
            "TimePeriod": {
                "Start": start_date.strftime("%Y-%m-%d"),
                "End": end_date.strftime("%Y-%m-%d"),
            },
            "Granularity": self.granularity_mapping.get(granularity, "DAILY"),
            "Metrics": self.default_metrics,
        }

        # Add group by dimensions
        if group_by or self.default_group_by:
            group_dimensions = group_by or self.default_group_by
            request_params["GroupBy"] = [
                {"Type": "DIMENSION", "Key": dim} for dim in group_dimensions  # type: ignore[misc]
            ]

        # Add filters if specified
        if filter_by:
            request_params["Filter"] = self._build_filter(filter_by)

        return request_params

    def _generate_date_list(
        self, start_date: datetime | date, end_date: datetime | date
    ) -> list[date]:
        """Generate list of dates in the range."""
        date_list = []
        current_date = start_date.date() if isinstance(start_date, datetime) else start_date
        end_date_obj = end_date.date() if isinstance(end_date, datetime) else end_date

        while current_date <= end_date_obj:
            date_list.append(current_date)
            current_date += timedelta(days=1)

        return date_list

    async def get_cost_data(
        self,
        start_date: datetime | date,
        end_date: datetime | date,
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: list[str] | None = None,
        filter_by: dict[str, Any] | None = None,
    ) -> CostSummary:
        """Retrieve cost data from AWS Cost Explorer."""
        await self.ensure_authenticated()

        # Validate and normalize dates
        start_date, end_date = self.validate_date_range(start_date, end_date)

        # Prepare request parameters
        self._prepare_cost_request_params(start_date, end_date, granularity, group_by, filter_by)

        # Convert date objects to datetime if needed
        start_datetime = (
            datetime.combine(start_date, datetime.min.time())
            if isinstance(start_date, date)
            else start_date
        )
        end_datetime = (
            datetime.combine(end_date, datetime.min.time())
            if isinstance(end_date, date)
            else end_date
        )

        # Get fresh data from API (no caching)
        group_dimensions = group_by or self.default_group_by

        try:
            cost_summary = await self._get_cost_data_with_chunking(
                start_datetime, end_datetime, granularity, group_dimensions, filter_by
            )

            logger.info(
                f"🔵 AWS: Retrieved {len(cost_summary.data_points)} data points, total cost: ${cost_summary.total_cost}"
            )

            return cost_summary

        except ClientError as e:
            self._handle_client_error(e)
            raise  # Re-raise after handling
        except Exception as e:
            logger.error(f"AWS cost data retrieval failed: {e}")
            raise APIError(f"AWS cost data retrieval failed: {e}", provider=self.provider_name)

    async def _make_cost_explorer_request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make a request to the Cost Explorer API with retry logic."""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                if not self.cost_explorer_client:
                    raise ValueError("AWS Cost Explorer client not initialized")
                return self.cost_explorer_client.get_cost_and_usage(**params)  # type: ignore[unreachable]

            except ClientError as e:
                error_code = e.response["Error"]["Code"]

                if error_code == "Throttling" and attempt < max_retries - 1:
                    # Implement exponential backoff for throttling
                    import asyncio

                    await asyncio.sleep(retry_delay * (2**attempt))
                    continue
                else:
                    raise e

        raise APIError(
            "Max retries exceeded for AWS Cost Explorer API", provider=self.provider_name
        )

    async def _get_cost_data_with_chunking(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_dimensions: list[str],
        filter_by: dict[str, Any] | None = None,
    ) -> CostSummary:
        """
        Get cost data with intelligent chunking to avoid AWS Cost Explorer's 5000 record limit.

        AWS Cost Explorer truncates results at 5000 records when using complex grouping like
        SERVICE + LINKED_ACCOUNT. This method uses date-based chunking to ensure we get
        complete data.
        """
        logger.info(
            f"🔵 AWS: Starting chunked data retrieval for {start_date.date()} to {end_date.date()}"
        )

        # Calculate total date range
        total_days = (end_date.date() - start_date.date()).days + 1

        # Determine chunk size based on expected data volume
        # For dual grouping (SERVICE + LINKED_ACCOUNT), we typically see:
        # - ~100-500 services per account
        # - Multiple accounts
        # - This can easily exceed 5000 records for even 1-2 days
        if group_dimensions and len(group_dimensions) >= 2:
            # Very conservative chunking for dual grouping - 1 day at a time
            chunk_days = 1
            logger.info("🔵 AWS: Using 1-day chunks for dual grouping to avoid 5000 record limit")
        else:
            # More aggressive chunking for single grouping
            chunk_days = min(7, total_days)
            logger.info(f"🔵 AWS: Using {chunk_days}-day chunks for single grouping")

        all_data_points = []
        current_start = start_date
        chunk_count = 0

        while current_start.date() <= end_date.date():
            chunk_count += 1
            # Calculate chunk end date
            chunk_end = min(current_start + timedelta(days=chunk_days - 1), end_date)

            logger.info(
                f"🔵 AWS: Processing chunk {chunk_count}: {current_start.date()} to {chunk_end.date()}"
            )

            # Prepare request parameters for this chunk
            chunk_params = {
                "TimePeriod": {
                    "Start": current_start.strftime("%Y-%m-%d"),
                    "End": (chunk_end + timedelta(days=1)).strftime(
                        "%Y-%m-%d"
                    ),  # AWS API requires end > start
                },
                "Granularity": self.granularity_mapping.get(granularity, "DAILY"),
                "Metrics": self.default_metrics,
            }

            # Add group by dimensions
            if group_dimensions:
                chunk_params["GroupBy"] = [
                    {"Type": "DIMENSION", "Key": dim} for dim in group_dimensions  # type: ignore[misc]
                ]

            # Add filters if specified
            if filter_by:
                chunk_params["Filter"] = self._build_filter(filter_by)

            try:
                # Make API request for this chunk
                response = await self._make_cost_explorer_request(chunk_params)

                # Check if we hit the limit
                result_count = 0
                for result in response.get("ResultsByTime", []):
                    result_count += len(result.get("Groups", []))

                if result_count >= 4900:  # Close to the 5000 limit
                    logger.warning(
                        f"🔵 AWS: Chunk {chunk_count} has {result_count} records - approaching 5000 limit!"
                    )

                # Parse response for this chunk
                chunk_summary = await self._parse_cost_response(
                    response, current_start, chunk_end, granularity, group_dimensions
                )

                all_data_points.extend(chunk_summary.data_points)
                logger.info(
                    f"🔵 AWS: Chunk {chunk_count} added {len(chunk_summary.data_points)} data points"
                )

                # Move to next chunk
                current_start = chunk_end + timedelta(days=1)

                # Small delay to be API-friendly
                import asyncio

                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(
                    f"🔵 AWS: Failed to fetch chunk {chunk_count} ({current_start.date()} to {chunk_end.date()}): {e}"
                )
                # Move to next chunk even if this one failed
                current_start = chunk_end + timedelta(days=1)
                continue

        # Calculate total cost
        total_cost = sum(point.amount for point in all_data_points)

        logger.info(
            f"🔵 AWS: Chunked retrieval completed - {len(all_data_points)} total data points, ${total_cost}"
        )

        # Resolve account names for uncached accounts only (fast operation)
        unique_account_ids = {
            point.account_id
            for point in all_data_points
            if point.account_id and point.account_id not in self.account_names_cache
        }
        if unique_account_ids:
            logger.info(
                f"🔵 AWS: Resolving {len(unique_account_ids)} uncached account names (fresh data)"
            )
            await self._resolve_selective_account_names(unique_account_ids)

        enriched_data_points = all_data_points

        return CostSummary(
            provider=self.provider_name,
            start_date=start_date.date(),
            end_date=end_date.date(),
            total_cost=total_cost,
            currency="USD",
            data_points=enriched_data_points,
            granularity=granularity,
            last_updated=datetime.now(),
        )

    def _extract_service_and_account_from_keys(
        self, keys: list[str], group_dimensions: list[str] | None
    ) -> tuple[str | None, str | None]:
        """Extract service name and account ID from AWS group keys based on dimensions."""
        service_name = None
        account_id = None

        logger.debug(f"🔵 AWS: Processing group with keys: {keys}, dimensions: {group_dimensions}")

        if len(keys) == 1:
            # Single dimension grouping
            if group_dimensions and "LINKED_ACCOUNT" in group_dimensions:
                account_id = keys[0]
                logger.debug(f"🔵 AWS: Single dimension LINKED_ACCOUNT: {account_id}")
            elif group_dimensions and "SERVICE" in group_dimensions:
                service_name = keys[0]
                logger.debug(f"🔵 AWS: Single dimension SERVICE: {service_name}")
            else:
                # Fallback - assume it's service name if no dimensions specified
                service_name = keys[0]
                logger.debug(f"🔵 AWS: Single dimension fallback to SERVICE: {service_name}")

        elif len(keys) == 2:
            # Two dimension grouping - check the order
            if group_dimensions and len(group_dimensions) >= 2:
                if group_dimensions[0] == "SERVICE" and group_dimensions[1] == "LINKED_ACCOUNT":
                    service_name, account_id = keys[0], keys[1]
                elif group_dimensions[0] == "LINKED_ACCOUNT" and group_dimensions[1] == "SERVICE":
                    account_id, service_name = keys[0], keys[1]
                else:
                    # Default fallback
                    service_name, account_id = keys[0], keys[1]
            else:
                # Default fallback for two keys
                service_name, account_id = keys[0], keys[1]

            logger.debug(f"🔵 AWS: Dual dimension - service: {service_name}, account: {account_id}")

        return service_name, account_id

    def _extract_cost_from_metrics(self, metrics_data: dict[str, Any]) -> tuple[float, str]:
        """Extract cost amount and currency from AWS metrics data."""
        amount = 0.0
        currency = "USD"

        # Look for UNBLENDED_COST first, then fallback to any other metric
        if "UnblendedCost" in metrics_data:
            metric_data = metrics_data["UnblendedCost"]
            amount = float(metric_data.get("Amount", 0))
            currency = metric_data.get("Unit", "USD")
        elif "UNBLENDED_COST" in metrics_data:
            metric_data = metrics_data["UNBLENDED_COST"]
            amount = float(metric_data.get("Amount", 0))
            currency = metric_data.get("Unit", "USD")
        elif metrics_data:
            # Fallback to first available metric
            first_metric = list(metrics_data.items())[0]
            metric_data = first_metric[1]
            amount = float(metric_data.get("Amount", 0))
            currency = metric_data.get("Unit", "USD")

        return amount, currency

    def _process_aws_cost_groups(
        self, response: dict[str, Any], group_dimensions: list[str] | None
    ) -> dict[tuple[date, str, str | None], dict[str, Any]]:
        """Process AWS cost response groups and aggregate costs to prevent duplication."""
        aggregated_costs: dict[tuple[date, str, str | None], dict[str, Any]] = {}

        for result in response.get("ResultsByTime", []):
            period_start = datetime.strptime(result["TimePeriod"]["Start"], "%Y-%m-%d")

            # Handle grouped costs
            for group in result.get("Groups", []):
                keys = group.get("Keys", [])

                # Extract service name and account ID from keys
                service_name, account_id = self._extract_service_and_account_from_keys(
                    keys, group_dimensions
                )

                # Set defaults for None values
                if service_name is None:
                    service_name = "Unknown"

                # Extract cost metrics
                metrics_data = group.get("Metrics", {})
                amount, currency = self._extract_cost_from_metrics(metrics_data)

                # Aggregate costs by (date, service, account) to prevent duplication
                if amount > 0:  # Only process non-zero amounts
                    normalized_service = self.normalize_service_name(service_name)
                    agg_key = (period_start.date(), normalized_service, account_id)

                    if agg_key not in aggregated_costs:
                        aggregated_costs[agg_key] = {"amount": 0.0, "currency": currency}
                    aggregated_costs[agg_key]["amount"] += amount

        return aggregated_costs

    def _format_account_name(self, account_id: str | None) -> str:
        """Format account name using cached account names."""
        if not account_id:
            return "AWS Account (Unknown)"

        raw_account_name = self.account_names_cache.get(account_id, account_id)
        if raw_account_name and raw_account_name != account_id:
            # We have a proper account name, format as "Name (Account ID)"
            return f"{raw_account_name} ({account_id})"
        else:
            # Fallback to generic format
            return f"AWS Account ({account_id})"

    def _create_data_points_from_aggregated_costs(
        self, aggregated_costs: dict[tuple[date, str, str | None], dict[str, Any]]
    ) -> tuple[list[CostDataPoint], float]:
        """Create data points from aggregated costs and calculate total cost."""
        data_points = []
        total_cost = 0.0

        for (date_val, service_name, account_id), cost_data in aggregated_costs.items():
            amount = cost_data["amount"]
            if amount > 0:  # Only include non-zero costs
                account_name = self._format_account_name(account_id)

                data_points.append(
                    CostDataPoint(
                        date=date_val,
                        amount=amount,
                        currency=cost_data["currency"],
                        service_name=service_name,
                        account_id=account_id,
                        account_name=account_name,
                        region=None,
                    )
                )
                total_cost += amount

        return data_points, total_cost

    async def _parse_cost_response(
        self,
        response: dict[str, Any],
        start_date: datetime,
        end_date: datetime,
        granularity: TimeGranularity,
        group_dimensions: list[str] | None = None,
    ) -> CostSummary:
        """Parse AWS Cost Explorer response into our standard format."""
        # Process response groups and aggregate costs to prevent duplication
        aggregated_costs = self._process_aws_cost_groups(response, group_dimensions)

        # Create data points from aggregated costs
        data_points, total_cost = self._create_data_points_from_aggregated_costs(aggregated_costs)

        logger.debug(
            f"🔵 AWS: Returning cost data with {len(data_points)} points (account IDs only)"
        )

        return CostSummary(
            provider=self.provider_name,
            start_date=start_date.date(),
            end_date=end_date.date(),
            total_cost=total_cost,
            currency="USD",
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
        daily_costs = {}
        for point in cost_summary.data_points:
            date_key = point.date
            if date_key not in daily_costs:
                daily_costs[date_key] = 0.0
            daily_costs[date_key] += point.amount

        return [
            CostDataPoint(date=date_key, amount=amount, currency="USD", service_name=None)
            for date_key, amount in daily_costs.items()
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
        """Get list of supported AWS regions."""
        return [
            "us-east-1",
            "us-east-2",
            "us-west-1",
            "us-west-2",
            "eu-west-1",
            "eu-west-2",
            "eu-west-3",
            "eu-central-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "ap-northeast-1",
            "ap-northeast-2",
            "ap-south-1",
            "ca-central-1",
            "sa-east-1",
        ]

    def get_supported_services(self) -> list[str]:
        """Get list of supported AWS services for cost monitoring."""
        return [
            "Amazon EC2-Instance",
            "Amazon S3",
            "Amazon RDS",
            "Amazon CloudFront",
            "Amazon Lambda",
            "Amazon EBS",
            "Amazon VPC",
            "Amazon Route 53",
            "Amazon CloudWatch",
            "Amazon DynamoDB",
            "Amazon ElastiCache",
            "Amazon Elasticsearch Service",
            "Amazon EKS",
            "Amazon ECS",
            "Amazon SQS",
            "Amazon SNS",
            "Amazon API Gateway",
            "AWS Data Transfer",
        ]

    def normalize_service_name(self, service_name: str) -> str:
        """Normalize AWS service names to a consistent format."""
        # AWS-specific service name normalization
        service_mapping = {
            "Amazon Elastic Compute Cloud - Compute": "EC2",
            "Amazon EC2-Instance": "EC2",
            "Amazon Simple Storage Service": "S3",
            "Amazon Relational Database Service": "RDS",
            "Amazon CloudFront": "CloudFront",
            "AWS Lambda": "Lambda",
            "Amazon Elastic Block Store": "EBS",
            "Amazon Virtual Private Cloud": "VPC",
        }

        return service_mapping.get(service_name, service_name)

    def _build_filter(self, filter_by: dict[str, Any]) -> dict[str, Any]:
        """Build AWS Cost Explorer filter from our generic filter format."""
        # Example filter building - can be expanded based on needs
        aws_filter: dict[str, Any] = {}

        if "services" in filter_by:
            aws_filter = {"Dimensions": {"Key": "SERVICE", "Values": filter_by["services"]}}

        if "regions" in filter_by:
            region_filter = {"Dimensions": {"Key": "REGION", "Values": filter_by["regions"]}}
            if "And" not in aws_filter:
                aws_filter = {"And": [aws_filter] if aws_filter else []}

            # aws_filter["And"] is guaranteed to be a list at this point
            and_filters: list[dict[str, Any]] = aws_filter["And"]
            and_filters.append(region_filter)

        return aws_filter

    async def _enrich_with_account_names(
        self, data_points: list[CostDataPoint]
    ) -> list[CostDataPoint]:
        """Enrich data points with AWS account names from Organizations API with rate limiting."""
        # Get unique account IDs to minimize API calls
        unique_account_ids = {point.account_id for point in data_points if point.account_id}

        logger.info(
            f"🔵 AWS: Resolving account names for {len(unique_account_ids)} unique accounts with rate limiting"
        )

        # Resolve account names with throttling between requests
        for i, account_id in enumerate(unique_account_ids):
            try:
                await self.get_account_name(account_id)  # This caches the name

                # Add small delay between requests to avoid rate limiting (except for last item)
                if i < len(unique_account_ids) - 1:
                    await asyncio.sleep(0.1)  # 100ms between requests

            except Exception as e:
                logger.warning(f"🔵 AWS: Failed to resolve account name for {account_id}: {e}")
                # Continue with other accounts even if one fails

        # Create enriched data points with account names in tags
        enriched_points = []
        for point in data_points:
            if point.account_id and point.account_id in self.account_names_cache:
                account_name = self.account_names_cache[point.account_id]
                display_name = self.format_account_display_name(point.account_id, account_name)

                # Add account name to tags
                tags = point.tags or {}
                tags["account_name"] = display_name

                # Create new data point with enriched tags
                enriched_point = CostDataPoint(
                    date=point.date,
                    amount=point.amount,
                    currency=point.currency,
                    service_name=point.service_name,
                    account_id=point.account_id,
                    resource_id=point.resource_id,
                    region=point.region,
                    tags=tags,
                )
                enriched_points.append(enriched_point)
            else:
                enriched_points.append(point)

        return enriched_points

    async def _resolve_selective_account_names(self, account_ids: set) -> None:
        """Resolve account names for specific account IDs only (fast, selective resolution)."""
        if not account_ids:
            return

        logger.info(f"🔵 AWS: Selective account name resolution for {len(account_ids)} accounts")

        # Resolve only the specified account IDs
        for account_id in account_ids:
            try:
                account_name = await self.get_account_name(account_id)
                logger.debug(f"🔵 AWS: Resolved {account_id} -> {account_name}")
            except Exception as e:
                logger.warning(f"🔵 AWS: Failed to resolve account name for {account_id}: {e}")
                # Cache the failure to avoid repeated attempts
                self.account_names_cache[account_id] = account_id

        logger.info(
            f"🔵 AWS: Selective account name resolution completed for {len(account_ids)} accounts"
        )
        # Save updated cache to persistent storage

    async def resolve_account_names_for_ids(self, account_ids: list[str]) -> dict[str, str]:
        """Resolve account names for specific account IDs and return a mapping.

        Args:
            account_ids: List of AWS account IDs to resolve

        Returns:
            Dictionary mapping account_id -> account_name
        """
        if not account_ids:
            return {}

        # Filter to only uncached account IDs
        uncached_ids = {aid for aid in account_ids if aid and aid not in self.account_names_cache}

        if uncached_ids:
            logger.info(
                f"🔵 AWS: Resolving names for {len(uncached_ids)} uncached accounts (on-demand)"
            )
            await self._resolve_selective_account_names(uncached_ids)
            # Save updated cache to persistent storage

        # Return mapping for all requested IDs
        result = {}
        for account_id in account_ids:
            result[account_id] = self.account_names_cache.get(account_id, account_id)

        return result

    async def resolve_account_names_background(self, data_points: list[CostDataPoint]) -> None:
        """Background task to resolve account names without blocking main data fetch."""
        unique_account_ids = {
            point.account_id
            for point in data_points
            if point.account_id and point.account_id not in self.account_names_cache
        }

        if not unique_account_ids:
            return

        logger.info(f"🔵 AWS: Background resolving {len(unique_account_ids)} account names")

        for account_id in unique_account_ids:
            try:
                await self.get_account_name(account_id)
                # Generous delay to avoid rate limiting
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(
                    f"🔵 AWS: Background account name resolution failed for {account_id}: {e}"
                )
                continue

    async def get_account_name(self, account_id: str) -> str:
        """Get the friendly name for an AWS account ID."""
        if not account_id:
            return "Unknown Account"

        # Check cache first
        if account_id in self.account_names_cache:
            return self.account_names_cache[account_id]

        # Try to get account name from Organizations
        account_name = await self._resolve_account_name_from_organizations(account_id)

        # Cache the result (even if it's just the account ID)
        self.account_names_cache[account_id] = account_name
        # Save updated cache to persistent storage
        return account_name

    async def _resolve_account_name_from_organizations(self, account_id: str) -> str:
        """Resolve account name using AWS Organizations API with rate limiting."""
        if not self.organizations_client:
            return account_id  # Return just the account ID if no Organizations access

        try:  # type: ignore[unreachable]
            # Implement exponential backoff for rate limiting
            max_retries = 3
            base_delay = 1.0  # Start with 1 second

            for attempt in range(max_retries):
                try:
                    # Try to get the account details
                    response = self.organizations_client.describe_account(AccountId=account_id)
                    account_name = response["Account"]["Name"]

                    # Check if this is the management account (cache the org info to avoid repeated calls)
                    if not hasattr(self, "_management_account_id"):
                        org_response = self.organizations_client.describe_organization()
                        self._management_account_id = org_response["Organization"][
                            "MasterAccountId"
                        ]

                    if account_id == self._management_account_id:
                        account_name = f"{account_name} (Management Account)"

                    return account_name

                except ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code", "")

                    if error_code == "TooManyRequestsException" and attempt < max_retries - 1:
                        # Exponential backoff with jitter
                        delay = base_delay * (2**attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"🔵 AWS Organizations rate limited, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        # Re-raise for other error handling
                        raise e

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")

            if error_code in ["AccountNotFoundException"]:
                # Account not in organization - this is expected for accounts outside the org
                logger.debug(f"Account {account_id} not found in organization")
                return account_id
            elif error_code in ["AccessDenied", "AccessDeniedException"]:
                # Missing permissions - log warning and return formatted account ID instead of failing
                logger.warning(
                    f"⚠️ AWS Organizations access denied for account {account_id}. Using account ID instead of name. Required permissions: organizations:DescribeAccount, organizations:DescribeOrganization"
                )
                return account_id
            else:
                logger.error(
                    f"Unexpected AWS Organizations API error for account {account_id}: {e}"
                )
                raise APIError(f"AWS Organizations API error: {e}", provider=self.provider_name)
        except Exception as e:
            logger.error(f"Error resolving account name for {account_id}: {e}")
            raise APIError(f"Account name resolution failed: {e}", provider=self.provider_name)

    def format_account_display_name(self, account_id: str, account_name: str | None = None) -> str:
        """Format account display name as 'Name (Account ID)' or just 'Account ID'."""
        if not account_name or account_name == account_id:
            return account_id

        # If account_name already contains the account ID, don't duplicate it
        if account_id in account_name:
            return account_name

        return f"{account_name} ({account_id})"

    def _handle_client_error(self, error: ClientError):
        """Handle AWS client errors appropriately."""
        error_code = error.response["Error"]["Code"]
        error_message = error.response["Error"]["Message"]

        if error_code == "Throttling":
            raise RateLimitError(
                f"AWS Cost Explorer API rate limit exceeded: {error_message}",
                provider=self.provider_name,
            )
        elif error_code == "UnauthorizedOperation":
            raise AuthenticationError(f"AWS unauthorized: {error_message}")
        elif error_code == "InvalidParameterValue":
            raise ConfigurationError(f"AWS invalid parameter: {error_message}")
        else:
            raise APIError(
                f"AWS Cost Explorer API error ({error_code}): {error_message}",
                status_code=error.response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                provider=self.provider_name,
            )


# Register the AWS provider with the factory
if AWS_AVAILABLE:
    ProviderFactory.register_provider("aws", AWSCostProvider)
else:
    logger.warning("AWS SDK not available, AWS provider not registered")
