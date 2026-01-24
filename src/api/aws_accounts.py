"""
AWS Account management utilities for database-driven account name resolution.

This module provides functions for managing AWS account ID to name mappings
in the database, replacing the pickle-based caching approach.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import asyncpg

logger = logging.getLogger(__name__)


async def get_aws_account_names(db_pool: asyncpg.Pool, account_ids: list[str]) -> dict[str, str]:
    """
    Get AWS account names from database for given account IDs.

    Args:
        db_pool: Database connection pool
        account_ids: List of AWS account IDs to lookup

    Returns:
        Dictionary mapping account_id -> account_name
    """
    if not account_ids:
        return {}

    async with db_pool.acquire() as conn:
        query = """
            SELECT account_id, account_name
            FROM aws_accounts
            WHERE account_id = ANY($1)
        """
        rows = await conn.fetch(query, account_ids)

        # Return mapping, fallback to account_id for missing entries
        result = {aid: aid for aid in account_ids}  # Default fallback
        for row in rows:
            result[row["account_id"]] = row["account_name"]

        return result


async def store_aws_account_names(
    db_pool: asyncpg.Pool,
    account_mapping: dict[str, str],
    management_account_id: str | None = None,
) -> int:
    """
    Store AWS account ID to name mappings in database.

    Args:
        db_pool: Database connection pool
        account_mapping: Dictionary of account_id -> account_name
        management_account_id: Optional ID of the management account

    Returns:
        Number of accounts stored/updated
    """
    if not account_mapping:
        return 0

    async with db_pool.acquire() as conn:
        # Prepare data for bulk upsert
        records = []
        for account_id, account_name in account_mapping.items():
            is_management = (
                (account_id == management_account_id) if management_account_id else False
            )
            records.append((account_id, account_name, is_management))

        # Use ON CONFLICT to update existing records
        query = """
            INSERT INTO aws_accounts (account_id, account_name, is_management_account)
            VALUES ($1, $2, $3)
            ON CONFLICT (account_id)
            DO UPDATE SET
                account_name = EXCLUDED.account_name,
                is_management_account = EXCLUDED.is_management_account,
                last_updated = CURRENT_TIMESTAMP
        """

        # Execute bulk insert/update
        await conn.executemany(query, records)

        logger.info(f"🔵 AWS: Stored {len(records)} account name mappings in database")
        return len(records)


async def get_uncached_account_ids(
    db_pool: asyncpg.Pool, account_ids: set[str], max_age_hours: int = 24
) -> set[str]:
    """
    Get list of account IDs that are not cached or are stale.

    Args:
        db_pool: Database connection pool
        account_ids: Set of account IDs to check
        max_age_hours: Maximum age in hours before considering cache stale

    Returns:
        Set of account IDs that need resolution
    """
    if not account_ids:
        return set()

    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

    async with db_pool.acquire() as conn:
        query = """
            SELECT account_id
            FROM aws_accounts
            WHERE account_id = ANY($1)
            AND last_updated > $2
        """
        rows = await conn.fetch(query, list(account_ids), cutoff_time)
        cached_ids = {row["account_id"] for row in rows}

        # Return the difference - IDs that are not cached or stale
        uncached_ids = account_ids - cached_ids

        if uncached_ids:
            logger.info(
                f"🔵 AWS: Found {len(uncached_ids)} uncached/stale account IDs (out of {len(account_ids)} total)"
            )

        return uncached_ids


async def resolve_aws_accounts_background(
    db_pool: asyncpg.Pool, auth_manager, account_ids: set[str]
) -> bool:
    """
    Background task to resolve AWS account names using Organizations API.

    Args:
        db_pool: Database connection pool
        auth_manager: Authentication manager instance
        account_ids: Set of account IDs to resolve

    Returns:
        True if successful, False if failed
    """
    if not account_ids:
        return True

    try:
        # Handle test environment where auth_manager.config might be None
        if not hasattr(auth_manager, "config") or auth_manager.config is None:
            logger.info(
                "🔵 AWS: No auth_manager config available, skipping background account resolution"
            )
            return False

        # Get AWS provider for account resolution
        aws_config = auth_manager.config.get("clouds", {}).get("aws", {})
        if not aws_config.get("enabled", False):
            logger.info("🔵 AWS: AWS provider not enabled, skipping background account resolution")
            return False

        from ..providers.aws import AWSCostProvider

        # Initialize AWS provider
        aws_provider = AWSCostProvider(aws_config)
        authenticated = await aws_provider.authenticate()

        if not authenticated:
            logger.warning("🔵 AWS: Authentication failed for background account resolution")
            return False

        # Resolve account names
        logger.info(f"🔵 AWS: Starting background resolution of {len(account_ids)} account names")

        account_mapping = {}
        management_account_id = None

        # Get management account ID if we have Organizations access
        if aws_provider.organizations_client:
            try:  # type: ignore[unreachable]
                org_response = aws_provider.organizations_client.describe_organization()
                management_account_id = org_response["Organization"]["MasterAccountId"]
            except Exception as e:
                logger.debug(f"🔵 AWS: Could not get management account ID: {e}")

        # Resolve each account with rate limiting
        for i, account_id in enumerate(account_ids):
            try:
                account_name = await aws_provider._resolve_account_name_from_organizations(
                    account_id
                )
                account_mapping[account_id] = account_name

                # Rate limiting: 100ms between requests
                if i < len(account_ids) - 1:
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.warning(f"🔵 AWS: Failed to resolve account {account_id}: {e}")
                # Store account ID as name for failed resolutions
                account_mapping[account_id] = account_id

        # Store resolved names in database
        stored_count = await store_aws_account_names(
            db_pool, account_mapping, management_account_id
        )

        logger.info(
            f"🔵 AWS: Background account resolution completed. Stored {stored_count} account names"
        )
        return True

    except Exception as e:
        logger.error(f"🔵 AWS: Background account resolution failed: {e}")
        return False


async def cleanup_old_aws_accounts(db_pool: asyncpg.Pool, max_age_days: int = 90) -> int:
    """
    Clean up old AWS account records that haven't been used recently.

    Args:
        db_pool: Database connection pool
        max_age_days: Maximum age in days before removal

    Returns:
        Number of records removed
    """
    cutoff_time = datetime.now() - timedelta(days=max_age_days)

    async with db_pool.acquire() as conn:
        # Delete old records
        result = await conn.execute("DELETE FROM aws_accounts WHERE last_updated < $1", cutoff_time)

        # Parse result to get affected rows
        affected_rows = int(result.split()[-1]) if result.startswith("DELETE") else 0

        if affected_rows > 0:
            logger.info(
                f"🔵 AWS: Cleaned up {affected_rows} old account records (older than {max_age_days} days)"
            )

        return affected_rows
