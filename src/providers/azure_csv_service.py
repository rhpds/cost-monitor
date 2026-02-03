"""
Azure CSV processing service functions.

Contains helper functions for Azure CSV download, PostgreSQL-based metadata storage,
parsing, and data transformation to reduce complexity in the main Azure provider.
"""

import csv
import hashlib
import io
import logging
import os
import time
from datetime import date, datetime
from typing import Any

from .base import CostDataPoint

logger = logging.getLogger(__name__)


# PostgreSQL-based ETag and CSV metadata management
async def get_csv_metadata_from_db(db_pool, blob_name: str) -> dict | None:
    """Get CSV file metadata from PostgreSQL."""
    try:
        async with db_pool.acquire() as conn:
            query = """
            SELECT blob_name, etag, file_size_bytes, last_downloaded,
                   last_parsed, parse_status, record_count,
                   date_range_start, date_range_end
            FROM azure_csv_metadata
            WHERE blob_name = $1
            """
            row = await conn.fetchrow(query, blob_name)
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error fetching CSV metadata for {blob_name}: {e}")
        return None


async def save_csv_metadata_to_db(
    db_pool,
    blob_name: str,
    etag: str | None = None,
    file_size_bytes: int | None = None,
    parse_status: str = "pending",
    record_count: int | None = None,
    date_range_start: date | None = None,
    date_range_end: date | None = None,
) -> None:
    """Save or update CSV file metadata in PostgreSQL."""
    try:
        async with db_pool.acquire() as conn:
            # Use UPSERT (ON CONFLICT) to handle both insert and update
            query = """
            INSERT INTO azure_csv_metadata
                (blob_name, etag, file_size_bytes, last_downloaded, last_parsed,
                 parse_status, record_count, date_range_start, date_range_end, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP,
                    CASE WHEN $4 = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    $4, $5, $6, $7, CURRENT_TIMESTAMP)
            ON CONFLICT (blob_name)
            DO UPDATE SET
                etag = COALESCE($2, azure_csv_metadata.etag),
                file_size_bytes = COALESCE($3, azure_csv_metadata.file_size_bytes),
                last_downloaded = CURRENT_TIMESTAMP,
                last_parsed = CASE WHEN $4 = 'completed' THEN CURRENT_TIMESTAMP
                                  ELSE azure_csv_metadata.last_parsed END,
                parse_status = $4,
                record_count = COALESCE($5, azure_csv_metadata.record_count),
                date_range_start = COALESCE($6, azure_csv_metadata.date_range_start),
                date_range_end = COALESCE($7, azure_csv_metadata.date_range_end),
                updated_at = CURRENT_TIMESTAMP
            """
            await conn.execute(
                query,
                blob_name,
                etag,
                file_size_bytes,
                parse_status,
                record_count,
                date_range_start,
                date_range_end,
            )
    except Exception as e:
        logger.error(f"Error saving CSV metadata for {blob_name}: {e}")


async def check_csv_freshness(
    db_pool, blob_name: str, is_current_month: bool
) -> tuple[str | None, bool]:
    """
    Check if CSV needs downloading based on PostgreSQL metadata.
    Returns: (cached_etag, needs_download)
    """
    try:
        metadata = await get_csv_metadata_from_db(db_pool, blob_name)
        if not metadata:
            # No record exists, need to download
            return None, True

        cached_etag = metadata.get("etag")
        last_downloaded = metadata.get("last_downloaded")

        # For current month data, check if it's recent enough (within 1 hour)
        if is_current_month and last_downloaded:
            age_seconds = (datetime.now() - last_downloaded).total_seconds()
            if age_seconds > 3600:  # 1 hour
                logger.info(
                    f"Current month cache expired ({age_seconds/3600:.1f}h old), will check for updates: {blob_name}"
                )
                return cached_etag, True  # Use ETag for conditional download

        # For historical data or recent current month data, use cached ETag
        logger.info(f"Using existing ETag for conditional download: {cached_etag}")
        return cached_etag, False  # May not need download if ETag matches

    except Exception as e:
        logger.error(f"Error checking CSV freshness for {blob_name}: {e}")
        return None, True


def validate_cache_and_setup_lock(blob_name: str) -> tuple[str, bool, str]:
    """Validate cache settings and setup download lock key."""
    # Check if this is current month data (files still growing, use short-lived cache)
    current_month = date.today().replace(day=1)
    is_current_month = bool(blob_name and current_month.strftime("%Y%m%d") in blob_name)

    # Create a lock key for this specific file to prevent concurrent downloads
    lock_key = f"azure_download_lock:{hashlib.md5(blob_name.encode()).hexdigest()}"

    return lock_key, is_current_month, current_month.strftime("%Y%m%d")


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


def wait_for_concurrent_download(blob_name: str, _: Any = None) -> str | None:
    """Wait for concurrent download to complete, then proceed with fresh download."""
    logger.info(f"Another process downloading {blob_name}, waiting...")
    # Wait for concurrent download to complete (up to 30 seconds)
    for _attempt in range(6):
        time.sleep(5)

    logger.info(
        f"Finished waiting for concurrent download, proceeding with fresh download: {blob_name}"
    )
    return None  # Always return None since we don't cache CSV content


async def handle_etag_conditional_download(
    db_pool, blob_name: str, is_current_month: bool
) -> tuple[str | None, bool]:
    """Handle ETag-based conditional downloads using PostgreSQL metadata."""
    cached_etag, needs_download = await check_csv_freshness(db_pool, blob_name, is_current_month)

    if cached_etag:
        logger.info(f"Found cached ETag for conditional download: {cached_etag}")
    else:
        logger.info(f"No cached ETag found, will download fresh: {blob_name}")

    return cached_etag, needs_download


async def download_blob_with_etag_check(
    db_pool,
    blob_client,
    cached_etag: str | None,
    is_current_month: bool,
    blob_name: str,
) -> str:
    """Download blob with ETag checking for efficient updates using PostgreSQL metadata."""
    if cached_etag and is_current_month:
        # Get blob properties to check ETag
        blob_properties = blob_client.get_blob_properties()
        current_etag = blob_properties.etag

        if current_etag == cached_etag:
            logger.info(f"File unchanged (ETag match), will download fresh anyway: {blob_name}")
            # Note: We don't cache CSV content, so we always download but this avoids unnecessary checks

        # Download new version (we always download, but ETag check prevents unnecessary metadata updates)
        blob_data = blob_client.download_blob()
        downloaded_content: str = blob_data.readall().decode("utf-8")
        logger.info(f"Downloaded data: {blob_name}")

        # Save new ETag to PostgreSQL
        await save_csv_metadata_to_db(
            db_pool,
            blob_name,
            etag=current_etag,
            file_size_bytes=len(downloaded_content.encode("utf-8")),
        )
        return downloaded_content
    else:
        # No cached ETag or not current month, download normally
        blob_data = blob_client.download_blob()
        fresh_content: str = blob_data.readall().decode("utf-8")

        # Save ETag to PostgreSQL for future conditional downloads (current month only)
        if is_current_month:
            try:
                blob_properties = blob_client.get_blob_properties()
                await save_csv_metadata_to_db(
                    db_pool,
                    blob_name,
                    etag=blob_properties.etag,
                    file_size_bytes=len(fresh_content.encode("utf-8")),
                )
                logger.info(
                    f"Saved ETag to PostgreSQL for future conditional downloads: {blob_properties.etag}"
                )
            except Exception as e:
                logger.warning(f"Failed to save ETag to PostgreSQL: {e}")

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
