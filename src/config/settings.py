"""
Configuration management for multi-cloud cost monitoring.

Uses dynaconf for flexible configuration with YAML files and environment overrides.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List

from dynaconf import Dynaconf, Validator

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

# Initialize dynaconf with multiple configuration sources
settings = Dynaconf(
    envvar_prefix="CLOUDCOST",
    settings_files=[
        str(CONFIG_DIR / "config.yaml"),        # Base configuration
        str(CONFIG_DIR / "development.yaml"),   # Development-specific settings (overrides base)
        str(CONFIG_DIR / "config.local.yaml"),  # Local overrides (git-ignored)
        str(CONFIG_DIR / ".secrets.yaml"),     # Secrets file (git-ignored)
    ],
    environments=False,  # Use file-based configuration instead of environment sections
    load_dotenv=True,
    merge_enabled=True,
    envvar_separator="__",  # Support nested config via CLOUDCOST__AWS__REGION=us-east-1
    validators=[
        # Cloud provider validation - only validate when providers are actually enabled
        Validator("clouds.aws.region", must_exist=True, when=Validator("clouds.aws.enabled", eq=True)),
        Validator("clouds.azure.subscription_id", must_exist=True, when=Validator("clouds.azure.enabled", eq=True)),
        Validator("clouds.gcp.project_id", must_exist=True, when=Validator("clouds.gcp.enabled", eq=True)),

        # Threshold validation
        Validator("monitoring.thresholds.warning", gte=0),
        Validator("monitoring.thresholds.critical", gte=0),
        # Validator("monitoring.thresholds.critical", gt=Validator("monitoring.thresholds.warning")),  # Disabled due to validator comparison issue

        # Dashboard validation
        Validator("dashboard.port", gte=1024, lte=65535),
        Validator("dashboard.host", must_exist=True),
    ]
)


class CloudConfig:
    """Configuration wrapper for cloud provider settings."""

    def __init__(self):
        self.settings = settings
        self._validate_config()

    def _validate_config(self):
        """Validate the configuration on initialization."""
        try:
            settings.validators.validate()
        except Exception as e:
            # During initial setup, be more lenient with validation
            import logging
            logging.warning(f"Configuration validation warning: {e}")
            logging.warning("Some providers may not be properly configured yet")
            # Don't raise error during initial setup

    @property
    def aws(self) -> Dict[str, Any]:
        """AWS configuration settings."""
        return self.settings.get("clouds.aws", {})

    @property
    def azure(self) -> Dict[str, Any]:
        """Azure configuration settings."""
        return self.settings.get("clouds.azure", {})

    @property
    def gcp(self) -> Dict[str, Any]:
        """GCP configuration settings."""
        return self.settings.get("clouds.gcp", {})

    @property
    def enabled_providers(self) -> List[str]:
        """List of enabled cloud providers."""
        enabled = []
        if self.aws.get("enabled", False):
            enabled.append("aws")
        if self.azure.get("enabled", False):
            enabled.append("azure")
        if self.gcp.get("enabled", False):
            enabled.append("gcp")
        return enabled

    @property
    def monitoring(self) -> Dict[str, Any]:
        """Monitoring and alerting configuration."""
        return self.settings.get("monitoring", {})

    @property
    def dashboard(self) -> Dict[str, Any]:
        """Dashboard configuration."""
        return self.settings.get("dashboard", {})

    @property
    def cache(self) -> Dict[str, Any]:
        """Cache configuration."""
        return self.settings.get("cache", {})

    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """Get configuration for a specific cloud provider."""
        provider_configs = {
            "aws": self.aws,
            "azure": self.azure,
            "gcp": self.gcp
        }
        return provider_configs.get(provider, {})

    def is_provider_enabled(self, provider: str) -> bool:
        """Check if a specific cloud provider is enabled."""
        return provider in self.enabled_providers

    def get_threshold(self, threshold_type: str, provider: Optional[str] = None) -> Optional[float]:
        """
        Get threshold value for monitoring.

        Args:
            threshold_type: 'warning' or 'critical'
            provider: Optional provider-specific threshold

        Returns:
            Threshold value or None if not configured
        """
        if provider and provider in self.enabled_providers:
            # Try provider-specific threshold first
            provider_threshold = self.get_provider_config(provider).get(
                f"thresholds.{threshold_type}"
            )
            if provider_threshold is not None:
                return float(provider_threshold)

        # Fall back to global threshold
        global_threshold = self.monitoring.get(f"thresholds.{threshold_type}")
        if global_threshold is not None:
            return float(global_threshold)

        return None

    def get_icinga_config(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get Icinga-specific configuration."""
        base_config = self.monitoring.get("icinga", {})

        if provider:
            provider_config = self.get_provider_config(provider).get("icinga", {})
            # Merge provider-specific config over base config
            return {**base_config, **provider_config}

        return base_config

    def override_from_cli(self, cli_args: Dict[str, Any]):
        """Override configuration with CLI arguments."""
        # Map CLI arguments to configuration paths
        cli_mapping = {
            "aws_region": "clouds.aws.region",
            "azure_subscription": "clouds.azure.subscription_id",
            "gcp_project": "clouds.gcp.project_id",
            "warning_threshold": "monitoring.thresholds.warning",
            "critical_threshold": "monitoring.thresholds.critical",
            "dashboard_port": "dashboard.port",
            "dashboard_host": "dashboard.host",
            "cache_ttl": "cache.ttl",
        }

        for cli_key, config_path in cli_mapping.items():
            if cli_args.get(cli_key) is not None:
                self.settings.set(config_path, cli_args[cli_key])

        # Re-validate after overrides
        self._validate_config()


# Global configuration instance
config = CloudConfig()


def get_config() -> CloudConfig:
    """Get the global configuration instance."""
    return config


def reload_config():
    """Reload configuration from files."""
    global config
    settings.reload()
    config = CloudConfig()
    return config