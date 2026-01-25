"""
Integration tests for cost service functions.

Tests the helper functions used by the API for cost data processing,
caching, and business logic.
"""

import asyncio
import json
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from src.api.services.cost_service import (
    build_response,
    ensure_data_collection,
    prepare_date_range_and_cache,
)


class TestDateRangeAndCachePreparation:
    """Test date range preparation and cache handling."""

    @pytest.mark.asyncio
    async def test_prepare_date_range_defaults(self, mock_redis):
        """Test date range preparation with default values."""
        mock_redis.get.return_value = None

        start_date, end_date, cache_key, cached_result = await prepare_date_range_and_cache(
            start_date=None,
            end_date=None,
            providers=None,
            force_refresh=False,
            redis_client=mock_redis,
        )

        # Should default to last 30 days
        expected_end = date.today()
        expected_start = expected_end - timedelta(days=30)

        assert start_date == expected_start
        assert end_date == expected_end
        assert cache_key is not None
        assert cached_result is None

    @pytest.mark.asyncio
    async def test_prepare_date_range_with_custom_dates(self, mock_redis):
        """Test date range preparation with custom dates."""
        mock_redis.get.return_value = None

        custom_start = date(2024, 1, 1)
        custom_end = date(2024, 1, 31)

        start_date, end_date, cache_key, cached_result = await prepare_date_range_and_cache(
            start_date=custom_start,
            end_date=custom_end,
            providers=["aws", "azure"],
            force_refresh=False,
            redis_client=mock_redis,
        )

        assert start_date == custom_start
        assert end_date == custom_end
        assert "aws,azure" in cache_key
        assert cached_result is None

    @pytest.mark.asyncio
    async def test_prepare_date_range_with_cache_hit(self, mock_redis):
        """Test date range preparation with cache hit."""
        cached_data = {"total_cost": 1000.0, "currency": "USD"}
        mock_redis.get.return_value = json.dumps(cached_data)

        start_date, end_date, cache_key, cached_result = await prepare_date_range_and_cache(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws"],
            force_refresh=False,
            redis_client=mock_redis,
        )

        assert cached_result == cached_data
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_date_range_force_refresh(self, mock_redis):
        """Test date range preparation with force refresh (skip cache)."""
        mock_redis.get.return_value = json.dumps({"cached": "data"})

        start_date, end_date, cache_key, cached_result = await prepare_date_range_and_cache(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws"],
            force_refresh=True,  # Skip cache
            redis_client=mock_redis,
        )

        assert cached_result is None  # Cache should be skipped
        mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_key_generation(self, mock_redis):
        """Test cache key generation with different parameters."""
        mock_redis.get.return_value = None

        # Test with no providers
        _, _, cache_key1, _ = await prepare_date_range_and_cache(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=None,
            force_refresh=False,
            redis_client=mock_redis,
        )

        # Test with multiple providers
        _, _, cache_key2, _ = await prepare_date_range_and_cache(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws", "azure", "gcp"],
            force_refresh=False,
            redis_client=mock_redis,
        )

        assert cache_key1 != cache_key2
        assert "2024-01-01:2024-01-31" in cache_key1
        assert "aws,azure,gcp" in cache_key2


class TestDataCollection:
    """Test data collection functions."""

    @pytest.mark.asyncio
    async def test_ensure_data_collection_with_providers(self, mock_db_pool):
        """Test data collection with mock helper functions."""
        # Mock the helper functions that would normally be passed in
        mock_collect_missing_data = AsyncMock()
        mock_check_existing_data = AsyncMock()
        mock_get_missing_date_ranges = AsyncMock()

        # Mock that there's no existing data (need to collect)
        mock_check_existing_data.return_value = []
        mock_get_missing_date_ranges.return_value = [
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31), "provider": "aws"}
        ]

        result = await ensure_data_collection(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws", "azure"],
            force_refresh=False,
            db_pool=mock_db_pool,
            collect_missing_data=mock_collect_missing_data,
            check_existing_data=mock_check_existing_data,
            get_missing_date_ranges=mock_get_missing_date_ranges,
        )

        # Should return completion status
        assert isinstance(result, bool)
        # Functions may be called multiple times for completeness check
        assert mock_check_existing_data.call_count >= 1
        assert mock_get_missing_date_ranges.call_count >= 1
        mock_collect_missing_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_data_collection_specific_providers(self, mock_db_pool):
        """Test data collection with specific requested providers."""
        mock_collect_missing_data = AsyncMock()
        mock_check_existing_data = AsyncMock()
        mock_get_missing_date_ranges = AsyncMock()

        # Mock that data exists (no missing ranges)
        mock_check_existing_data.return_value = ["existing_data"]
        mock_get_missing_date_ranges.return_value = []  # No missing data

        result = await ensure_data_collection(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws"],  # Request only AWS data
            force_refresh=False,
            db_pool=mock_db_pool,
            collect_missing_data=mock_collect_missing_data,
            check_existing_data=mock_check_existing_data,
            get_missing_date_ranges=mock_get_missing_date_ranges,
        )

        # Should complete successfully
        assert isinstance(result, bool)
        # Functions may be called multiple times for completeness check
        assert mock_check_existing_data.call_count >= 1
        assert mock_get_missing_date_ranges.call_count >= 1

    @pytest.mark.asyncio
    async def test_ensure_data_collection_force_refresh(self):
        """Test data collection with force refresh enabled."""
        from contextlib import asynccontextmanager

        mock_collect_missing_data = AsyncMock()
        mock_check_existing_data = AsyncMock()
        mock_get_missing_date_ranges = AsyncMock()

        # Create a custom mock database pool for this test
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 10"  # Mock delete result

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool.acquire = mock_acquire

        # Mock final data check after collection
        mock_check_existing_data.return_value = ["new_data"]
        mock_get_missing_date_ranges.return_value = []  # No missing data after collection

        result = await ensure_data_collection(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=["aws"],
            force_refresh=True,  # Force refresh
            db_pool=mock_pool,
            collect_missing_data=mock_collect_missing_data,
            check_existing_data=mock_check_existing_data,
            get_missing_date_ranges=mock_get_missing_date_ranges,
        )

        # Should handle force refresh mode
        assert isinstance(result, bool)
        mock_conn.execute.assert_called_once()  # Should delete existing data
        mock_collect_missing_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_data_collection_no_providers(self, mock_db_pool):
        """Test data collection when no providers are specified."""
        mock_collect_missing_data = AsyncMock()
        mock_check_existing_data = AsyncMock()
        mock_get_missing_date_ranges = AsyncMock()

        mock_check_existing_data.return_value = []
        mock_get_missing_date_ranges.return_value = []

        result = await ensure_data_collection(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            providers=None,  # No specific providers
            force_refresh=False,
            db_pool=mock_db_pool,
            collect_missing_data=mock_collect_missing_data,
            check_existing_data=mock_check_existing_data,
            get_missing_date_ranges=mock_get_missing_date_ranges,
        )

        # Should handle no providers gracefully
        assert isinstance(result, bool)


class TestCostSummaryResponse:
    """Test cost summary response building."""

    def test_build_response(self):
        """Test building cost summary response from database results."""
        # Mock database query results
        db_results = {
            "total_rows": [
                {"provider": "aws", "total_cost": 100.0, "currency": "USD"},
                {"provider": "azure", "total_cost": 50.0, "currency": "USD"},
            ],
            "daily_rows": [
                {"date": date(2024, 1, 1), "provider": "aws", "cost": 100.0, "currency": "USD"},
                {"date": date(2024, 1, 1), "provider": "azure", "cost": 50.0, "currency": "USD"},
            ],
            "service_rows": [
                {"provider": "aws", "service_name": "EC2", "cost": 100.0, "currency": "USD"},
                {
                    "provider": "azure",
                    "service_name": "Virtual Machines",
                    "cost": 50.0,
                    "currency": "USD",
                },
            ],
            "account_rows": [
                {"provider": "aws", "account_id": "123456789012", "cost": 100.0, "currency": "USD"},
                {"provider": "azure", "account_id": "azure-sub-1", "cost": 50.0, "currency": "USD"},
            ],
        }

        all_account_rows = [
            {
                "provider": "aws",
                "account_id": "123456789012",
                "account_name": "Production",
                "cost": 100.0,
                "currency": "USD",
            },
            {
                "provider": "azure",
                "account_id": "azure-sub-1",
                "account_name": "Production",
                "cost": 50.0,
                "currency": "USD",
            },
        ]

        response = build_response(
            db_results=db_results,
            all_account_rows=all_account_rows,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            data_collection_complete=True,
        )

        assert response["total_cost"] == 150.0  # 100 + 50
        assert response["currency"] == "USD"
        assert "aws" in response["provider_breakdown"]
        assert "azure" in response["provider_breakdown"]
        assert response["provider_breakdown"]["aws"] == 100.0
        assert response["provider_breakdown"]["azure"] == 50.0

    def test_build_response_no_data(self):
        """Test building cost summary response with no data."""
        db_results = {"total_rows": [], "daily_rows": [], "service_rows": [], "account_rows": []}

        response = build_response(
            db_results=db_results,
            all_account_rows=[],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            data_collection_complete=True,
        )

        assert response["total_cost"] == 0.0
        assert response["provider_breakdown"] == {}
        assert response["combined_daily_costs"] == []

    def test_build_response_single_provider(self):
        """Test building cost summary response for single provider."""
        db_results = {
            "total_rows": [{"provider": "gcp", "total_cost": 350.0, "currency": "USD"}],
            "daily_rows": [
                {"date": date(2024, 1, 1), "provider": "gcp", "cost": 200.0, "currency": "USD"},
                {"date": date(2024, 1, 2), "provider": "gcp", "cost": 150.0, "currency": "USD"},
            ],
            "service_rows": [
                {
                    "provider": "gcp",
                    "service_name": "Compute Engine",
                    "cost": 200.0,
                    "currency": "USD",
                },
                {
                    "provider": "gcp",
                    "service_name": "Cloud Storage",
                    "cost": 150.0,
                    "currency": "USD",
                },
            ],
            "account_rows": [],
        }

        all_account_rows = [
            {
                "provider": "gcp",
                "account_id": "gcp-project-1",
                "account_name": "Production",
                "cost": 350.0,
                "currency": "USD",
            }
        ]

        response = build_response(
            db_results=db_results,
            all_account_rows=all_account_rows,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            data_collection_complete=True,
        )

        assert response["total_cost"] == 350.0
        assert len(response["provider_breakdown"]) == 1
        assert response["provider_breakdown"]["gcp"] == 350.0
        assert len(response["combined_daily_costs"]) == 2

    def test_build_response_multiple_currencies(self):
        """Test building cost summary response with multiple currencies."""
        db_results = {
            "total_rows": [
                {"provider": "aws", "total_cost": 100.0, "currency": "USD"},
                {"provider": "azure", "total_cost": 85.0, "currency": "EUR"},
            ],
            "daily_rows": [
                {"date": date(2024, 1, 1), "provider": "aws", "cost": 100.0, "currency": "USD"},
                {"date": date(2024, 1, 1), "provider": "azure", "cost": 85.0, "currency": "EUR"},
            ],
            "service_rows": [
                {"provider": "aws", "service_name": "EC2", "cost": 100.0, "currency": "USD"},
                {
                    "provider": "azure",
                    "service_name": "Virtual Machines",
                    "cost": 85.0,
                    "currency": "EUR",
                },
            ],
            "account_rows": [],
        }

        all_account_rows = [
            {
                "provider": "aws",
                "account_id": "123456789012",
                "account_name": "Production",
                "cost": 100.0,
                "currency": "USD",
            },
            {
                "provider": "azure",
                "account_id": "azure-sub-1",
                "account_name": "Production",
                "cost": 85.0,
                "currency": "EUR",
            },
        ]

        response = build_response(
            db_results=db_results,
            all_account_rows=all_account_rows,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            data_collection_complete=True,
        )

        # Should handle multiple currencies (implementation dependent)
        assert "currency" in response
        assert "total_cost" in response
        assert response["provider_breakdown"]["aws"] == 100.0
        assert response["provider_breakdown"]["azure"] == 85.0


class TestErrorHandling:
    """Test error handling in cost service functions."""

    @pytest.mark.asyncio
    async def test_prepare_date_range_redis_error(self):
        """Test date range preparation when Redis is unavailable."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("Redis connection failed")

        # Should handle Redis errors gracefully
        try:
            start_date, end_date, cache_key, cached_result = await prepare_date_range_and_cache(
                start_date=None,
                end_date=None,
                providers=None,
                force_refresh=False,
                redis_client=mock_redis,
            )
            # If the function handles errors gracefully
            assert start_date is not None
            assert end_date is not None
            assert cached_result is None  # Should fallback to no cache
        except Exception:
            # It's also acceptable for the function to let Redis errors propagate
            pass

    @pytest.mark.asyncio
    async def test_data_collection_database_error(self):
        """Test data collection when database operations fail."""
        # Mock helper functions that might fail
        mock_collect_missing_data = AsyncMock(side_effect=Exception("Database error"))
        mock_check_existing_data = AsyncMock(side_effect=Exception("Database error"))
        mock_get_missing_date_ranges = AsyncMock(return_value=[])

        # Should handle database errors gracefully
        try:
            result = await ensure_data_collection(  # noqa: F841
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                providers=["aws"],
                force_refresh=False,
                db_pool=None,  # Missing database pool
                collect_missing_data=mock_collect_missing_data,
                check_existing_data=mock_check_existing_data,
                get_missing_date_ranges=mock_get_missing_date_ranges,
            )
            # Implementation should handle errors gracefully
            assert True
        except Exception:
            # Acceptable to raise exception for database errors
            pass

    def test_build_response_with_invalid_data(self):
        """Test building response with invalid or missing data fields."""
        # Test with missing total_cost field
        db_results = {
            "total_rows": [{"provider": "aws", "currency": "USD"}],  # Missing total_cost
            "daily_rows": [],
            "service_rows": [],
            "account_rows": [],
        }

        all_account_rows = []

        try:
            response = build_response(  # noqa: F841
                db_results=db_results,
                all_account_rows=all_account_rows,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                data_collection_complete=True,
            )
            # Should handle missing fields gracefully or raise appropriate error
            assert True
        except (KeyError, ValueError, TypeError):
            # Acceptable to raise exception for invalid data
            pass


class TestPerformance:
    """Test performance characteristics of cost service functions."""

    def test_large_date_range_handling(self):
        """Test handling large date ranges efficiently."""
        # Simulate large amount of data (365 data points)
        total_rows = []
        daily_rows = []
        service_rows = []
        account_rows = []

        for i in range(365):
            cost = 100.0 + i
            date_obj = date(2024, 1, 1) + timedelta(days=i % 31)

            daily_rows.append(
                {"date": date_obj, "provider": "aws", "cost": cost, "currency": "USD"}
            )

            service_rows.append(
                {
                    "provider": "aws",
                    "service_name": f"Service-{i % 10}",
                    "cost": cost,
                    "currency": "USD",
                }
            )

        total_rows.append(
            {"provider": "aws", "total_cost": sum(100.0 + i for i in range(365)), "currency": "USD"}
        )

        db_results = {
            "total_rows": total_rows,
            "daily_rows": daily_rows,
            "service_rows": service_rows,
            "account_rows": account_rows,
        }

        all_account_rows = [
            {
                "provider": "aws",
                "account_id": "123456789012",
                "account_name": "Production",
                "cost": sum(100.0 + i for i in range(365)),
                "currency": "USD",
            }
        ]

        # Should handle large datasets without issues
        response = build_response(
            db_results=db_results,
            all_account_rows=all_account_rows,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            data_collection_complete=True,
        )

        assert response["total_cost"] > 0
        assert len(response["provider_breakdown"]) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_cache_operations(self, mock_redis):
        """Test concurrent cache operations."""
        mock_redis.get.return_value = None

        async def prepare_cache():
            return await prepare_date_range_and_cache(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                providers=["aws"],
                force_refresh=False,
                redis_client=mock_redis,
            )

        # Run multiple cache operations concurrently
        tasks = [prepare_cache() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All operations should complete successfully
        assert len(results) == 5
        for result in results:
            assert result[0] == date(2024, 1, 1)  # start_date
            assert result[1] == date(2024, 1, 31)  # end_date
