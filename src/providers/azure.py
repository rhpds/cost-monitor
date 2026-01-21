"""
Azure Cost Management provider implementation using Azure Cost Management Exports.

Provides Azure-specific cost monitoring functionality using exported CSV files from
Azure Cost Management instead of direct API queries.
"""

import logging
import json
import csv
import io
import os
import hashlib
import pickle
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union, Tuple

try:
    from azure.identity import ClientSecretCredential
    from azure.storage.blob import BlobServiceClient
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

logger = logging.getLogger(__name__)


class AzureCostProvider(CloudCostProvider):
    """Azure Cost Management provider using billing exports."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.credentials = None

        # Azure storage configuration for billing exports
        self.storage_account_name = config.get("export", {}).get("storage_account", "demobillingexports")
        self.container_name = config.get("export", {}).get("container", "demo-billing-exports-actual")
        self.export_name = config.get("export", {}).get("export_name", "demo-billing-exports-actual")

        # Azure authentication configuration
        self.tenant_id = config.get("tenant_id")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")

        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise ConfigurationError("Azure service principal credentials (tenant_id, client_id, client_secret) are required")

        # Initialize blob service client
        self.blob_service_client = None

        # Initialize persistent cache for cost data
        self._init_cache()

    def _get_provider_name(self) -> str:
        return "azure"

    def _init_cache(self):
        """Initialize persistent cache for cost data."""
        self.cache_dir = os.path.expanduser("~/.cache/cost-monitor/azure")
        self.csv_cache_dir = os.path.join(self.cache_dir, "csv_files")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.csv_cache_dir, exist_ok=True)
        # Cache files for 30 days, older files will be cleaned up
        self.cache_max_age_days = 30
        logger.debug(f"Azure cache initialized at: {self.cache_dir}")

    def _get_csv_cache_path(self, blob_name: str) -> str:
        """Get cache file path for a CSV blob."""
        # Create a safe filename from the blob path
        safe_filename = blob_name.replace("/", "_").replace("\\", "_")
        return os.path.join(self.csv_cache_dir, f"{safe_filename}.csv")

    def _is_csv_cached(self, blob_name: str) -> bool:
        """Check if CSV file is already cached."""
        cache_path = self._get_csv_cache_path(blob_name)
        return os.path.exists(cache_path)

    def _load_cached_csv(self, blob_name: str) -> Optional[str]:
        """Load CSV content from cache."""
        try:
            cache_path = self._get_csv_cache_path(blob_name)
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return f.read()
            return None
        except Exception as e:
            logger.warning(f"Failed to load cached CSV: {e}")
            return None

    def _save_csv_to_cache(self, blob_name: str, csv_content: str) -> None:
        """Save CSV content to cache."""
        try:
            cache_path = self._get_csv_cache_path(blob_name)
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(csv_content)
            logger.debug(f"Cached CSV file: {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to cache CSV: {e}")

    async def ensure_authenticated(self):
        """Ensure we have valid authentication to Azure."""
        if self.blob_service_client is None:
            try:
                # Create service principal credential
                credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )

                # Create blob service client
                account_url = f"https://{self.storage_account_name}.blob.core.windows.net"
                self.blob_service_client = BlobServiceClient(
                    account_url=account_url,
                    credential=credential
                )

                # Test connection by listing containers
                containers = list(self.blob_service_client.list_containers())
                logger.info(f"Azure blob storage authentication successful. Found {len(containers)} containers")

            except Exception as e:
                logger.error(f"Azure blob storage authentication failed: {e}")
                raise AuthenticationError(f"Failed to authenticate with Azure: {e}")

    def _find_latest_export_files(self, target_month: date) -> Optional[Dict[str, str]]:
        """Find the latest export files for a given month."""
        try:
            # Generate the expected month directory pattern (YYYYMMDD-YYYYMMDD)
            month_start = target_month.replace(day=1)
            if target_month.month == 12:
                month_end = date(target_month.year + 1, 1, 31)
            else:
                next_month = target_month.replace(month=target_month.month + 1, day=1)
                month_end = (next_month - timedelta(days=1))

            date_pattern = f"{month_start.strftime('%Y%m%d')}-{month_end.strftime('%Y%m%d')}"

            # List blobs in the container that match the export pattern
            prefix = f"billingexportsactual/{self.export_name}/{date_pattern}/"
            container_client = self.blob_service_client.get_container_client(self.container_name)

            # Find the most recent export directory (by GUID)
            export_dirs = {}
            for blob in container_client.list_blobs(name_starts_with=prefix):
                # Extract GUID from path: billingexportsactual/demo-billing-exports-actual/20260101-20260131/{guid}/...
                path_parts = blob.name.split('/')
                if len(path_parts) >= 4:
                    guid = path_parts[3]
                    if guid not in export_dirs:
                        export_dirs[guid] = {"last_modified": blob.last_modified, "blobs": []}
                    export_dirs[guid]["blobs"].append(blob.name)
                    if blob.last_modified > export_dirs[guid]["last_modified"]:
                        export_dirs[guid]["last_modified"] = blob.last_modified

            if not export_dirs:
                logger.warning(f"No export files found for month {date_pattern}")
                return None

            # Get the most recent export directory
            latest_guid = max(export_dirs.keys(), key=lambda g: export_dirs[g]["last_modified"])
            latest_export = export_dirs[latest_guid]

            # Find the main data file (part_1_0001.csv) and manifest
            data_files = {}
            for blob_name in latest_export["blobs"]:
                if blob_name.endswith("part_1_0001.csv"):
                    data_files["main_data"] = blob_name
                elif blob_name.endswith("manifest.json"):
                    data_files["manifest"] = blob_name

            if "main_data" not in data_files:
                logger.error(f"No main data file found in export {latest_guid}")
                return None

            logger.info(f"Found latest export for {date_pattern}: {latest_guid} (updated: {latest_export['last_modified']})")
            return data_files

        except Exception as e:
            logger.error(f"Error finding export files: {e}")
            return None

    def _download_and_parse_csv(self, blob_name: str, target_date: Optional[date] = None) -> List[CostDataPoint]:
        """Download and parse CSV data from blob storage with caching."""
        try:
            # Check if CSV is already cached
            csv_content = self._load_cached_csv(blob_name)

            if csv_content:
                logger.info(f"Using cached CSV data: {blob_name}")
            else:
                # Download blob content
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name,
                    blob=blob_name
                )

                logger.info(f"Downloading export data: {blob_name}")
                blob_data = blob_client.download_blob()
                csv_content = blob_data.readall().decode('utf-8')

                # Cache the downloaded content
                self._save_csv_to_cache(blob_name, csv_content)
                logger.info(f"Cached CSV data for future use: {len(csv_content):,} characters")

            # Parse CSV data
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            cost_points = []

            total_rows = 0
            filtered_rows = 0

            for row in csv_reader:
                total_rows += 1

                # Parse the date field (format: MM/DD/YYYY)
                try:
                    row_date = datetime.strptime(row['date'], '%m/%d/%Y').date()
                except (ValueError, KeyError) as e:
                    logger.debug(f"Could not parse date from row: {e}")
                    continue

                # Filter by target date if specified
                if target_date and row_date != target_date:
                    continue

                filtered_rows += 1

                # Parse cost amount
                try:
                    cost_amount = float(row.get('costInUsd', 0))
                except (ValueError, TypeError):
                    cost_amount = 0.0

                if cost_amount <= 0:
                    continue

                # Extract service name and other metadata
                service_name = row.get('meterCategory', 'Unknown')
                subscription_id = row.get('SubscriptionId', '')
                subscription_name = row.get('subscriptionName', '')
                resource_group = row.get('resourceGroupName', '')

                cost_points.append(CostDataPoint(
                    date=row_date,
                    amount=cost_amount,
                    currency="USD",
                    service_name=service_name,
                    account_id=subscription_id,
                    region=row.get('location', ''),
                    additional_properties={
                        'subscription_name': subscription_name,
                        'resource_group': resource_group,
                        'product_name': row.get('ProductName', ''),
                        'meter_name': row.get('meterName', '')
                    }
                ))

            logger.info(f"Processed {total_rows} total rows, {filtered_rows} matching date filter, {len(cost_points)} with costs")
            return cost_points

        except Exception as e:
            logger.error(f"Error downloading/parsing CSV data: {e}")
            return []

    async def get_cost_data(
        self,
        start_date: Union[datetime, date],
        end_date: Union[datetime, date],
        granularity: TimeGranularity = TimeGranularity.DAILY,
        group_by: Optional[List[str]] = None,
        filter_by: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> CostSummary:
        """Retrieve cost data from Azure Cost Management exports."""
        await self.ensure_authenticated()

        # Validate and normalize dates
        start_date, end_date = self.validate_date_range(start_date, end_date)

        logger.info(f"🔍 Azure: Getting cost data from exports for {start_date.date()} to {end_date.date()}")

        # Process each month that overlaps with the date range
        all_cost_points = []
        current_month = start_date.replace(day=1).date()

        while current_month <= end_date.date():
            # Find export files for this month
            export_files = self._find_latest_export_files(current_month)

            if export_files and "main_data" in export_files:
                # Download and parse the main data file
                month_cost_points = self._download_and_parse_csv(export_files["main_data"])

                # Filter to the requested date range
                for point in month_cost_points:
                    if start_date.date() <= point.date <= end_date.date():
                        all_cost_points.append(point)
            else:
                logger.warning(f"No export data found for month {current_month}")

            # Move to next month
            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)

        # Calculate total cost
        total_cost = sum(point.amount for point in all_cost_points)

        # Group by date for daily summary
        daily_summary = {}
        for point in all_cost_points:
            if point.date not in daily_summary:
                daily_summary[point.date] = 0.0
            daily_summary[point.date] += point.amount

        logger.info(f"💰 Azure: Retrieved {len(all_cost_points)} cost points, total ${total_cost:.2f}")

        return CostSummary(
            provider=self._get_provider_name(),
            start_date=start_date.date(),
            end_date=end_date.date(),
            total_cost=total_cost,
            currency="USD",
            data_points=all_cost_points,
            daily_summary=daily_summary
        )

    async def test_connection(self) -> bool:
        """Test the connection to Azure blob storage."""
        try:
            await self.ensure_authenticated()

            # Try to list containers to verify access
            containers = list(self.blob_service_client.list_containers())
            logger.info(f"Azure blob storage connection successful")
            return True

        except Exception as e:
            logger.error(f"Azure blob storage connection test failed: {e}")
            return False


# Register the Azure provider with the factory
if AZURE_AVAILABLE:
    ProviderFactory.register_provider("azure", AzureCostProvider)
else:
    logger.warning("Azure SDK not available, Azure provider not registered")