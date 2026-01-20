"""
Multi-cloud authentication utilities for AWS, Azure, and GCP.

Provides a unified interface for handling authentication across different cloud providers
with support for various authentication methods and credential management.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass
from abc import ABC, abstractmethod

# AWS imports
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound
    from botocore.config import Config
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False

# Azure imports
try:
    from azure.identity import (
        DefaultAzureCredential,
        ClientSecretCredential,
        AzureCliCredential,
        EnvironmentCredential,
        ManagedIdentityCredential
    )
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

# GCP imports
try:
    from google.cloud import billing_v1
    from google.auth import default as gcp_default
    from google.auth.exceptions import DefaultCredentialsError
    from google.oauth2 import service_account
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class AuthenticationResult:
    """Result of an authentication attempt."""
    success: bool
    provider: str
    method: str
    error_message: Optional[str] = None
    credentials: Optional[Any] = None


class CloudAuthenticator(ABC):
    """Abstract base class for cloud authenticators."""

    def __init__(self, config: Dict[str, Any]):
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
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="none",
                error_message="AWS SDK (boto3) not available"
            )

        # If access keys are provided in config, use ONLY those (highest precedence)
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")

        if access_key and secret_key:
            logger.info(f"🔵 AWS: Using access keys from secrets config (highest precedence)")
            result = await self._authenticate_with_access_keys()
            if result.success:
                logger.info(f"🔵 AWS: Authentication successful using secrets access keys")
                return result
            else:
                logger.error(f"🔵 AWS: Secrets access keys failed: {result.error_message}")
                # If secrets file credentials fail, this is an error - don't fallback
                return result

        # Fallback to other authentication methods only if no access keys in config
        logger.info(f"🔵 AWS: No access keys in config, trying fallback methods")
        auth_methods = [
            self._authenticate_with_environment,   # Environment variables
            self._authenticate_with_profile,       # AWS CLI profile
            self._authenticate_with_instance_profile, # EC2 instance profile (lowest priority)
        ]

        for method in auth_methods:
            try:
                logger.debug(f"🔵 AWS: Trying authentication method: {method.__name__}")
                result = await method()
                if result.success:
                    logger.info(f"🔵 AWS: Authentication successful using {result.method}")
                    return result
                else:
                    logger.debug(f"🔵 AWS: Method {method.__name__} failed: {result.error_message}")
            except Exception as e:
                logger.debug(f"🔵 AWS: Authentication method {method.__name__} failed: {e}")
                continue

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="none",
            error_message="All AWS authentication methods failed"
        )

    async def _authenticate_with_profile(self) -> AuthenticationResult:
        """Authenticate using AWS CLI profile."""
        profile_name = self.config.get("profile", os.environ.get("AWS_PROFILE", "default"))

        try:
            session = boto3.Session(profile_name=profile_name)
            credentials = session.get_credentials()

            if credentials and self.test_credentials(session):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method=f"profile:{profile_name}",
                    credentials=session
                )
        except (ProfileNotFound, NoCredentialsError) as e:
            logger.debug(f"AWS profile authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="profile",
            error_message=f"Profile '{profile_name}' not found or invalid"
        )

    async def _authenticate_with_environment(self) -> AuthenticationResult:
        """Authenticate using environment variables."""
        required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]

        if missing_vars:
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="environment",
                error_message=f"Missing environment variables: {missing_vars}"
            )

        try:
            session = boto3.Session(
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
                region_name=self.config.get("region", os.environ.get("AWS_DEFAULT_REGION"))
            )

            if self.test_credentials(session):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="environment",
                    credentials=session
                )
        except (ClientError, NoCredentialsError) as e:
            logger.debug(f"AWS environment authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="environment",
            error_message="Invalid environment credentials"
        )

    async def _authenticate_with_instance_profile(self) -> AuthenticationResult:
        """Authenticate using EC2 instance profile or IAM role."""
        try:
            session = boto3.Session(region_name=self.config.get("region"))
            credentials = session.get_credentials()

            if credentials and self.test_credentials(session):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="instance_profile",
                    credentials=session
                )
        except Exception as e:
            logger.debug(f"AWS instance profile authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="instance_profile",
            error_message="Instance profile not available"
        )

    async def _authenticate_with_access_keys(self) -> AuthenticationResult:
        """Authenticate using access keys from config."""
        access_key = self.config.get("access_key_id")
        secret_key = self.config.get("secret_access_key")

        logger.debug(f"🔵 AWS: _authenticate_with_access_keys - access_key: {bool(access_key)}, secret_key: {bool(secret_key)}")

        if not access_key or not secret_key:
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="access_keys",
                error_message="Access key or secret key not provided in config"
            )

        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=self.config.get("session_token"),
                region_name=self.config.get("region")
            )

            if self.test_credentials(session):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="access_keys",
                    credentials=session
                )
        except Exception as e:
            logger.debug(f"AWS access key authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="access_keys",
            error_message="Invalid access keys"
        )

    def test_credentials(self, session: boto3.Session) -> bool:
        """Test AWS credentials by making a simple API call."""
        try:
            sts_client = session.client('sts')
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
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="none",
                error_message="Azure SDK not available"
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

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="none",
            error_message="All Azure authentication methods failed"
        )

    async def _authenticate_with_service_principal(self) -> AuthenticationResult:
        """Authenticate using service principal credentials from config file."""
        tenant_id = self.config.get("tenant_id")
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")

        if not all([tenant_id, client_id, client_secret]):
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="service_principal",
                error_message="Missing tenant_id, client_id, or client_secret"
            )

        try:
            credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret
            )

            if self.test_credentials(credential):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="service_principal",
                    credentials=credential
                )
        except Exception as e:
            logger.debug(f"Azure service principal authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="service_principal",
            error_message="Invalid service principal credentials"
        )

    async def _authenticate_with_environment(self) -> AuthenticationResult:
        """Authenticate using environment credentials."""
        try:
            credential = EnvironmentCredential()

            if self.test_credentials(credential):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="environment",
                    credentials=credential
                )
        except Exception as e:
            logger.debug(f"Azure environment authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="environment",
            error_message="Environment credentials not available"
        )

    async def _authenticate_with_azure_cli(self) -> AuthenticationResult:
        """Authenticate using Azure CLI credentials."""
        try:
            credential = AzureCliCredential()

            if self.test_credentials(credential):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="azure_cli",
                    credentials=credential
                )
        except Exception as e:
            logger.debug(f"Azure CLI authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="azure_cli",
            error_message="Azure CLI not authenticated"
        )

    async def _authenticate_with_managed_identity(self) -> AuthenticationResult:
        """Authenticate using managed identity."""
        try:
            credential = ManagedIdentityCredential()

            if self.test_credentials(credential):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="managed_identity",
                    credentials=credential
                )
        except Exception as e:
            logger.debug(f"Azure managed identity authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="managed_identity",
            error_message="Managed identity not available"
        )

    async def _authenticate_with_default_credential(self) -> AuthenticationResult:
        """Authenticate using default Azure credential chain."""
        try:
            credential = DefaultAzureCredential()

            if self.test_credentials(credential):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="default_credential",
                    credentials=credential
                )
        except Exception as e:
            logger.debug(f"Azure default credential authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="default_credential",
            error_message="Default credential chain failed"
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
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="none",
                error_message="GCP SDK not available"
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

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="none",
            error_message="All GCP authentication methods failed"
        )

    async def _authenticate_with_service_account(self) -> AuthenticationResult:
        """Authenticate using service account JSON file from config."""
        credentials_path = self.config.get("credentials_path")

        if not credentials_path:
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="service_account",
                error_message="No service account credentials path provided"
            )

        if not Path(credentials_path).exists():
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="service_account",
                error_message=f"Service account file not found: {credentials_path}"
            )

        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )

            if self.test_credentials(credentials):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="service_account",
                    credentials=credentials
                )
        except Exception as e:
            logger.debug(f"GCP service account authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="service_account",
            error_message="Invalid service account credentials"
        )

    async def _authenticate_with_default_credentials(self) -> AuthenticationResult:
        """Authenticate using default GCP credentials."""
        try:
            credentials, project = gcp_default()

            if self.test_credentials(credentials):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="default_credentials",
                    credentials=credentials
                )
        except DefaultCredentialsError as e:
            logger.debug(f"GCP default credentials failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="default_credentials",
            error_message="Default credentials not available"
        )

    async def _authenticate_with_environment(self) -> AuthenticationResult:
        """Authenticate using environment variable JSON."""
        creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

        if not creds_json:
            return AuthenticationResult(
                success=False,
                provider=self.provider_name,
                method="environment",
                error_message="No credentials JSON in environment"
            )

        try:
            creds_info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_info)

            if self.test_credentials(credentials):
                return AuthenticationResult(
                    success=True,
                    provider=self.provider_name,
                    method="environment_json",
                    credentials=credentials
                )
        except Exception as e:
            logger.debug(f"GCP environment JSON authentication failed: {e}")

        return AuthenticationResult(
            success=False,
            provider=self.provider_name,
            method="environment",
            error_message="Invalid credentials JSON in environment"
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

    async def authenticate_provider(self, provider: str, config: Dict[str, Any]) -> AuthenticationResult:
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
            return AuthenticationResult(
                success=False,
                provider=provider,
                method="none",
                error_message=f"Unknown provider: {provider}"
            )

        authenticator = self.authenticators[provider](config)
        result = await authenticator.authenticate()

        if result.success:
            self.authenticated_providers[provider] = {
                "credentials": result.credentials,
                "method": result.method,
                "authenticator": authenticator
            }

        return result

    async def authenticate_all(self, configs: Dict[str, Dict[str, Any]]) -> Dict[str, AuthenticationResult]:
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

    def get_credentials(self, provider: str) -> Optional[Any]:
        """Get authenticated credentials for a provider."""
        auth_info = self.authenticated_providers.get(provider.lower())
        return auth_info["credentials"] if auth_info else None

    def is_provider_authenticated(self, provider: str) -> bool:
        """Check if a provider is authenticated."""
        return provider.lower() in self.authenticated_providers

    def get_authentication_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary of authentication status for all providers."""
        summary = {}

        for provider, auth_info in self.authenticated_providers.items():
            summary[provider] = {
                "authenticated": True,
                "method": auth_info["method"],
                "provider": provider
            }

        # Add unauthenticated providers
        for provider in self.authenticators.keys():
            if provider not in summary:
                summary[provider] = {
                    "authenticated": False,
                    "method": None,
                    "provider": provider
                }

        return summary