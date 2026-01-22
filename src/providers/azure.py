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
                container_names = [c.name for c in containers]
                logger.info(f"Azure blob storage authentication successful. Found {len(containers)} containers: {container_names}")

            except Exception as e:
                logger.error(f"Azure blob storage authentication failed: {e}")
                raise AuthenticationError(f"Failed to authenticate with Azure: {e}")

    def _get_export_containers(self) -> List[str]:
        """Get list of containers that might contain export data."""
        try:
            containers = []
            container_list = self.blob_service_client.list_containers()

            # Look for containers that might contain our export
            target_containers = [self.container_name, 'cost-exports', 'exports', 'demo-billing-exports-actual', 'demo-billing-exports-amortized']

            for container in container_list:
                if (container.name in target_containers or
                    self.export_name.lower() in container.name.lower() or
                    'billing' in container.name.lower() or
                    'export' in container.name.lower()):
                    containers.append(container.name)
                    logger.info(f"Found potential export container: {container.name}")

            # If no specific containers found, try the configured container
            if not containers and self.container_name:
                containers = [self.container_name]
                logger.info(f"Using configured container: {self.container_name}")

            return containers

        except Exception as e:
            logger.error(f"Error listing containers: {e}")
            return [self.container_name] if self.container_name else []

    def _find_export_folders_in_container(self, container_name: str, target_month: date) -> List[Dict]:
        """Find export folders in a container that contain data for target month."""
        import re
        from datetime import datetime as dt, timedelta

        try:
            # Generate target date patterns
            month_start = target_month.replace(day=1)
            if target_month.month == 12:
                month_end = date(target_month.year + 1, 1, 31)
            else:
                next_month = target_month.replace(month=target_month.month + 1, day=1)
                month_end = (next_month - timedelta(days=1))

            target_date_pattern = f"{month_start.strftime('%Y%m%d')}-{month_end.strftime('%Y%m%d')}"

            container_client = self.blob_service_client.get_container_client(container_name)
            blob_list = container_client.list_blobs()
            folder_candidates = []

            logger.info(f"Scanning container {container_name} for exports covering {target_date_pattern}")

            # Look for folders that match date ranges
            processed_paths = set()
            for blob in blob_list:
                blob_path = blob.name

                # Skip if we've already processed this folder path
                path_parts = blob_path.split('/')
                if len(path_parts) < 3:
                    continue

                folder_base = '/'.join(path_parts[:3])
                if folder_base in processed_paths:
                    continue
                processed_paths.add(folder_base)

                # Look for our export name and date range patterns
                if (self.export_name in blob_path or 'billing' in blob_path.lower() or 'export' in blob_path.lower()):
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

                                # Check if this folder's date range overlaps with our target month
                                if folder_start <= month_end and folder_end >= month_start:
                                    # Build folder path up to the date range part
                                    folder_path_parts = []
                                    for i, path_part in enumerate(path_parts):
                                        folder_path_parts.append(path_part)
                                        if path_part == part:  # Found the date range part
                                            break

                                    if len(folder_path_parts) >= 2:
                                        # Get the full folder path including date range
                                        folder_path = '/'.join(folder_path_parts)

                                        overlap_days = min(folder_end, month_end) - max(folder_start, month_start) + timedelta(days=1)

                                        folder_candidates.append({
                                            'path': folder_path,
                                            'container': container_name,
                                            'start_date': folder_start,
                                            'end_date': folder_end,
                                            'overlap_days': overlap_days.days,
                                            'last_modified': blob.last_modified
                                        })

                                        logger.debug(f"Found export folder: {folder_path} "
                                                   f"(covers {folder_start} to {folder_end}, overlap: {overlap_days.days} days)")
                                        break

                            except ValueError as e:
                                logger.debug(f"Could not parse date range from {part}: {e}")
                                continue

            # Sort candidates by overlap (most overlap first), then by recency
            folder_candidates.sort(key=lambda x: (-x['overlap_days'], -x['last_modified'].timestamp() if x['last_modified'] else 0))

            logger.info(f"Found {len(folder_candidates)} export folders in {container_name} covering {target_date_pattern}")
            for candidate in folder_candidates[:5]:  # Log top 5
                logger.info(f"  - {candidate['path']} (overlap: {candidate['overlap_days']} days)")

            return folder_candidates

        except Exception as e:
            logger.error(f"Error scanning container {container_name}: {e}")
            return []

    def _find_latest_export_files(self, target_month: date) -> Optional[Dict[str, str]]:
        """Find the latest export files for a given month using sophisticated discovery."""
        try:
            # First, discover all potential containers
            containers = self._get_export_containers()

            if not containers:
                logger.error("No export containers found")
                return None

            all_export_folders = []

            # Search each container for export folders
            for container in containers:
                container_folders = self._find_export_folders_in_container(container, target_month)
                all_export_folders.extend(container_folders)

            if not all_export_folders:
                logger.warning(f"No export folders found for {target_month}")
                return None

            # Sort by overlap (most days) and recency - take the best one
            best_export = all_export_folders[0]
            logger.info(f"Selected best export: {best_export['path']} from container {best_export['container']} "
                       f"(covers {best_export['start_date']} to {best_export['end_date']}, "
                       f"overlap: {best_export['overlap_days']} days)")

            # Now find the latest GUID directory within this export folder
            container_client = self.blob_service_client.get_container_client(best_export['container'])

            # Look for GUID subdirectories in the export folder
            export_dirs = {}
            prefix = best_export['path'] + "/"

            for blob in container_client.list_blobs(name_starts_with=prefix):
                path_parts = blob.name.split('/')
                # Look for GUID pattern after the export path
                export_path_parts = best_export['path'].split('/')
                if len(path_parts) > len(export_path_parts):
                    guid_candidate = path_parts[len(export_path_parts)]
                    # Check if this looks like a GUID (36 chars with hyphens)
                    if len(guid_candidate) == 36 and guid_candidate.count('-') == 4:
                        if guid_candidate not in export_dirs:
                            export_dirs[guid_candidate] = {"last_modified": blob.last_modified, "blobs": []}
                        export_dirs[guid_candidate]["blobs"].append(blob.name)
                        if blob.last_modified > export_dirs[guid_candidate]["last_modified"]:
                            export_dirs[guid_candidate]["last_modified"] = blob.last_modified

            if not export_dirs:
                logger.error(f"No GUID directories found in export folder {best_export['path']}")
                return None

            # Get the most recent export directory
            latest_guid = max(export_dirs.keys(), key=lambda g: export_dirs[g]["last_modified"])
            latest_export = export_dirs[latest_guid]

            logger.info(f"Found latest export GUID: {latest_guid} (updated: {latest_export['last_modified']})")

            # Find manifest file
            manifest_file = None
            for blob_name in latest_export["blobs"]:
                if blob_name.endswith("manifest.json"):
                    manifest_file = blob_name
                    break

            if not manifest_file:
                logger.error(f"No manifest file found in export {latest_guid}")
                # Fallback: scan for CSV files directly
                csv_files = []
                for blob_name in latest_export["blobs"]:
                    if blob_name.endswith(".csv"):
                        csv_files.append({
                            "name": blob_name,
                            "byte_count": 0,  # Unknown without manifest
                            "row_count": 0    # Unknown without manifest
                        })

                if csv_files:
                    logger.info(f"Found {len(csv_files)} CSV files without manifest")
                    return {"csv_files": csv_files}
                else:
                    return None

            # Parse manifest to get the definitive list of CSV files
            manifest = self._parse_manifest(manifest_file, best_export['container'])
            if not manifest or "blobs" not in manifest:
                logger.error(f"Invalid manifest or missing blobs array in {latest_guid}")
                return None

            # Extract CSV files from manifest
            csv_files = []
            for blob_info in manifest["blobs"]:
                blob_name = blob_info.get("blobName", "")
                if blob_name.endswith(".csv"):
                    csv_files.append({
                        "name": blob_name,
                        "byte_count": blob_info.get("byteCount", 0),
                        "row_count": blob_info.get("dataRowCount", 0)
                    })

            if not csv_files:
                logger.error(f"No CSV files found in manifest for {latest_guid}")
                return None

            logger.info(f"Found {len(csv_files)} CSV files in manifest: {[f['name'].split('/')[-1] for f in csv_files]}")
            total_rows = sum(f["row_count"] for f in csv_files)
            total_size_mb = sum(f["byte_count"] for f in csv_files) / 1024 / 1024
            logger.info(f"Total export data: {total_rows:,} rows, {total_size_mb:.1f}MB across {len(csv_files)} files")

            return {"csv_files": csv_files, "container": best_export['container']}

        except Exception as e:
            logger.error(f"Error finding export files: {e}")
            return None

    def _parse_manifest(self, manifest_blob_name: str, container_name: str = None) -> Optional[Dict]:
        """Parse the manifest.json file to get export metadata."""
        try:
            container = container_name or self.container_name
            blob_client = self.blob_service_client.get_blob_client(
                container=container,
                blob=manifest_blob_name
            )
            manifest_data = blob_client.download_blob().readall().decode('utf-8')
            manifest = json.loads(manifest_data)
            logger.info(f"Parsed manifest with {len(manifest.get('blobs', []))} files from container {container}")
            return manifest
        except Exception as e:
            logger.error(f"Failed to parse manifest {manifest_blob_name} from container {container_name}: {e}")
            return None

    def _download_and_parse_csv(self, blob_name: str, container_name: str = None, target_date: Optional[date] = None) -> List[CostDataPoint]:
        """Download and parse CSV data from blob storage with caching."""
        try:
            # Check if this is current month data (files still growing, don't use cache)
            current_month = date.today().replace(day=1)
            is_current_month = blob_name and current_month.strftime('%Y%m%d') in blob_name

            # Check if CSV is already cached (skip cache for current month)
            csv_content = None
            if not is_current_month:
                csv_content = self._load_cached_csv(blob_name)

            if csv_content:
                logger.info(f"Using cached CSV data: {blob_name}")
            else:
                if is_current_month:
                    logger.info(f"Current month detected - downloading fresh data: {blob_name}")
                else:
                    logger.info(f"No cache found - downloading data: {blob_name}")
                # Download blob content
                container = container_name or self.container_name
                blob_client = self.blob_service_client.get_blob_client(
                    container=container,
                    blob=blob_name
                )

                logger.info(f"Downloading export data: {blob_name}")
                blob_data = blob_client.download_blob()
                csv_content = blob_data.readall().decode('utf-8')

                # Cache the downloaded content (skip caching for current month to allow for updates)
                if not is_current_month:
                    self._save_csv_to_cache(blob_name, csv_content)
                    logger.info(f"Cached CSV data for future use: {len(csv_content):,} characters")
                else:
                    logger.info(f"Skipping cache for current month file: {len(csv_content):,} characters")

            # Parse CSV data
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            cost_points = []

            total_rows = 0
            filtered_rows = 0
            sample_logged = False

            for row in csv_reader:
                total_rows += 1

                # Parse the date field - try multiple field names and formats
                date_str = row.get('date') or row.get('billingPeriodStartDate') or row.get('servicePeriodStartDate')
                if not date_str:
                    continue

                try:
                    # Try different date formats
                    row_date = None
                    for date_format in ['%m/%d/%Y', '%Y-%m-%d', '%Y%m%d']:
                        try:
                            row_date = datetime.strptime(date_str, date_format).date()
                            break
                        except ValueError:
                            continue

                    if row_date is None:
                        logger.debug(f"Could not parse date: '{date_str}'")
                        continue
                except (ValueError, KeyError) as e:
                    logger.debug(f"Could not parse date from row: {e}")
                    continue

                # Filter by target date if specified
                if target_date and row_date != target_date:
                    continue

                filtered_rows += 1

                # Parse cost amount - use costInBillingCurrency to avoid duplication
                # Analysis shows costInBillingCurrency, costInPricingCurrency, and costInUsd
                # often contain identical values, causing 3x cost inflation if not careful
                try:
                    cost_amount = float(row.get('costInBillingCurrency', 0))
                except (ValueError, TypeError):
                    cost_amount = 0.0

                if cost_amount <= 0:
                    continue

                # Extract service name and other metadata
                service_name = row.get('meterCategory', 'Unknown')
                subscription_id = row.get('SubscriptionId', '')
                subscription_name = row.get('subscriptionName', '')
                resource_group = row.get('resourceGroupName', '')

                # Extract currency (use billingCurrency since we use costInBillingCurrency)
                currency = row.get('billingCurrency', 'USD')
                if not currency or currency.strip() == '':
                    currency = 'USD'

                cost_points.append(CostDataPoint(
                    date=row_date,
                    amount=cost_amount,
                    currency=currency,
                    service_name=service_name,
                    account_id=subscription_id,
                    region=row.get('location', ''),
                    resource_id=row.get('resourceGroupName', ''),
                    tags={
                        'subscription_name': subscription_name,
                        'resource_group': resource_group,
                        'product_name': row.get('ProductName', ''),
                        'meter_name': row.get('meterName', '')
                    }
                ))

                # Log first few cost points for debugging
                if not sample_logged and len(cost_points) <= 3:
                    logger.info(f"Sample cost point {len(cost_points)}: {row_date} - {service_name} - {currency} {cost_amount:.6f}")
                    if len(cost_points) == 3:
                        sample_logged = True

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

            if export_files and "csv_files" in export_files:
                # Process all CSV files found in the manifest
                month_cost_points = []
                csv_files_processed = 0
                total_manifest_rows = sum(f["row_count"] for f in export_files["csv_files"])
                container = export_files.get("container", self.container_name)

                logger.info(f"📊 Azure: Processing export with {len(export_files['csv_files'])} files, {total_manifest_rows:,} total rows from manifest")
                logger.info(f"📊 Azure: Using container: {container}")

                for csv_file_info in export_files["csv_files"]:
                    csv_file_name = csv_file_info["name"]
                    expected_rows = csv_file_info["row_count"]
                    file_size_mb = csv_file_info["byte_count"] / 1024 / 1024

                    logger.info(f"Processing: {csv_file_name.split('/')[-1]} ({file_size_mb:.1f}MB, {expected_rows:,} rows expected)")
                    csv_points = self._download_and_parse_csv(csv_file_name, container)
                    month_cost_points.extend(csv_points)
                    csv_files_processed += 1
                    logger.info(f"📊 Azure: Processed {csv_file_name.split('/')[-1]} - got {len(csv_points):,} cost points (expected {expected_rows:,})")

                logger.info(f"📊 Azure: Processed {csv_files_processed} CSV files with {len(month_cost_points):,} total cost points")

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

        # Determine primary currency from data (most common currency)
        if all_cost_points:
            currencies = [point.currency for point in all_cost_points]
            primary_currency = max(set(currencies), key=currencies.count)
        else:
            primary_currency = "USD"

        logger.info(f"💰 Azure: Retrieved {len(all_cost_points)} cost points, total {primary_currency} {total_cost:.2f}")

        return CostSummary(
            provider=self._get_provider_name(),
            start_date=start_date.date(),
            end_date=end_date.date(),
            total_cost=total_cost,
            currency=primary_currency,
            data_points=all_cost_points,
            granularity=granularity,
            last_updated=datetime.now()
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

    async def authenticate(self) -> bool:
        """Authenticate with Azure."""
        try:
            await self.ensure_authenticated()
            return True
        except Exception:
            return False

    async def get_current_month_cost(self) -> float:
        """Get the current month's total cost."""
        now = datetime.now()
        start_of_month = now.replace(day=1)
        cost_summary = await self.get_cost_data(start_of_month, now)
        return cost_summary.total_cost

    async def get_daily_costs(self, start_date: Union[datetime, date], end_date: Union[datetime, date]) -> List[CostDataPoint]:
        """Get daily cost breakdown for the specified period."""
        cost_summary = await self.get_cost_data(start_date, end_date)
        return cost_summary.data_points

    async def get_service_costs(self, start_date: Union[datetime, date], end_date: Union[datetime, date], top_n: int = 10) -> Dict[str, float]:
        """Get cost breakdown by service for the specified period."""
        cost_summary = await self.get_cost_data(start_date, end_date)
        service_costs = {}
        for point in cost_summary.data_points:
            service = point.service_name or "Unknown"
            service_costs[service] = service_costs.get(service, 0.0) + point.amount

        # Return top N services by cost
        sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_services[:top_n])

    def get_supported_regions(self) -> List[str]:
        """Get list of supported regions for this provider."""
        return [
            "eastus", "eastus2", "southcentralus", "westus2", "westus3",
            "australiaeast", "southeastasia", "northeurope", "swedencentral",
            "uksouth", "westeurope", "centralus", "southafricanorth",
            "centralindia", "eastasia", "japaneast", "koreacentral",
            "canadacentral", "francecentral", "germanywestcentral",
            "norwayeast", "polandcentral", "switzerlandnorth", "uaenorth",
            "brazilsouth", "eastus2euap", "qatarcentral", "centralusstage",
            "eastusstage", "eastus2stage", "northcentralusstage",
            "southcentralusstage", "westusstage", "westus2stage"
        ]

    def get_supported_services(self) -> List[str]:
        """Get list of supported services for cost monitoring."""
        return [
            "Virtual Machines", "Storage", "Networking", "Databases",
            "App Service", "Azure Functions", "Container Instances",
            "Kubernetes Service", "Cognitive Services", "Machine Learning",
            "Data Factory", "Synapse Analytics", "Event Hubs", "Service Bus",
            "API Management", "Application Gateway", "Load Balancer",
            "VPN Gateway", "ExpressRoute", "CDN", "Traffic Manager",
            "DNS", "Monitor", "Security Center", "Key Vault"
        ]


# Register the Azure provider with the factory
if AZURE_AVAILABLE:
    ProviderFactory.register_provider("azure", AzureCostProvider)
else:
    logger.warning("Azure SDK not available, Azure provider not registered")