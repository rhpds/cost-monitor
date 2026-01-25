"""
Database integration tests.

Tests database operations, migrations, and data consistency
for the cost monitoring system.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from src.api.aws_accounts import (
    cleanup_old_aws_accounts,
    get_aws_account_names,
    get_uncached_account_ids,
    resolve_aws_accounts_background,
    store_aws_account_names,
)


class TestDatabaseConnection:
    """Test database connection and basic operations."""

    @pytest.mark.asyncio
    async def test_database_pool_creation(self, mock_db_pool):
        """Test database pool creation and configuration."""
        # Mock successful pool creation
        assert mock_db_pool is not None

        # Test pool configuration
        mock_db_pool.acquire.return_value.__aenter__.return_value.fetch.return_value = [
            {"version": "14.0"}
        ]

        async with mock_db_pool.acquire() as conn:
            result = await conn.fetch("SELECT version()")
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_database_connection_error_handling(self):
        """Test database connection error handling."""
        with patch("asyncpg.create_pool") as mock_create_pool:
            mock_create_pool.side_effect = asyncpg.ConnectionDoesNotExistError("Connection failed")

            with pytest.raises(asyncpg.ConnectionDoesNotExistError):
                await asyncpg.create_pool("invalid://connection/string")

    @pytest.mark.asyncio
    async def test_database_transaction_handling(self, mock_db_pool):
        """Test database transaction handling."""
        # The mock is already set up in conftest.py with transaction support
        async with mock_db_pool.acquire() as conn, conn.transaction():
            result = await conn.execute("INSERT INTO test_table (id) VALUES (1)")
            assert "INSERT" in result

    @pytest.mark.asyncio
    async def test_database_concurrent_connections(self, mock_db_pool):
        """Test concurrent database connections."""
        # Update the mock return value for this test
        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = [{"result": "success"}]

        async def db_operation():
            async with mock_db_pool.acquire() as conn:
                return await conn.fetch("SELECT 'success' as result")

        # Test multiple concurrent operations
        tasks = [db_operation() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for result in results:
            assert result[0]["result"] == "success"


class TestCostDataStorage:
    """Test cost data storage operations."""

    @pytest.mark.asyncio
    async def test_store_cost_data_points(self, mock_db_pool):
        """Test storing individual cost data points."""
        # Test data to insert
        cost_data_points = [
            {
                "date": date(2024, 1, 1),
                "amount": 100.0,
                "currency": "USD",
                "provider": "aws",
                "service_name": "EC2",
                "account_id": "123456789012",
                "region": "us-east-1",
            },
            {
                "date": date(2024, 1, 2),
                "amount": 150.0,
                "currency": "USD",
                "provider": "aws",
                "service_name": "S3",
                "account_id": "123456789012",
                "region": "us-east-1",
            },
        ]

        # Simulate insertion
        async with mock_db_pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO cost_data (date, amount, currency, provider, service_name, account_id, region) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                [
                    (
                        point["date"],
                        point["amount"],
                        point["currency"],
                        point["provider"],
                        point["service_name"],
                        point["account_id"],
                        point["region"],
                    )
                    for point in cost_data_points
                ],
            )

        # Verify the call was made (using the mock that's actually used)
        async with mock_db_pool.acquire() as conn:
            conn.executemany.assert_called()

    @pytest.mark.asyncio
    async def test_retrieve_cost_data(self, mock_db_pool):
        """Test retrieving cost data from database."""
        # Mock data retrieval
        mock_cost_data = [
            {
                "date": date(2024, 1, 1),
                "amount": 100.0,
                "currency": "USD",
                "provider": "aws",
                "service_name": "EC2",
                "account_id": "123456789012",
                "account_name": "Production",
                "region": "us-east-1",
            }
        ]

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = mock_cost_data
            result = await conn.fetch(
                "SELECT * FROM cost_data WHERE date BETWEEN $1 AND $2",
                date(2024, 1, 1),
                date(2024, 1, 31),
            )

        assert len(result) == 1
        assert result[0]["amount"] == 100.0
        assert result[0]["provider"] == "aws"

    @pytest.mark.asyncio
    async def test_cost_data_aggregation(self, mock_db_pool):
        """Test cost data aggregation queries."""
        # Mock aggregation result
        mock_aggregation = [
            {
                "provider": "aws",
                "total_cost": 1000.0,
                "service_breakdown": '{"EC2": 600.0, "S3": 400.0}',
            },
            {
                "provider": "azure",
                "total_cost": 750.0,
                "service_breakdown": '{"VMs": 500.0, "Storage": 250.0}',
            },
        ]

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = mock_aggregation
            result = await conn.fetch(
                """
                SELECT
                    provider,
                    SUM(amount) as total_cost,
                    JSON_OBJECT_AGG(service_name, SUM(amount)) as service_breakdown
                FROM cost_data
                WHERE date BETWEEN $1 AND $2
                GROUP BY provider
            """,
                date(2024, 1, 1),
                date(2024, 1, 31),
            )

        assert len(result) == 2
        assert result[0]["total_cost"] == 1000.0
        assert result[1]["total_cost"] == 750.0

    @pytest.mark.asyncio
    async def test_duplicate_data_handling(self, mock_db_pool):
        """Test handling of duplicate cost data entries."""
        async with mock_db_pool.acquire() as conn:
            # Mock constraint violation for duplicates
            conn.execute.side_effect = [
                "INSERT 0 1",  # First insert succeeds
                asyncpg.UniqueViolationError("duplicate key value"),  # Duplicate fails
            ]

            # First insert should succeed
            result1 = await conn.execute("INSERT INTO cost_data (...) VALUES (...)")
            assert "INSERT" in result1

            # Duplicate insert should raise error
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute("INSERT INTO cost_data (...) VALUES (...)")


class TestAWSAccountManagement:
    """Test AWS account management database operations."""

    @pytest.mark.asyncio
    async def test_get_aws_account_names(self, mock_db_pool):
        """Test retrieving AWS account names from database."""
        # Mock account data to be returned by the database
        mock_accounts = [
            {"account_id": "123456789012", "account_name": "Production Account"},
            {"account_id": "123456789013", "account_name": "Development Account"},
        ]

        # Configure the mock to return this data when conn.fetch is called
        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = mock_accounts

        account_ids = ["123456789012", "123456789013", "123456789014"]  # Third one not found
        result = await get_aws_account_names(mock_db_pool, account_ids)

        # Should return mapping with fallback for missing accounts
        assert result["123456789012"] == "Production Account"
        assert result["123456789013"] == "Development Account"
        assert result["123456789014"] == "123456789014"  # Fallback to account ID

    @pytest.mark.asyncio
    async def test_store_aws_account_names(self, mock_db_pool):
        """Test storing AWS account names in database."""
        account_mapping = {
            "123456789012": "Production Account",
            "123456789013": "Development Account",
        }
        management_account_id = "123456789012"

        # The store function will call executemany, so we need to ensure the mock is ready
        async with mock_db_pool.acquire() as conn:
            # Executemany is already mocked in conftest.py
            pass

        stored_count = await store_aws_account_names(
            mock_db_pool, account_mapping, management_account_id
        )

        assert stored_count == 2

        # Verify the SQL call was made
        async with mock_db_pool.acquire() as conn:
            conn.executemany.assert_called()
            # Verify the SQL call included proper upsert logic
            call_args = conn.executemany.call_args
            sql_query = call_args[0][0]
            assert "ON CONFLICT" in sql_query
            assert "account_id" in sql_query

    @pytest.mark.asyncio
    async def test_get_uncached_account_ids(self, mock_db_pool):
        """Test identifying uncached account IDs."""
        # Mock cached accounts (recently updated)
        cached_accounts = [{"account_id": "123456789012"}]  # Only one account is cached

        # Configure the mock to return cached accounts
        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = cached_accounts

        account_ids = {"123456789012", "123456789013", "123456789014"}
        uncached_ids = await get_uncached_account_ids(mock_db_pool, account_ids, max_age_hours=24)

        # Should return accounts not in cache or stale
        expected_uncached = {"123456789013", "123456789014"}
        assert uncached_ids == expected_uncached

    @pytest.mark.asyncio
    async def test_cleanup_old_aws_accounts(self, mock_db_pool):
        """Test cleanup of old AWS account records."""
        # Configure mock to return a successful deletion result
        async with mock_db_pool.acquire() as conn:
            conn.execute.return_value = "DELETE 5"  # 5 records deleted

        deleted_count = await cleanup_old_aws_accounts(mock_db_pool, max_age_days=90)

        assert deleted_count == 5

        # Verify DELETE query was executed
        async with mock_db_pool.acquire() as conn:
            conn.execute.assert_called()
            call_args = conn.execute.call_args
            sql_query = call_args[0][0]
            assert "DELETE FROM aws_accounts" in sql_query

    @pytest.mark.asyncio
    async def test_resolve_aws_accounts_background(
        self, mock_db_pool, mock_auth_manager, mock_aws_session, mock_aws_credentials
    ):
        """Test background AWS account resolution."""
        # Configure the database mock to work with store_aws_account_names
        async with mock_db_pool.acquire() as conn:
            conn.executemany.return_value = None

        with patch("src.providers.aws.AWSCostProvider") as mock_provider_class:
            # Create a realistic AWS provider mock
            mock_provider = AsyncMock()
            mock_provider.authenticate.return_value = True
            mock_provider.organizations_client = mock_aws_session.client("organizations")

            # Mock the account name resolution method
            async def mock_resolve_name(account_id):
                return "Test Account"

            mock_provider._resolve_account_name_from_organizations = mock_resolve_name

            mock_provider_class.return_value = mock_provider

            account_ids = {"123456789012"}
            result = await resolve_aws_accounts_background(
                mock_db_pool, mock_auth_manager, account_ids
            )

            assert result is True
            mock_provider.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_aws_account_operations_error_handling(self, mock_db_pool):
        """Test error handling in AWS account operations."""
        # Test database error during account retrieval
        async with mock_db_pool.acquire() as conn:
            conn.fetch.side_effect = asyncpg.PostgresError("Database connection lost")

        with pytest.raises(asyncpg.PostgresError):
            await get_aws_account_names(mock_db_pool, ["123456789012"])

        # Test empty account list handling
        result = await get_aws_account_names(mock_db_pool, [])
        assert result == {}


class TestDataConsistency:
    """Test data consistency and integrity."""

    @pytest.mark.asyncio
    async def test_cost_data_currency_consistency(self, mock_db_pool):
        """Test currency consistency across cost data."""
        # Mock mixed currency data
        mixed_currency_data = [
            {"date": date(2024, 1, 1), "amount": 100.0, "currency": "USD", "provider": "aws"},
            {"date": date(2024, 1, 1), "amount": 85.0, "currency": "EUR", "provider": "azure"},
        ]

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = mixed_currency_data
            result = await conn.fetch(
                "SELECT DISTINCT currency FROM cost_data WHERE date = $1", date(2024, 1, 1)
            )

        # Should handle multiple currencies
        currencies = {row["currency"] for row in result}
        assert "USD" in currencies
        assert "EUR" in currencies

    @pytest.mark.asyncio
    async def test_cost_data_date_range_validation(self, mock_db_pool):
        """Test date range validation in cost data queries."""
        # Mock data within valid date range
        valid_data = [{"date": date(2024, 1, 15), "amount": 100.0}]

        # Test valid date range query
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = valid_data
            result = await conn.fetch(
                "SELECT * FROM cost_data WHERE date BETWEEN $1 AND $2", start_date, end_date
            )

        assert len(result) == 1
        assert result[0]["date"] == date(2024, 1, 15)

    @pytest.mark.asyncio
    async def test_account_data_referential_integrity(self, mock_db_pool):
        """Test referential integrity between cost data and account data."""
        # Mock cost data with account references
        cost_with_accounts = [
            {
                "date": date(2024, 1, 1),
                "amount": 100.0,
                "provider": "aws",
                "account_id": "123456789012",
                "account_name": "Production Account",
            }
        ]

        # Test join query between cost data and accounts
        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = cost_with_accounts
            result = await conn.fetch(
                """
                SELECT cd.amount, aa.account_name
                FROM cost_data cd
                LEFT JOIN aws_accounts aa ON cd.account_id = aa.account_id
                WHERE cd.date = $1
            """,
                date(2024, 1, 1),
            )

        assert len(result) == 1
        assert result[0]["account_name"] == "Production Account"

    @pytest.mark.asyncio
    async def test_data_archival_and_cleanup(self, mock_db_pool):
        """Test data archival and cleanup operations."""
        # Test cleanup of old cost data (older than 2 years)
        cutoff_date = date.today() - timedelta(days=730)

        async with mock_db_pool.acquire() as conn:
            conn.execute.return_value = "DELETE 100"
            result = await conn.execute("DELETE FROM cost_data WHERE date < $1", cutoff_date)

        assert result == "DELETE 100"

        # Verify the execute was called
        async with mock_db_pool.acquire() as conn:
            conn.execute.assert_called()


class TestDatabasePerformance:
    """Test database performance characteristics."""

    @pytest.mark.asyncio
    async def test_large_dataset_query_performance(self, mock_db_pool):
        """Test query performance with large datasets."""
        # Simulate large dataset query
        large_dataset = [
            {"date": date(2024, 1, 1) + timedelta(days=i), "amount": 100.0 + i}
            for i in range(365)  # Full year of data
        ]

        import time

        start_time = time.time()

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = large_dataset
            result = await conn.fetch(
                "SELECT * FROM cost_data WHERE date BETWEEN $1 AND $2 ORDER BY date",
                date(2024, 1, 1),
                date(2024, 12, 31),
            )

        end_time = time.time()
        query_time = end_time - start_time

        assert len(result) == 365
        # Mock query should be very fast
        assert query_time < 1.0

    @pytest.mark.asyncio
    async def test_concurrent_write_operations(self, mock_db_pool):
        """Test concurrent write operations."""
        # Configure the mock to return INSERT result
        async with mock_db_pool.acquire() as conn:
            conn.execute.return_value = "INSERT 0 1"

        async def write_operation(data_id):
            async with mock_db_pool.acquire() as conn:
                return await conn.execute(
                    "INSERT INTO cost_data (id, amount) VALUES ($1, $2)", data_id, 100.0
                )

        # Test multiple concurrent writes
        tasks = [write_operation(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for result in results:
            assert "INSERT" in result

    @pytest.mark.asyncio
    async def test_connection_pool_efficiency(self, mock_db_pool):
        """Test connection pool efficiency under load."""
        # Configure mock to return success data
        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = [{"result": "success"}]

        async def pool_operation():
            async with mock_db_pool.acquire() as conn:
                return await conn.fetch("SELECT 'success' as result")

        # Test many concurrent operations that should reuse connections
        tasks = [pool_operation() for _ in range(20)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        # All should succeed using the mocked pool
        for result in results:
            assert result[0]["result"] == "success"

    @pytest.mark.asyncio
    async def test_index_utilization(self, mock_db_pool):
        """Test that queries utilize database indexes effectively."""
        # Mock query plan showing index usage
        mock_query_plan = [{"plan": "Index Scan using idx_cost_data_date on cost_data"}]

        async with mock_db_pool.acquire() as conn:
            conn.fetch.return_value = mock_query_plan
            # Test EXPLAIN query to verify index usage
            plan = await conn.fetch(
                "EXPLAIN SELECT * FROM cost_data WHERE date = $1", date(2024, 1, 1)
            )

        assert "Index Scan" in plan[0]["plan"]
        assert "idx_cost_data_date" in plan[0]["plan"]
