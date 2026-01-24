"""
Pytest configuration and shared fixtures for cost-monitor tests.

This module provides common fixtures and configurations used across
all test modules in the cost monitoring system.
"""

import asyncio
import os
import tempfile
from collections.abc import Generator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.monitoring.alerts import Alert, AlertLevel, AlertRule, AlertType

# Test data imports
from src.providers.base import CostDataPoint, CostSummary, TimeGranularity


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "aws: mark test as AWS-specific")
    config.addinivalue_line("markers", "azure: mark test as Azure-specific")
    config.addinivalue_line("markers", "gcp: mark test as GCP-specific")
    config.addinivalue_line("markers", "slow: mark test as slow running")


# Async event loop fixture
@pytest_asyncio.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Temporary directory fixture
@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# Environment fixture
@pytest.fixture
def clean_env() -> Generator[dict[str, str], None, None]:
    """Provide a clean environment for testing."""
    original_env = os.environ.copy()
    # Clear environment variables that might affect tests
    env_vars_to_clear = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GCP_PROJECT_ID",
    ]

    for var in env_vars_to_clear:
        os.environ.pop(var, None)

    yield os.environ

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# Database fixtures
@pytest.fixture
def mock_db_pool():
    """Mock database connection pool for testing."""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()

    # Set up connection methods
    mock_conn.fetch.return_value = []
    mock_conn.fetchrow.return_value = None
    mock_conn.execute.return_value = "INSERT 0 1"
    mock_conn.executemany.return_value = None

    # Set up transaction mock
    class MockTransaction:
        def __init__(self, connection):
            self.conn = connection

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    # Make transaction() return the context manager directly (not a coroutine)
    def mock_transaction():
        return MockTransaction(mock_conn)

    mock_conn.transaction = mock_transaction

    class MockConnectionContextManager:
        def __init__(self, connection):
            self.conn = connection

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    # Create a callable that returns async context manager
    def mock_acquire():
        return MockConnectionContextManager(mock_conn)

    # Set up acquire method
    mock_pool.acquire = mock_acquire

    # Also support the old style access pattern for compatibility
    mock_pool.acquire.return_value = MockConnectionContextManager(mock_conn)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    return mock_pool


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    mock_client = AsyncMock()
    mock_client.get.return_value = None
    mock_client.set.return_value = True
    mock_client.delete.return_value = True
    mock_client.ping.return_value = True
    mock_client.info.return_value = {"redis_version": "6.2.0"}
    return mock_client


# Configuration fixtures
@pytest.fixture
def test_config() -> dict[str, Any]:
    """Provide test configuration."""
    return {
        "clouds": {
            "aws": {
                "enabled": True,
                "access_key_id": "test_access_key",  # pragma: allowlist secret
                "secret_access_key": "test_secret_key",  # pragma: allowlist secret
                "region": "us-east-1",
            },
            "azure": {
                "enabled": True,
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",  # pragma: allowlist secret
                "tenant_id": "test_tenant_id",
            },
            "gcp": {
                "enabled": True,
                "project_id": "test-project",
                "credentials_path": "/path/to/test/creds.json",
            },
        },
        "database": {"url": "postgresql://test:test@localhost:5432/test_db"},  # nosec
        "redis": {"url": "redis://localhost:6379/1"},
        "dashboard": {"host": "localhost", "port": 8050, "debug": True},
        "alerts": {
            "enabled": True,
            "threshold_rules": [
                {"name": "Daily Threshold", "type": "daily_threshold", "threshold_value": 100.0}
            ],
        },
    }


# Sample data fixtures
@pytest.fixture
def sample_cost_data_point() -> CostDataPoint:
    """Provide a sample CostDataPoint for testing."""
    return CostDataPoint(
        date=date(2024, 1, 15),
        amount=125.50,
        currency="USD",
        service_name="Amazon EC2",
        account_id="123456789012",
        account_name="Production Account",
        region="us-east-1",
        resource_id="i-1234567890abcdef0",
        tags={"Environment": "Production", "Team": "Backend"},
    )


@pytest.fixture
def sample_cost_summary(sample_cost_data_point) -> CostSummary:
    """Provide a sample CostSummary for testing."""
    return CostSummary(
        provider="aws",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        total_cost=3875.25,
        currency="USD",
        data_points=[sample_cost_data_point],
        granularity=TimeGranularity.DAILY,
        last_updated=datetime.now(),
    )


@pytest.fixture
def sample_alert_rule() -> AlertRule:
    """Provide a sample AlertRule for testing."""
    return AlertRule(
        name="Daily Cost Warning",
        alert_type=AlertType.DAILY_THRESHOLD,
        provider="aws",
        threshold_value=500.0,
        time_window=1,
        enabled=True,
        alert_level=AlertLevel.WARNING,
        description="Alert when daily AWS costs exceed $500",
    )


@pytest.fixture
def sample_alert(sample_alert_rule) -> Alert:
    """Provide a sample Alert for testing."""
    return Alert(
        id="alert-test-12345",
        rule_name=sample_alert_rule.name,
        alert_type=AlertType.DAILY_THRESHOLD,
        alert_level=AlertLevel.WARNING,
        provider="aws",
        current_value=650.0,
        threshold_value=500.0,
        currency="USD",
        message="Daily AWS cost of $650.00 exceeds threshold of $500.00",
        timestamp=datetime.now(),
        metadata={"service_breakdown": {"EC2": 400.0, "S3": 250.0}},
        acknowledged=False,
        resolved=False,
    )


# Configuration mocking classes for realistic config behavior
class MockConfigSection:
    """Mock config section that supports dict-like access."""

    def __init__(self, data: dict):
        self.data = data
        for key, value in data.items():
            setattr(self, key, value)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __contains__(self, key):
        return key in self.data


class MockCloudConfig:
    """Mock CloudConfig that behaves like the real one."""

    def __init__(self):
        self.aws = MockConfigSection(
            {
                "enabled": True,
                "region": "us-east-1",
                "access_key_id": "test_key",  # pragma: allowlist secret
                "secret_access_key": "test_secret",  # pragma: allowlist secret
            }
        )
        self.azure = MockConfigSection(
            {
                "enabled": True,
                "subscription_id": "test-sub",
                "client_id": "test_client",
                "client_secret": "test_secret",  # pragma: allowlist secret
                "tenant_id": "test_tenant",
            }
        )
        self.gcp = MockConfigSection(
            {
                "enabled": True,
                "project_id": "test-project",
                "credentials_path": "/tmp/test-creds.json",
            }
        )
        self.monitoring = MockConfigSection({"thresholds": {"warning": 100, "critical": 200}})
        self.dashboard = MockConfigSection({"host": "localhost", "port": 8050, "debug": True})
        self.cache = MockConfigSection({"ttl": 300})
        self.database = MockConfigSection({"url": "postgresql://test:test@localhost:5432/test_db"})
        self.redis = MockConfigSection({"url": "redis://localhost:6379/1"})
        self.alerts = MockConfigSection({"enabled": True, "threshold_rules": []})

    @property
    def enabled_providers(self):
        return ["aws", "azure", "gcp"]

    def get_provider_config(self, provider: str):
        return getattr(self, provider, {})

    def is_provider_enabled(self, provider: str):
        return provider in self.enabled_providers


@pytest.fixture
def mock_cloud_config():
    """Provide a realistic mock configuration."""
    return MockCloudConfig()


@pytest.fixture(autouse=True)
def patch_config_globally(mock_cloud_config):
    """Auto-patch get_config function globally for all tests."""
    with patch("src.config.settings.get_config", return_value=mock_cloud_config):
        yield


# Mock cloud provider responses
@pytest.fixture
def aws_cost_response() -> dict[str, Any]:
    """Mock AWS Cost Explorer API response."""
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                "Total": {"BlendedCost": {"Amount": "125.50", "Unit": "USD"}},
                "Groups": [
                    {
                        "Keys": ["Amazon Elastic Compute Cloud - Compute"],
                        "Metrics": {"BlendedCost": {"Amount": "75.30", "Unit": "USD"}},
                    }
                ],
            }
        ]
    }


@pytest.fixture
def azure_cost_response() -> dict[str, Any]:
    """Mock Azure billing API response."""
    return {
        "value": [
            {
                "id": "subscriptions/12345/providers/Microsoft.Billing/billingPeriods/202401/providers/Microsoft.Consumption/usageDetails/usage1",
                "name": "usage1",
                "type": "Microsoft.Consumption/usageDetails",
                "properties": {
                    "subscriptionGuid": "12345-67890-abcdef",
                    "usageStart": "2024-01-01T00:00:00Z",
                    "usageEnd": "2024-01-01T23:59:59Z",
                    "pretaxCost": 98.75,
                    "currency": "USD",
                    "meterDetails": {"meterCategory": "Virtual Machines"},
                },
            }
        ]
    }


@pytest.fixture
def gcp_cost_response() -> list[dict[str, Any]]:
    """Mock GCP BigQuery billing response."""
    return [
        {
            "service_description": "Compute Engine",
            "usage_start_time": "2024-01-01 00:00:00 UTC",
            "usage_end_time": "2024-01-01 23:59:59 UTC",
            "cost": 85.25,
            "currency": "USD",
            "project_id": "test-project-12345",
            "location_region": "us-central1",
        }
    ]


# Provider mock fixtures
@pytest.fixture
def mock_aws_provider():
    """Mock AWS provider for testing."""
    with patch("src.providers.aws.AWSCostProvider") as mock:
        provider = mock.return_value
        provider.authenticate.return_value = True
        provider.test_connection.return_value = True
        provider.get_costs.return_value = CostSummary(
            provider="aws",
            start_date=date.today() - timedelta(days=7),
            end_date=date.today(),
            total_cost=500.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )
        yield provider


@pytest.fixture
def mock_azure_provider():
    """Mock Azure provider for testing."""
    with patch("src.providers.azure.AzureCostProvider") as mock:
        provider = mock.return_value
        provider.authenticate.return_value = True
        provider.test_connection.return_value = True
        provider.get_costs.return_value = CostSummary(
            provider="azure",
            start_date=date.today() - timedelta(days=7),
            end_date=date.today(),
            total_cost=350.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )
        yield provider


@pytest.fixture
def mock_gcp_provider():
    """Mock GCP provider for testing."""
    with patch("src.providers.gcp.GCPCostProvider") as mock:
        provider = mock.return_value
        provider.authenticate.return_value = True
        provider.test_connection.return_value = True
        provider.get_costs.return_value = CostSummary(
            provider="gcp",
            start_date=date.today() - timedelta(days=7),
            end_date=date.today(),
            total_cost=275.0,
            currency="USD",
            data_points=[],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now(),
        )
        yield provider


# Performance testing fixtures
@pytest.fixture
def performance_timer():
    """Fixture for measuring test performance."""
    times = {}

    def timer(name: str):
        import time

        start_time = time.perf_counter()

        def stop():
            end_time = time.perf_counter()
            times[name] = end_time - start_time
            return times[name]

        return stop

    timer.times = times
    return timer


# Authentication fixtures
@pytest.fixture
def mock_auth_manager():
    """Mock authentication manager for testing."""
    mock_manager = MagicMock()
    mock_manager.authenticate_aws.return_value = True
    mock_manager.authenticate_azure.return_value = True
    mock_manager.authenticate_gcp.return_value = True
    mock_manager.get_aws_session.return_value = MagicMock()
    mock_manager.get_azure_credential.return_value = MagicMock()
    mock_manager.get_gcp_credentials.return_value = MagicMock()

    # Add proper config structure for AWS testing
    mock_manager.config = {
        "clouds": {
            "aws": {
                "enabled": True,
                "region": "us-east-1",
                "access_key_id": "test_access_key",  # pragma: allowlist secret
                "secret_access_key": "test_secret_key",  # pragma: allowlist secret
            }
        }
    }

    return mock_manager


# AWS-specific mocking fixtures
@pytest.fixture
def mock_aws_credentials():
    """Mock AWS credentials for testing."""
    import os

    original_env = os.environ.copy()

    # Set mock AWS credentials to prevent hitting real AWS
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"  # pragma: allowlist secret
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"  # pragma: allowlist secret
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_aws_cost_explorer_client():
    """Mock AWS Cost Explorer client with realistic responses."""
    mock_client = MagicMock()

    # Mock get_cost_and_usage response with proper structure
    mock_client.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                "Total": {"BlendedCost": {"Amount": "125.50", "Unit": "USD"}},
                "Groups": [
                    {
                        "Keys": ["Amazon Elastic Compute Cloud - Compute"],
                        "Metrics": {"BlendedCost": {"Amount": "75.30", "Unit": "USD"}},
                    }
                ],
            }
        ]
    }

    return mock_client


@pytest.fixture
def mock_aws_organizations_client():
    """Mock AWS Organizations client with realistic responses."""
    mock_client = MagicMock()

    # Mock describe_organization response
    mock_client.describe_organization.return_value = {
        "Organization": {
            "Id": "o-1234567890",
            "Arn": "arn:aws:organizations::123456789012:organization/o-1234567890",
            "FeatureSet": "ALL",
            "MasterAccountArn": "arn:aws:organizations::123456789012:account/o-1234567890/123456789012",
            "MasterAccountId": "123456789012",
            "MasterAccountEmail": "test@example.com",
        }
    }

    # Mock describe_account response
    mock_client.describe_account.return_value = {
        "Account": {
            "Id": "123456789012",
            "Arn": "arn:aws:organizations::123456789012:account/o-1234567890/123456789012",
            "Email": "test@example.com",
            "Name": "Test Account",
            "Status": "ACTIVE",
            "JoinedMethod": "INVITED",
            "JoinedTimestamp": "2020-01-01T00:00:00Z",
        }
    }

    return mock_client


@pytest.fixture
def mock_aws_session(mock_aws_cost_explorer_client, mock_aws_organizations_client):
    """Mock boto3 session that returns proper AWS service clients."""
    mock_session = MagicMock()

    # Configure client method to return appropriate mocks based on service
    def mock_client(service_name, **kwargs):
        if service_name == "ce":  # Cost Explorer
            return mock_aws_cost_explorer_client
        elif service_name == "organizations":
            return mock_aws_organizations_client
        else:
            return MagicMock()

    mock_session.client = mock_client
    return mock_session


# Date range fixtures
@pytest.fixture
def date_ranges() -> dict[str, tuple[date, date]]:
    """Provide common date ranges for testing."""
    today = date.today()
    return {
        "last_7_days": (today - timedelta(days=7), today),
        "last_30_days": (today - timedelta(days=30), today),
        "this_month": (today.replace(day=1), today),
        "last_month": (
            (today.replace(day=1) - timedelta(days=1)).replace(day=1),
            today.replace(day=1) - timedelta(days=1),
        ),
        "this_year": (today.replace(month=1, day=1), today),
    }
