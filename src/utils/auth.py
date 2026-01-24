"""
Multi-cloud authentication utilities for AWS, Azure, and GCP.

Provides a unified interface for handling authentication across different cloud providers
with support for various authentication methods and credential management.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# AWS imports
try:
    import boto3

    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False

# Azure imports
try:
    from azure.identity import (
        AzureCliCredential,
        ClientSecretCredential,
        DefaultAzureCredential,
        EnvironmentCredential,
        ManagedIdentityCredential,
    )

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

# GCP imports
try:
    from google.auth import default as gcp_default
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import billing_v1
    from google.oauth2 import service_account

    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

logger = logging.getLogger(__name__)


class AuthenticationResult(BaseModel):
    """Result of an authentication attempt with validation."""

    success: bool = Field(..., description="Whether authentication was successful")
    provider: str = Field(..., min_length=1, max_length=50, description="Cloud provider name")
    method: str = Field(..., min_length=1, max_length=100, description="Authentication method used")
    error_message: str | None = Field(
        None, max_length=1000, description="Error message if authentication failed"
    )
    credentials: Any | None = Field(None, description="Authenticated credentials object")

    @classmethod
    def create_success(cls, provider: str, method: str, credentials: Any) -> "AuthenticationResult":
        """Create a successful authentication result."""
        return cls(
            success=True,
            provider=provider,
            method=method,
            credentials=credentials,
            error_message=None,
        )

    @classmethod
    def create_failure(
        cls, provider: str, method: str, error_message: str
    ) -> "AuthenticationResult":
        """Create a failed authentication result."""
        return cls(
            success=False,
            provider=provider,
            method=method,
            error_message=error_message,
            credentials=None,
        )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate and normalize provider name."""
        normalized = v.lower().strip()
        valid_providers = {"aws", "azure", "gcp"}

        if normalized not in valid_providers:
            # Allow other providers but warn
            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown provider in authentication result: {v}")
            return v.strip()

        return normalized

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Validate and normalize authentication method."""
        if not v or not v.strip():
            raise ValueError("Authentication method cannot be empty")

        # Common authentication methods
        normalized = v.lower().strip().replace("-", "_").replace(" ", "_")

        known_methods = {
            "access_key",
            "instance_profile",
            "session_token",
            "profile",
            "service_principal",
            "managed_identity",
            "device_code",
            "service_account",
            "gcloud_auth",
            "api_key",
            "oauth2",
        }

        if normalized not in known_methods:
            # Allow custom methods but warn
            logger = logging.getLogger(__name__)
            logger.info(f"Custom authentication method: {v}")

        return normalized

    @field_validator("error_message")
    @classmethod
    def validate_error_message(cls, v: str | None) -> str | None:
        """Validate error message."""
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return v

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization (excluding credentials for security)."""
        result = self.model_dump(by_alias=True, exclude_unset=True)
        # Don't include credentials in serialized output for security
        result.pop("credentials", None)
        return result


class CloudAuthenticator(ABC):
    """Abstract base class for cloud authenticators."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.provider_name = self._get_provider_name()

    @abstractmethod
    def _get_provider_name(self) -> str:
        """Return the provider name."""
        pass

    @abstractmethod
    async def authenticate(self) -> AuthenticationResult:
        """Authenticate with the cloud provider."""
        pass

    @abstractmethod
    def test_credentials(self, credentials: Any) -> bool:
        """Test if the credentials are valid."""
        pass


class AWSAuthenticator(CloudAuthenticator):
    """AWS authentication handler."""

    def _get_provider_name(self) -> str:
        return "aws"

    async def authenticate(self) -> AuthenticationResult:
        """Authenticate with AWS using various methods."""
        if not AWS_AVAILABLE:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="none",
                error_message="AWS SDK (boto3) not available",
            )

        # If access keys are provided in config, use ONLY those (highest precedence)
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")

        if access_key and secret_key:
            logger.info("🔵 AWS: Using access keys from secrets config (highest precedence)")
            result = await self._authenticate_with_access_keys()
            if result.success:
                logger.info("🔵 AWS: Authentication successful using secrets access keys")
                return result
            else:
                logger.error(f"🔵 AWS: Secrets access keys failed: {result.error_message}")
                # If secrets file credentials fail, this is an error - don't fallback
                return result

        # No access keys in config - this is now an error since we're using only dynaconf
        logger.error("🔵 AWS: No access keys found in dynaconf configuration")
        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="none",
            error_message="No AWS credentials found in dynaconf configuration - environment variables and other fallbacks have been disabled",
        )

    async def _authenticate_with_access_keys(self) -> AuthenticationResult:
        """Authenticate using access keys from config."""
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")

        logger.debug(
            f"🔵 AWS: _authenticate_with_access_keys - access_key: {bool(access_key)}, secret_key: {bool(secret_key)}"
        )

        if not access_key or not secret_key:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="access_keys",
                error_message="Access key or secret key not provided in config",
            )

        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=self.config.get("session_token"),
                region_name=self.config.get("region"),
            )

            if self.test_credentials(session):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="access_keys",
                    credentials=session,
                )
        except Exception as e:
            logger.debug(f"AWS access key authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="access_keys",
            error_message="Invalid access keys",
        )

    def test_credentials(self, session: boto3.Session) -> bool:
        """Test AWS credentials by making a simple API call."""
        try:
            sts_client = session.client("sts")
            sts_client.get_caller_identity()
            return True
        except Exception as e:
            logger.debug(f"AWS credential test failed: {e}")
            return False


class AzureAuthenticator(CloudAuthenticator):
    """Azure authentication handler."""

    def _get_provider_name(self) -> str:
        return "azure"

    async def authenticate(self) -> AuthenticationResult:
        """Authenticate with Azure using various methods."""
        if not AZURE_AVAILABLE:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="none",
                error_message="Azure SDK not available",
            )

        # Try authentication methods in order of preference
        auth_methods = [
            self._authenticate_with_service_principal,
            self._authenticate_with_environment,
            self._authenticate_with_azure_cli,
            self._authenticate_with_managed_identity,
            self._authenticate_with_default_credential,
        ]

        for method in auth_methods:
            try:
                result = await method()
                if result.success:
                    logger.info(f"Azure authentication successful using {result.method}")
                    return result
            except Exception as e:
                logger.debug(f"Azure authentication method {method.__name__} failed: {e}")
                continue

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="none",
            error_message="All Azure authentication methods failed",
        )

    async def _authenticate_with_service_principal(self) -> AuthenticationResult:
        """Authenticate using service principal credentials from config file."""
        tenant_id = self.config.get("tenant_id")
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")

        if (
            not all([tenant_id, client_id, client_secret])
            or not isinstance(tenant_id, str)
            or not isinstance(client_id, str)
            or not isinstance(client_secret, str)
        ):
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="service_principal",
                error_message="Missing tenant_id, client_id, or client_secret",
            )

        try:
            credential = ClientSecretCredential(
                tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
            )

            if self.test_credentials(credential):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="service_principal",
                    credentials=credential,
                )
        except Exception as e:
            logger.debug(f"Azure service principal authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="service_principal",
            error_message="Invalid service principal credentials",
        )

    async def _authenticate_with_environment(self) -> AuthenticationResult:
        """Authenticate using environment credentials."""
        try:
            credential = EnvironmentCredential()

            if self.test_credentials(credential):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="environment",
                    credentials=credential,
                )
        except Exception as e:
            logger.debug(f"Azure environment authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="environment",
            error_message="Environment credentials not available",
        )

    async def _authenticate_with_azure_cli(self) -> AuthenticationResult:
        """Authenticate using Azure CLI credentials."""
        try:
            credential = AzureCliCredential()

            if self.test_credentials(credential):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="azure_cli",
                    credentials=credential,
                )
        except Exception as e:
            logger.debug(f"Azure CLI authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="azure_cli",
            error_message="Azure CLI not authenticated",
        )

    async def _authenticate_with_managed_identity(self) -> AuthenticationResult:
        """Authenticate using managed identity."""
        try:
            credential = ManagedIdentityCredential()

            if self.test_credentials(credential):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="managed_identity",
                    credentials=credential,
                )
        except Exception as e:
            logger.debug(f"Azure managed identity authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="managed_identity",
            error_message="Managed identity not available",
        )

    async def _authenticate_with_default_credential(self) -> AuthenticationResult:
        """Authenticate using default Azure credential chain."""
        try:
            credential = DefaultAzureCredential()

            if self.test_credentials(credential):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="default_credential",
                    credentials=credential,
                )
        except Exception as e:
            logger.debug(f"Azure default credential authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="default_credential",
            error_message="Default credential chain failed",
        )

    def test_credentials(self, credential) -> bool:
        """Test Azure credentials by attempting to get a token."""
        try:
            token = credential.get_token("https://management.azure.com/.default")
            return token is not None
        except Exception as e:
            logger.debug(f"Azure credential test failed: {e}")
            return False


class GCPAuthenticator(CloudAuthenticator):
    """GCP authentication handler."""

    def _get_provider_name(self) -> str:
        return "gcp"

    async def authenticate(self) -> AuthenticationResult:
        """Authenticate with GCP using various methods."""
        if not GCP_AVAILABLE:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="none",
                error_message="GCP SDK not available",
            )

        # Try authentication methods in order of preference
        auth_methods = [
            self._authenticate_with_service_account,
            self._authenticate_with_default_credentials,
            self._authenticate_with_environment,
        ]

        for method in auth_methods:
            try:
                result = await method()
                if result.success:
                    logger.info(f"GCP authentication successful using {result.method}")
                    return result
            except Exception as e:
                logger.debug(f"GCP authentication method {method.__name__} failed: {e}")
                continue

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="none",
            error_message="All GCP authentication methods failed",
        )

    async def _authenticate_with_service_account(self) -> AuthenticationResult:
        """Authenticate using service account JSON file from config."""
        credentials_path = self.config.get("credentials_path")

        if not credentials_path:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="service_account",
                error_message="No service account credentials path provided",
            )

        if not Path(credentials_path).exists():
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="service_account",
                error_message=f"Service account file not found: {credentials_path}",
            )

        try:
            credentials = service_account.Credentials.from_service_account_file(credentials_path)

            if self.test_credentials(credentials):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="service_account",
                    credentials=credentials,
                )
        except Exception as e:
            logger.debug(f"GCP service account authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="service_account",
            error_message="Invalid service account credentials",
        )

    async def _authenticate_with_default_credentials(self) -> AuthenticationResult:
        """Authenticate using default GCP credentials."""
        try:
            credentials, project = gcp_default()

            if self.test_credentials(credentials):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="default_credentials",
                    credentials=credentials,
                )
        except DefaultCredentialsError as e:
            logger.debug(f"GCP default credentials failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="default_credentials",
            error_message="Default credentials not available",
        )

    async def _authenticate_with_environment(self) -> AuthenticationResult:
        """Authenticate using environment variable JSON."""
        creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

        if not creds_json:
            return AuthenticationResult.create_failure(
                provider=self.provider_name,
                method="environment",
                error_message="No credentials JSON in environment",
            )

        try:
            creds_info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_info)

            if self.test_credentials(credentials):
                return AuthenticationResult.create_success(
                    provider=self.provider_name,
                    method="environment_json",
                    credentials=credentials,
                )
        except Exception as e:
            logger.debug(f"GCP environment JSON authentication failed: {e}")

        return AuthenticationResult.create_failure(
            provider=self.provider_name,
            method="environment",
            error_message="Invalid credentials JSON in environment",
        )

    def test_credentials(self, credentials) -> bool:
        """Test GCP credentials by creating a client."""
        try:
            client = billing_v1.CloudBillingClient(credentials=credentials)
            # Try to list billing accounts (requires minimal permissions)
            request = billing_v1.ListBillingAccountsRequest()
            client.list_billing_accounts(request=request)
            return True
        except Exception as e:
            logger.debug(f"GCP credential test failed: {e}")
            return False


class MultiCloudAuthManager:
    """Manager for multi-cloud authentication."""

    def __init__(self):
        self.authenticators = {
            "aws": AWSAuthenticator,
            "azure": AzureAuthenticator,
            "gcp": GCPAuthenticator,
        }
        self.authenticated_providers = {}

    async def authenticate_provider(
        self, provider: str, config: dict[str, Any]
    ) -> AuthenticationResult:
        """
        Authenticate a specific provider.

        Args:
            provider: Provider name (aws, azure, gcp)
            config: Provider configuration

        Returns:
            Authentication result
        """
        provider = provider.lower()

        if provider not in self.authenticators:
            return AuthenticationResult.create_failure(
                provider=provider,
                method="none",
                error_message=f"Unknown provider: {provider}",
            )

        authenticator = self.authenticators[provider](config)
        result: AuthenticationResult = await authenticator.authenticate()

        if result.success:
            self.authenticated_providers[provider] = {
                "credentials": result.credentials,
                "method": result.method,
                "authenticator": authenticator,
            }

        return result

    async def authenticate_all(
        self, configs: dict[str, dict[str, Any]]
    ) -> dict[str, AuthenticationResult]:
        """
        Authenticate all configured providers.

        Args:
            configs: Dictionary mapping provider names to their configs

        Returns:
            Dictionary mapping provider names to authentication results
        """
        results = {}

        for provider, config in configs.items():
            if config.get("enabled", False):
                result = await self.authenticate_provider(provider, config)
                results[provider] = result

        return results

    def get_credentials(self, provider: str) -> Any | None:
        """Get authenticated credentials for a provider."""
        auth_info = self.authenticated_providers.get(provider.lower())
        return auth_info["credentials"] if auth_info else None

    def is_provider_authenticated(self, provider: str) -> bool:
        """Check if a provider is authenticated."""
        return provider.lower() in self.authenticated_providers

    def get_authentication_summary(self) -> dict[str, dict[str, Any]]:
        """Get summary of authentication status for all providers."""
        summary = {}

        for provider, auth_info in self.authenticated_providers.items():
            summary[provider] = {
                "authenticated": True,
                "method": auth_info["method"],
                "provider": provider,
            }

        # Add unauthenticated providers
        for provider in self.authenticators:
            if provider not in summary:
                summary[provider] = {"authenticated": False, "method": None, "provider": provider}

        return summary
