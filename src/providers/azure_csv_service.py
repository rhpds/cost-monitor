"""
Azure CSV processing service functions.

Contains helper functions for Azure CSV download, caching, parsing,
and data transformation to reduce complexity in the main Azure provider.
"""

import csv
import hashlib
import io
import logging
import os
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from .base import CostDataPoint

logger = logging.getLogger(__name__)


def validate_cache_and_setup_lock(blob_name: str) -> tuple[str, bool, str]:
    """Validate cache settings and setup download lock key."""
    # Check if this is current month data (files still growing, use short-lived cache)
    current_month = date.today().replace(day=1)
    is_current_month = bool(blob_name and current_month.strftime("%Y%m%d") in blob_name)

    # Create a lock key for this specific file to prevent concurrent downloads
    lock_key = f"azure_download_lock:{hashlib.md5(blob_name.encode()).hexdigest()}"

    return lock_key, is_current_month, current_month.strftime("%Y%m%d")


def check_current_month_cache_age(
    blob_name: str, csv_content: str, is_current_month: bool, get_cache_path_func
) -> str | None:
    """Check if current month cached data is recent enough (within 1 hour)."""
    if not (csv_content and is_current_month):
        return csv_content

    cache_path = get_cache_path_func(blob_name)
    try:
        cache_age_seconds = time.time() - os.path.getmtime(cache_path)
        if cache_age_seconds > 3600:  # 1 hour
            logger.info(
                f"Current month cache expired ({cache_age_seconds/3600:.1f}h old), will check for updates: {blob_name}"
            )
            return None  # Force refresh check
        else:
            logger.info(
                f"Using recent current month cache ({cache_age_seconds/60:.1f}m old): {blob_name}"
            )
            return csv_content
    except OSError as e:
        logger.warning(f"Failed to check cache age: {e}")
        return None  # Force refresh on error


def acquire_download_lock(lock_key: str) -> tuple[bool, Any]:
    """Acquire Redis download lock to prevent concurrent downloads."""
    lock_acquired = False
    redis_client = None

    try:
        import redis

        redis_client = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )

        # Try to acquire lock for 10 minutes with 30 second timeout for lock acquisition
        lock_acquired = bool(redis_client.set(lock_key, "downloading", ex=600, nx=True))

        if not lock_acquired:
            logger.info(f"Another process downloading, lock key: {lock_key}")

    except (ImportError, Exception) as e:
        logger.warning(f"Redis lock failed, proceeding without lock: {e}")

    return lock_acquired, redis_client


def wait_for_concurrent_download(
    blob_name: str, load_cached_func: Callable[[str], str | None]
) -> str | None:
    """Wait for concurrent download to complete and check for cached result."""
    logger.info(f"Another process downloading {blob_name}, waiting...")
    for _attempt in range(6):  # Wait up to 30 seconds
        time.sleep(5)
        csv_content = load_cached_func(blob_name)
        if csv_content:
            logger.info(f"Using cached CSV data after wait: {blob_name}")
            return csv_content

    logger.warning(f"Cache still empty after 30s wait, proceeding with download: {blob_name}")
    return None


def handle_etag_conditional_download(
    blob_client, blob_name: str, is_current_month: bool, get_cache_path_func
) -> tuple[str | None, str]:
    """Handle ETag-based conditional downloads for current month data."""
    etag_cache_path = get_cache_path_func(blob_name) + ".etag"
    cached_etag = None

    if is_current_month and os.path.exists(etag_cache_path):
        try:
            with open(etag_cache_path) as f:
                cached_etag = f.read().strip()
            logger.info(f"Found cached ETag for conditional download: {cached_etag}")
        except Exception as e:
            logger.warning(f"Failed to read cached ETag: {e}")

    return cached_etag, etag_cache_path


def download_blob_with_etag_check(
    blob_client,
    cached_etag: str | None,
    is_current_month: bool,
    blob_name: str,
    etag_cache_path: str,
    load_cached_func: Callable[[str], str | None],
) -> str:
    """Download blob with ETag checking for efficient updates."""
    if cached_etag and is_current_month:
        # Get blob properties to check ETag
        blob_properties = blob_client.get_blob_properties()
        current_etag = blob_properties.etag

        if current_etag == cached_etag:
            # File hasn't changed, use cached version
            csv_content = load_cached_func(blob_name)
            if csv_content is not None:
                logger.info(f"File unchanged (ETag match), using cached data: {blob_name}")
                return csv_content
            else:
                logger.warning(
                    f"ETag match but no cached content found, downloading fresh: {blob_name}"
                )

        # File changed or no cached content, download new version
        blob_data = blob_client.download_blob()
        downloaded_content: str = blob_data.readall().decode("utf-8")
        logger.info(f"Downloaded fresh data: {blob_name}")

        # Save new ETag
        with open(etag_cache_path, "w") as f:
            f.write(current_etag)
        return downloaded_content
    else:
        # No cached ETag or not current month, download normally
        blob_data = blob_client.download_blob()
        fresh_content: str = blob_data.readall().decode("utf-8")

        # Save ETag for future conditional downloads (current month only)
        if is_current_month:
            try:
                blob_properties = blob_client.get_blob_properties()
                with open(etag_cache_path, "w") as f:
                    f.write(blob_properties.etag)
                logger.info(f"Saved ETag for future conditional downloads: {blob_properties.etag}")
            except Exception as e:
                logger.warning(f"Failed to save ETag: {e}")

        return fresh_content


def release_download_lock(lock_acquired: bool, redis_client: Any, lock_key: str) -> None:
    """Release the download lock if acquired."""
    if lock_acquired and redis_client:
        try:
            redis_client.delete(lock_key)
            logger.debug(f"Released download lock: {lock_key}")
        except Exception as e:
            logger.warning(f"Failed to release lock: {e}")


def parse_csv_date_field(row: dict[str, Any]) -> date | None:
    """Parse date field from CSV row, trying multiple field names and formats."""
    date_str = (
        row.get("date") or row.get("billingPeriodStartDate") or row.get("servicePeriodStartDate")
    )
    if not date_str:
        return None

    try:
        # Try different date formats
        for date_format in ["%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"]:
            try:
                return datetime.strptime(date_str, date_format).date()
            except ValueError:
                continue

        logger.debug(f"Could not parse date: '{date_str}'")
        return None
    except (ValueError, KeyError) as e:
        logger.debug(f"Could not parse date from row: {e}")
        return None


def extract_cost_amount(row: dict[str, Any]) -> float:
    """Extract cost amount from CSV row using validated billing currency field."""
    # VALIDATED: use costInBillingCurrency for accurate billing
    # See detailed validation comments in original function
    try:
        cost_amount = float(row.get("costInBillingCurrency", 0))
    except (ValueError, TypeError):
        cost_amount = 0.0
    return cost_amount


def extract_service_metadata(row: dict[str, Any]) -> dict[str, str]:
    """Extract service name and metadata from CSV row."""
    service_name = row.get("meterCategory", "Unknown")
    subscription_id = row.get("SubscriptionId", "")
    subscription_name = row.get("subscriptionName", "")
    resource_group = row.get("resourceGroupName", "")

    # Extract currency (use billingCurrency since we use costInBillingCurrency)
    currency = row.get("billingCurrency", "USD")
    if not currency or currency.strip() == "":
        currency = "USD"

    # Format account name as "Subscription Name (Subscription ID)"
    if subscription_name and subscription_name.strip():
        formatted_account_name = f"{subscription_name} ({subscription_id})"
    else:
        formatted_account_name = f"Azure Subscription ({subscription_id})"

    return {
        "service_name": service_name,
        "subscription_id": subscription_id,
        "subscription_name": subscription_name,
        "resource_group": resource_group,
        "currency": currency,
        "formatted_account_name": formatted_account_name,
    }


def create_cost_data_point(
    row: dict[str, Any], row_date: date, cost_amount: float, metadata: dict[str, str]
) -> CostDataPoint:
    """Create a CostDataPoint from parsed CSV row data."""
    return CostDataPoint(
        date=row_date,
        amount=cost_amount,
        currency=metadata["currency"],
        service_name=metadata["service_name"],
        account_id=metadata["subscription_id"],
        account_name=metadata["formatted_account_name"],
        region=row.get("location", ""),
        resource_id=row.get("resourceGroupName", ""),
        tags={
            "subscription_name": metadata["subscription_name"],
            "resource_group": metadata["resource_group"],
            "product_name": row.get("ProductName", ""),
            "meter_name": row.get("meterName", ""),
        },
    )


def parse_csv_content_to_cost_points(
    csv_content: str, target_date: date | None = None
) -> list[CostDataPoint]:
    """Parse CSV content into CostDataPoint objects with filtering and validation."""
    csv_reader = csv.DictReader(io.StringIO(csv_content))
    cost_points = []

    total_rows = 0
    filtered_rows = 0
    sample_logged = False

    for row in csv_reader:
        total_rows += 1

        # Parse the date field
        row_date = parse_csv_date_field(row)
        if row_date is None:
            continue

        # Filter by target date if specified
        if target_date and row_date != target_date:
            continue

        filtered_rows += 1

        # Extract cost amount
        cost_amount = extract_cost_amount(row)
        if cost_amount <= 0:
            continue

        # Extract service metadata
        metadata = extract_service_metadata(row)

        # Create cost data point
        cost_points.append(create_cost_data_point(row, row_date, cost_amount, metadata))

        # Log first few cost points for debugging
        if not sample_logged and len(cost_points) <= 3:
            logger.info(
                f"Sample cost point {len(cost_points)}: {row_date} - {metadata['service_name']} - {metadata['currency']} {cost_amount:.6f}"
            )
            if len(cost_points) == 3:
                sample_logged = True

    logger.info(
        f"Processed {total_rows} total rows, {filtered_rows} matching date filter, {len(cost_points)} with costs"
    )
    return cost_points
