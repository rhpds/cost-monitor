"""
Integration tests for FastAPI endpoints.

Tests the complete API functionality including database interactions,
authentication, and response validation.
"""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.data_service import app


@pytest.fixture
async def mock_app_dependencies():
    """Mock FastAPI app dependencies to prevent real database connections during startup."""
    from contextlib import asynccontextmanager

    with patch("src.api.data_service.asyncpg.create_pool") as mock_create_pool, patch(
        "src.api.data_service.redis.from_url"
    ) as mock_redis_from_url, patch(
        "src.api.data_service.MultiCloudAuthManager"
    ) as mock_auth_class, patch(
        "src.api.data_service.get_config"
    ) as mock_get_config:
        # Create proper async context manager for database pool
        mock_conn = AsyncMock()

        # Mock realistic cost data for the API endpoints
        mock_cost_data = [
            {
                "date": date(2024, 1, 1),
                "cost": 100.0,
                "currency": "USD",
                "provider": "aws",
                "service_name": "EC2",
                "account_id": "123456789012",
                "region": "us-east-1",
            },
            {
                "date": date(2024, 1, 1),
                "cost": 50.0,
                "currency": "USD",
                "provider": "azure",
                "service_name": "Virtual Machines",
                "account_id": "azure-sub-1",
                "region": "eastus",
            },
        ]

        # Mock provider data for the providers endpoint
        mock_provider_data = [
            {
                "name": "aws",
                "display_name": "Amazon Web Services",
                "is_enabled": True,
                "last_sync_at": datetime(2024, 1, 1, 10, 0, 0),
                "sync_status": "completed",
            },
            {
                "name": "azure",
                "display_name": "Microsoft Azure",
                "is_enabled": True,
                "last_sync_at": datetime(2024, 1, 1, 10, 0, 0),
                "sync_status": "completed",
            },
            {
                "name": "gcp",
                "display_name": "Google Cloud Platform",
                "is_enabled": True,
                "last_sync_at": datetime(2024, 1, 1, 10, 0, 0),
                "sync_status": "completed",
            },
        ]

        # Create a smart mock that returns different data based on the query
        async def smart_fetch(*args, **kwargs):
            query = args[0] if args else ""
            if "FROM providers" in query:
                return mock_provider_data
            else:
                return mock_cost_data

        mock_conn.fetch.side_effect = smart_fetch
        mock_conn.fetchval.return_value = 5  # Simple integer for COUNT(*) queries
        mock_conn.execute.return_value = "EXECUTE 1"

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = AsyncMock()
        mock_pool.acquire = mock_acquire
        mock_pool.fetch = smart_fetch  # For direct pool.fetch() calls
        mock_pool.fetchval = mock_conn.fetchval  # For direct pool.fetchval() calls
        mock_create_pool.return_value = mock_pool

        # Mock Redis client creation
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {"used_memory_human": "1.5M", "redis_version": "6.2.0"}
        mock_redis_from_url.return_value = mock_redis

        # Mock auth manager
        mock_auth = AsyncMock()
        mock_auth_class.return_value = mock_auth

        # Mock config
        mock_get_config.return_value = {"clouds": {"aws": {"enabled": True}}}

        yield {"db_pool": mock_pool, "redis_client": mock_redis, "auth_manager": mock_auth}


class TestHealthEndpoints:
    """Test health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_live(self, mock_app_dependencies):
        """Test liveness probe endpoint."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/health/live")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "alive"
            assert data["version"] == "1.0.0"
            assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_ready_with_mocked_deps(self, mock_app_dependencies):
        """Test readiness probe with mocked dependencies."""
        # The fixture already provides properly configured mocks
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/health/ready")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ready"

    @pytest.mark.asyncio
    async def test_health_ready_db_failure(self, mock_app_dependencies):
        """Test readiness probe with database failure."""
        mock_redis = mock_app_dependencies["redis_client"]

        with patch("src.api.data_service.db_pool", None), patch(
            "src.api.data_service.redis_client", mock_redis
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/health/ready")

                assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_health_db_endpoint(self, mock_app_dependencies):
        """Test database health endpoint."""
        mock_db_pool = mock_app_dependencies["db_pool"]

        with patch("src.api.data_service.db_pool", mock_db_pool):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/health/db")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert "providers_count" in data
                assert data["providers_count"] == 5

    @pytest.mark.asyncio
    async def test_health_redis_endpoint(self, mock_app_dependencies):
        """Test Redis health endpoint."""
        mock_redis = mock_app_dependencies["redis_client"]

        with patch("src.api.data_service.redis_client", mock_redis):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/health/redis")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert "memory_used" in data


class TestCostEndpoints:
    """Test cost-related endpoints."""

    @pytest.mark.asyncio
    async def test_cost_summary_endpoint(self, mock_app_dependencies):
        """Test cost summary endpoint with mocked dependencies."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        # Mock the service functions to return simple test data
        mock_summary = {
            "total_cost": 150.0,
            "currency": "USD",
            "period_start": "2024-01-01",
            "period_end": "2024-01-31",
            "provider_breakdown": {"aws": 100.0, "azure": 50.0},
            "combined_daily_costs": [],
            "provider_data": {},
            "account_breakdown": {},
            "data_collection_complete": True,
            "last_updated": "2024-01-31T10:00:00Z",
        }

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare, patch(
            "src.api.services.cost_service.ensure_data_collection"
        ) as mock_ensure, patch(
            "src.api.services.cost_service.query_cost_data"
        ) as mock_query, patch(
            "src.api.services.cost_service.process_account_data"
        ) as mock_process, patch(
            "src.api.services.cost_service.build_response"
        ) as mock_build:
            # Mock the service function chain
            mock_prepare.return_value = (date(2024, 1, 1), date(2024, 1, 31), "cache_key", None)
            mock_ensure.return_value = True
            mock_query.return_value = {
                "total_rows": [],
                "daily_rows": [],
                "service_rows": [],
                "account_rows": [],
            }
            mock_process.return_value = []
            mock_build.return_value = mock_summary

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs/summary")

                assert response.status_code == 200
                data = response.json()
                assert "total_cost" in data
                assert "currency" in data
                assert "provider_breakdown" in data
                assert "combined_daily_costs" in data

    @pytest.mark.asyncio
    async def test_cost_summary_with_date_range(self, mock_app_dependencies):
        """Test cost summary with specific date range."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)

        # Mock the service functions to return test data
        mock_summary = {
            "total_cost": 150.0,
            "currency": "USD",
            "period_start": str(start_date),
            "period_end": str(end_date),
            "provider_breakdown": {"aws": 150.0},
            "combined_daily_costs": [],
            "provider_data": {},
            "account_breakdown": {},
            "data_collection_complete": True,
            "last_updated": "2024-01-31T10:00:00Z",
        }

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare, patch(
            "src.api.services.cost_service.ensure_data_collection"
        ) as mock_ensure, patch(
            "src.api.services.cost_service.query_cost_data"
        ) as mock_query, patch(
            "src.api.services.cost_service.process_account_data"
        ) as mock_process, patch(
            "src.api.services.cost_service.build_response"
        ) as mock_build:
            # Mock the service function chain
            mock_prepare.return_value = (start_date, end_date, "cache_key", None)
            mock_ensure.return_value = True
            mock_query.return_value = {
                "total_rows": [],
                "daily_rows": [],
                "service_rows": [],
                "account_rows": [],
            }
            mock_process.return_value = []
            mock_build.return_value = mock_summary

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/api/v1/costs/summary?start_date={start_date}&end_date={end_date}"
                )

                assert response.status_code == 200
                data = response.json()
                assert data["period_start"] == str(start_date)
                assert data["period_end"] == str(end_date)

    @pytest.mark.asyncio
    async def test_cost_summary_cached_response(self, mock_app_dependencies):
        """Test cost summary with cached response."""
        cached_data = {
            "total_cost": 1000.0,
            "currency": "USD",
            "period_start": "2024-01-01",
            "period_end": "2024-01-31",
            "provider_breakdown": {"aws": 600.0, "azure": 400.0},
            "combined_daily_costs": [],
            "provider_data": {},
            "account_breakdown": {},
            "data_collection_complete": True,
            "last_updated": "2024-01-31T10:00:00Z",
        }

        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare:
            # Mock that cache returns our test data directly

            mock_prepare.return_value = (
                date(2024, 1, 1),
                date(2024, 1, 31),
                "cache_key",
                cached_data,
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs/summary")

                assert response.status_code == 200
                data = response.json()
                assert data["total_cost"] == 1000.0

    @pytest.mark.asyncio
    async def test_costs_endpoint(self, mock_app_dependencies):
        """Test general costs endpoint."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            mock_auth_manager.get_enabled_providers.return_value = ["aws"]

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs")

                assert response.status_code == 200
                data = response.json()
                assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_costs_endpoint_with_filters(self, mock_app_dependencies):
        """Test costs endpoint with provider and date filters."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            mock_auth_manager.get_enabled_providers.return_value = ["aws"]

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/costs?provider=aws&start_date=2024-01-01&end_date=2024-01-31"
                )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_costs_endpoint_database_error(self, mock_app_dependencies):
        """Test costs endpoint with database error."""
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", None), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs")

                assert response.status_code == 500


class TestProviderEndpoints:
    """Test provider-related endpoints."""

    @pytest.mark.asyncio
    async def test_providers_endpoint(self, mock_app_dependencies):
        """Test providers endpoint."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            mock_auth_manager.get_enabled_providers.return_value = ["aws", "azure", "gcp"]
            mock_auth_manager.config = {
                "clouds": {
                    "aws": {"enabled": True, "name": "Amazon Web Services"},
                    "azure": {"enabled": True, "name": "Microsoft Azure"},
                    "gcp": {"enabled": True, "name": "Google Cloud Platform"},
                }
            }

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/providers")

                assert response.status_code == 200
                data = response.json()
                assert isinstance(data, list)
                assert len(data) == 3
                assert data[0]["name"] == "aws"
                assert data[0]["display_name"] == "Amazon Web Services"

    @pytest.mark.asyncio
    async def test_providers_endpoint_database_error(self, mock_app_dependencies):
        """Test providers endpoint when database is not available."""
        mock_redis = mock_app_dependencies["redis_client"]

        with patch("src.api.data_service.db_pool", None), patch(
            "src.api.data_service.redis_client", mock_redis
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/providers")

                assert response.status_code == 500


class TestRootEndpoint:
    """Test root endpoint."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, mock_app_dependencies):
        """Test root endpoint."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/")

            assert response.status_code == 200
            data = response.json()
            assert "service" in data or "message" in data
            assert "version" in data
            assert "endpoints" in data or "docs_url" in data


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_date_format(self, mock_db_pool, mock_redis, mock_auth_manager):
        """Test invalid date format handling."""
        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs/summary?start_date=invalid-date")

                assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_date_range_validation(self, mock_app_dependencies):
        """Test date range validation (end before start)."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare:
            start_date = date(2024, 1, 31)
            end_date = date(2024, 1, 1)  # Before start date

            # Mock that the validation raises an exception or returns an error
            mock_prepare.side_effect = ValueError("End date must be after start date")

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/api/v1/costs/summary?start_date={start_date}&end_date={end_date}"
                )

                assert response.status_code == 500  # Server error due to validation

    @pytest.mark.asyncio
    async def test_missing_dependencies_error(self):
        """Test behavior when dependencies are not initialized."""
        with patch("src.api.data_service.db_pool", None), patch(
            "src.api.data_service.redis_client", None
        ), patch("src.api.data_service.auth_manager", None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs/summary")

                assert response.status_code == 500


class TestConcurrentRequests:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_cost_summary_requests(self, mock_app_dependencies):
        """Test handling multiple concurrent cost summary requests."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare, patch(
            "src.api.services.cost_service.ensure_data_collection"
        ) as mock_ensure, patch(
            "src.api.services.cost_service.build_response"
        ) as mock_build:
            # Mock service chain for concurrent requests
            mock_prepare.return_value = (date(2024, 1, 1), date(2024, 1, 31), "cache_key", None)
            mock_ensure.return_value = True
            mock_build.return_value = {
                "total_cost": 100.0,
                "currency": "USD",
                "period_start": "2024-01-01",
                "period_end": "2024-01-31",
                "provider_breakdown": {"aws": 100.0},
                "combined_daily_costs": [],
                "provider_data": {},
                "account_breakdown": {},
                "data_collection_complete": True,
                "last_updated": "2024-01-31T10:00:00Z",
            }

            async def make_request():
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/v1/costs/summary")

            # Make 3 concurrent requests
            tasks = [make_request() for _ in range(3)]
            responses = await asyncio.gather(*tasks)

            # All requests should succeed
            for response in responses:
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, mock_app_dependencies):
        """Test concurrent health check requests."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ):

            async def make_health_request():
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/health/ready")

            # Make 5 concurrent health checks
            tasks = [make_health_request() for _ in range(5)]
            responses = await asyncio.gather(*tasks)

            # All health checks should succeed
            for response in responses:
                assert response.status_code == 200


class TestDataIntegrity:
    """Test data integrity and validation."""

    @pytest.mark.asyncio
    async def test_cost_summary_response_structure(self, mock_app_dependencies):
        """Test that cost summary response has correct structure."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        mock_summary = {
            "total_cost": 150.0,
            "currency": "USD",
            "period_start": "2024-01-01",
            "period_end": "2024-01-31",
            "provider_breakdown": {"aws": 150.0},
            "combined_daily_costs": [],
            "provider_data": {},
            "account_breakdown": {},
            "data_collection_complete": True,
            "last_updated": "2024-01-31T10:00:00Z",
        }

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager), patch(
            "src.api.services.cost_service.prepare_date_range_and_cache"
        ) as mock_prepare, patch(
            "src.api.services.cost_service.ensure_data_collection"
        ) as mock_ensure, patch(
            "src.api.services.cost_service.build_response"
        ) as mock_build:
            mock_prepare.return_value = (date(2024, 1, 1), date(2024, 1, 31), "cache_key", None)
            mock_ensure.return_value = True
            mock_build.return_value = mock_summary

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs/summary")

                assert response.status_code == 200
                data = response.json()

                # Validate response structure matches CostSummary model
                required_fields = [
                    "total_cost",
                    "currency",
                    "period_start",
                    "period_end",
                    "provider_breakdown",
                    "combined_daily_costs",
                    "provider_data",
                    "account_breakdown",
                    "data_collection_complete",
                    "last_updated",
                ]

                for field in required_fields:
                    assert field in data, f"Missing field: {field}"

                # Validate data types
                assert isinstance(data["total_cost"], int | float)
                assert isinstance(data["currency"], str)
                assert isinstance(data["provider_breakdown"], dict)
                assert isinstance(data["combined_daily_costs"], list)

    @pytest.mark.asyncio
    async def test_costs_response_structure(self, mock_app_dependencies):
        """Test that costs endpoint response has correct structure."""
        mock_db_pool = mock_app_dependencies["db_pool"]
        mock_redis = mock_app_dependencies["redis_client"]
        mock_auth_manager = mock_app_dependencies["auth_manager"]

        with patch("src.api.data_service.db_pool", mock_db_pool), patch(
            "src.api.data_service.redis_client", mock_redis
        ), patch("src.api.data_service.auth_manager", mock_auth_manager):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/costs")

                assert response.status_code == 200
                data = response.json()

                assert isinstance(data, list)
                if data:  # If there's data, validate structure
                    cost_item = data[0]
                    required_fields = [
                        "date",
                        "cost",
                        "currency",
                        "provider",
                    ]  # Note: "cost" not "amount"
                    for field in required_fields:
                        assert field in cost_item
