"""
Icinga check plugins for multi-cloud cost monitoring.

Provides Nagios/Icinga compatible check plugins with proper exit codes,
performance data output, and monitoring integration capabilities.
"""

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from ..config.settings import CloudConfig, get_config
from ..providers.base import CloudCostProvider, ProviderFactory
from ..utils.auth import MultiCloudAuthManager
from ..utils.data_normalizer import CostDataNormalizer

logger = logging.getLogger(__name__)


class IcingaExitCode(Enum):
    """Standard Icinga/Nagios exit codes."""

    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


class IcingaCheckResult:
    """Represents the result of an Icinga check."""

    def __init__(
        self,
        exit_code: IcingaExitCode,
        message: str,
        performance_data: dict[str, Any] | None = None,
        long_output: list[str] | None = None,
    ):
        self.exit_code = exit_code
        self.message = message
        self.performance_data = performance_data or {}
        self.long_output = long_output or []

    def format_output(self, include_perfdata: bool = True) -> str:
        """Format the check result for Icinga output."""
        output_parts = [self.message]

        # Add performance data
        if include_perfdata and self.performance_data:
            perfdata_parts = []
            for key, data in self.performance_data.items():
                perfdata_str = self._format_perfdata_item(key, data)
                perfdata_parts.append(perfdata_str)

            if perfdata_parts:
                output_parts.append("|")
                output_parts.extend(perfdata_parts)

        result = " ".join(output_parts)

        # Add long output
        if self.long_output:
            result += "\n" + "\n".join(self.long_output)

        return result

    def _format_perfdata_item(self, key: str, data: dict[str, Any]) -> str:
        """Format a single performance data item."""
        value = data.get("value", 0)
        unit = data.get("unit", "")
        warn = data.get("warning")
        crit = data.get("critical")
        min_val = data.get("min", 0)
        max_val = data.get("max", "")

        # Format: label=value[UOM];[warn];[crit];[min];[max]
        perfdata = f"'{key}'={value}{unit}"

        # Add thresholds
        threshold_parts = []
        threshold_parts.append(str(warn) if warn is not None else "")
        threshold_parts.append(str(crit) if crit is not None else "")
        threshold_parts.append(str(min_val))
        threshold_parts.append(str(max_val))

        # Only add thresholds if any are specified
        if any(part for part in threshold_parts):
            perfdata += ";" + ";".join(threshold_parts)

        return perfdata


class CloudCostCheckPlugin:
    """Base class for cloud cost check plugins."""

    def __init__(self, config: CloudConfig):
        self.config = config
        self.auth_manager = MultiCloudAuthManager()
        self.normalizer = CostDataNormalizer()

    async def authenticate_providers(self, providers: list[str]) -> dict[str, CloudCostProvider]:
        """Authenticate specified cloud providers."""
        authenticated_providers = {}

        for provider_name in providers:
            if not self.config.is_provider_enabled(provider_name):
                continue

            provider_config = self.config.get_provider_config(provider_name)

            try:
                provider = ProviderFactory.create_provider(provider_name, provider_config)
                auth_result = await self.auth_manager.authenticate_provider(
                    provider_name, provider_config
                )

                if auth_result.success:
                    authenticated_providers[provider_name] = provider
                else:
                    logger.warning(
                        f"Failed to authenticate {provider_name}: {auth_result.error_message}"
                    )

            except Exception as e:
                logger.error(f"Error setting up {provider_name} provider: {e}")

        return authenticated_providers

    def get_thresholds(self, provider: str | None = None) -> tuple[float | None, float | None]:
        """Get warning and critical thresholds for a provider."""
        warning = self.config.get_threshold("warning", provider)
        critical = self.config.get_threshold("critical", provider)
        return warning, critical


class DailyCostCheckPlugin(CloudCostCheckPlugin):
    """Check plugin for daily cost monitoring."""

    async def check(
        self,
        provider: str | None = None,
        warning_threshold: float | None = None,
        critical_threshold: float | None = None,
        check_date: date | None = None,
    ) -> IcingaCheckResult:
        """
        Check daily costs against thresholds.

        Args:
            provider: Specific provider to check (None for all)
            warning_threshold: Warning threshold override
            critical_threshold: Critical threshold override
            check_date: Date to check (defaults to today)

        Returns:
            IcingaCheckResult with check status
        """
        if check_date is None:
            check_date = date.today()

        try:
            # Determine which providers to check
            providers_to_check = [provider] if provider else self.config.enabled_providers

            # Authenticate providers
            authenticated_providers = await self.authenticate_providers(providers_to_check)

            if not authenticated_providers:
                return IcingaCheckResult(
                    IcingaExitCode.UNKNOWN, "UNKNOWN - No authenticated providers available"
                )

            # Get cost data
            total_cost = 0.0
            provider_costs = {}
            performance_data = {}
            long_output = []

            for provider_name, provider_instance in authenticated_providers.items():
                try:
                    cost_summary = await provider_instance.get_cost_data(check_date, check_date)

                    provider_cost = cost_summary.total_cost
                    total_cost += provider_cost
                    provider_costs[provider_name] = provider_cost

                    # Get provider-specific thresholds
                    warn_threshold, crit_threshold = self.get_thresholds(provider_name)

                    # Override with command-line thresholds if provided
                    if warning_threshold is not None:
                        warn_threshold = warning_threshold
                    if critical_threshold is not None:
                        crit_threshold = critical_threshold

                    # Add performance data
                    performance_data[f"{provider_name}_cost"] = {
                        "value": round(provider_cost, 2),
                        "unit": "USD",
                        "warning": warn_threshold,
                        "critical": crit_threshold,
                        "min": 0,
                    }

                    # Add detailed output
                    status = "OK"
                    if crit_threshold and provider_cost >= crit_threshold:
                        status = "CRITICAL"
                    elif warn_threshold and provider_cost >= warn_threshold:
                        status = "WARNING"

                    long_output.append(f"{provider_name.upper()}: ${provider_cost:.2f} [{status}]")

                except Exception as e:
                    logger.error(f"Failed to get cost data for {provider_name}: {e}")
                    long_output.append(f"{provider_name.upper()}: ERROR - {str(e)}")

            # Add total cost performance data
            global_warn, global_crit = self.get_thresholds()
            if warning_threshold is not None:
                global_warn = warning_threshold
            if critical_threshold is not None:
                global_crit = critical_threshold

            performance_data["total_cost"] = {
                "value": round(total_cost, 2),
                "unit": "USD",
                "warning": global_warn,
                "critical": global_crit,
                "min": 0,
            }

            # Determine overall status
            exit_code = IcingaExitCode.OK
            status_text = "OK"

            if global_crit and total_cost >= global_crit:
                exit_code = IcingaExitCode.CRITICAL
                status_text = "CRITICAL"
            elif global_warn and total_cost >= global_warn:
                exit_code = IcingaExitCode.WARNING
                status_text = "WARNING"

            # Format message
            if provider:
                message = f"{status_text} - {provider.upper()} daily cost: ${total_cost:.2f}"
            else:
                provider_breakdown = ", ".join(
                    [f"{p}: ${c:.2f}" for p, c in provider_costs.items()]
                )
                message = (
                    f"{status_text} - Total daily cost: ${total_cost:.2f} ({provider_breakdown})"
                )

            return IcingaCheckResult(exit_code, message, performance_data, long_output)

        except Exception as e:
            logger.error(f"Daily cost check failed: {e}")
            return IcingaCheckResult(
                IcingaExitCode.UNKNOWN, f"UNKNOWN - Check execution failed: {str(e)}"
            )


class MonthlyCostCheckPlugin(CloudCostCheckPlugin):
    """Check plugin for monthly cost monitoring."""

    async def check(
        self,
        provider: str | None = None,
        budget_threshold: float | None = None,
        warning_percentage: float = 75.0,
        critical_percentage: float = 90.0,
    ) -> IcingaCheckResult:
        """
        Check monthly costs against budget.

        Args:
            provider: Specific provider to check (None for all)
            budget_threshold: Monthly budget threshold
            warning_percentage: Warning threshold percentage of budget
            critical_percentage: Critical threshold percentage of budget

        Returns:
            IcingaCheckResult with check status
        """
        try:
            # Get current month date range
            now = datetime.now()
            start_of_month = now.replace(day=1).date()
            current_date = now.date()

            # Determine which providers to check
            providers_to_check = [provider] if provider else self.config.enabled_providers

            # Authenticate providers
            authenticated_providers = await self.authenticate_providers(providers_to_check)

            if not authenticated_providers:
                return IcingaCheckResult(
                    IcingaExitCode.UNKNOWN, "UNKNOWN - No authenticated providers available"
                )

            # Get cost data
            total_cost = 0.0
            provider_costs = {}
            performance_data = {}
            long_output = []

            for provider_name, provider_instance in authenticated_providers.items():
                try:
                    cost_summary = await provider_instance.get_cost_data(
                        start_of_month, current_date
                    )

                    provider_cost = cost_summary.total_cost
                    total_cost += provider_cost
                    provider_costs[provider_name] = provider_cost

                    long_output.append(
                        f"{provider_name.upper()}: ${provider_cost:.2f} (month-to-date)"
                    )

                except Exception as e:
                    logger.error(f"Failed to get cost data for {provider_name}: {e}")
                    long_output.append(f"{provider_name.upper()}: ERROR - {str(e)}")

            # Calculate budget status
            if budget_threshold:
                budget_used_percentage = (total_cost / budget_threshold) * 100
                remaining_budget = budget_threshold - total_cost

                # Add performance data
                performance_data["monthly_cost"] = {
                    "value": round(total_cost, 2),
                    "unit": "USD",
                    "warning": round(budget_threshold * warning_percentage / 100, 2),
                    "critical": round(budget_threshold * critical_percentage / 100, 2),
                    "min": 0,
                    "max": budget_threshold,
                }

                performance_data["budget_used_percentage"] = {
                    "value": round(budget_used_percentage, 1),
                    "unit": "%",
                    "warning": warning_percentage,
                    "critical": critical_percentage,
                    "min": 0,
                    "max": 100,
                }

                # Determine status
                exit_code = IcingaExitCode.OK
                status_text = "OK"

                if budget_used_percentage >= critical_percentage:
                    exit_code = IcingaExitCode.CRITICAL
                    status_text = "CRITICAL"
                elif budget_used_percentage >= warning_percentage:
                    exit_code = IcingaExitCode.WARNING
                    status_text = "WARNING"

                # Format message
                message = (
                    f"{status_text} - Monthly cost: ${total_cost:.2f} "
                    f"({budget_used_percentage:.1f}% of ${budget_threshold:.2f} budget, "
                    f"${remaining_budget:.2f} remaining)"
                )

            else:
                # No budget set, just report current cost
                performance_data["monthly_cost"] = {
                    "value": round(total_cost, 2),
                    "unit": "USD",
                    "min": 0,
                }

                message = f"OK - Monthly cost: ${total_cost:.2f} (no budget threshold set)"
                exit_code = IcingaExitCode.OK

            return IcingaCheckResult(exit_code, message, performance_data, long_output)

        except Exception as e:
            logger.error(f"Monthly cost check failed: {e}")
            return IcingaCheckResult(
                IcingaExitCode.UNKNOWN, f"UNKNOWN - Check execution failed: {str(e)}"
            )


class ServiceCostCheckPlugin(CloudCostCheckPlugin):
    """Check plugin for service-level cost monitoring."""

    async def check(
        self,
        provider: str,
        service_name: str,
        warning_threshold: float | None = None,
        critical_threshold: float | None = None,
        time_period: int = 1,  # days
    ) -> IcingaCheckResult:
        """
        Check service-specific costs.

        Args:
            provider: Cloud provider name
            service_name: Service to monitor
            warning_threshold: Warning threshold
            critical_threshold: Critical threshold
            time_period: Time period in days

        Returns:
            IcingaCheckResult with check status
        """
        try:
            # Authenticate provider
            authenticated_providers = await self.authenticate_providers([provider])

            if provider not in authenticated_providers:
                return IcingaCheckResult(
                    IcingaExitCode.UNKNOWN, f"UNKNOWN - Could not authenticate {provider} provider"
                )

            # Get date range
            end_date = date.today()
            start_date = end_date - timedelta(days=time_period - 1)

            # Get service costs
            provider_instance = authenticated_providers[provider]
            service_costs = await provider_instance.get_service_costs(start_date, end_date)

            # Find the specific service
            service_cost = service_costs.get(service_name, 0.0)

            # Get thresholds
            if warning_threshold is None or critical_threshold is None:
                warn, crit = self.get_thresholds(provider)
                warning_threshold = warning_threshold or warn
                critical_threshold = critical_threshold or crit

            # Add performance data
            performance_data = {
                f"{service_name.lower().replace(' ', '_')}_cost": {
                    "value": round(service_cost, 2),
                    "unit": "USD",
                    "warning": warning_threshold,
                    "critical": critical_threshold,
                    "min": 0,
                }
            }

            # Determine status
            exit_code = IcingaExitCode.OK
            status_text = "OK"

            if critical_threshold and service_cost >= critical_threshold:
                exit_code = IcingaExitCode.CRITICAL
                status_text = "CRITICAL"
            elif warning_threshold and service_cost >= warning_threshold:
                exit_code = IcingaExitCode.WARNING
                status_text = "WARNING"

            # Format message
            period_text = f"{time_period} day{'s' if time_period > 1 else ''}"
            message = (
                f"{status_text} - {provider.upper()} {service_name} cost: "
                f"${service_cost:.2f} ({period_text})"
            )

            # Add top services to long output
            long_output = ["Top 5 services by cost:"]
            sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)
            for svc, cost in sorted_services[:5]:
                long_output.append(f"  {svc}: ${cost:.2f}")

            return IcingaCheckResult(exit_code, message, performance_data, long_output)

        except Exception as e:
            logger.error(f"Service cost check failed: {e}")
            return IcingaCheckResult(
                IcingaExitCode.UNKNOWN, f"UNKNOWN - Check execution failed: {str(e)}"
            )


async def main():
    """Main entry point for Icinga check plugins."""
    parser = argparse.ArgumentParser(description="Multi-cloud cost monitoring Icinga check plugin")

    parser.add_argument(
        "check_type", choices=["daily", "monthly", "service"], help="Type of cost check to perform"
    )

    parser.add_argument("--provider", help="Cloud provider to check (aws, azure, gcp)")

    parser.add_argument("--warning", "-w", type=float, help="Warning threshold")

    parser.add_argument("--critical", "-c", type=float, help="Critical threshold")

    parser.add_argument("--service", help="Service name for service-level checks")

    parser.add_argument("--budget", type=float, help="Monthly budget threshold")

    parser.add_argument("--period", type=int, default=1, help="Time period in days (default: 1)")

    parser.add_argument(
        "--no-perfdata", action="store_true", help="Disable performance data output"
    )

    parser.add_argument("--config", help="Path to configuration file")

    args = parser.parse_args()

    # Load configuration
    try:
        config = get_config()

        # Override config file if specified
        if args.config:
            # TODO: Implement config file override
            pass

    except Exception as e:
        result = IcingaCheckResult(
            IcingaExitCode.UNKNOWN, f"UNKNOWN - Configuration error: {str(e)}"
        )
        print(result.format_output(False))
        sys.exit(result.exit_code.value)

    # Execute the appropriate check
    try:
        if args.check_type == "daily":
            plugin = DailyCostCheckPlugin(config)
            result = await plugin.check(
                provider=args.provider,
                warning_threshold=args.warning,
                critical_threshold=args.critical,
            )

        elif args.check_type == "monthly":
            plugin = MonthlyCostCheckPlugin(config)
            result = await plugin.check(
                provider=args.provider,
                budget_threshold=args.budget,
                warning_percentage=75.0,  # Could be made configurable
                critical_percentage=90.0,
            )

        elif args.check_type == "service":
            if not args.service:
                result = IcingaCheckResult(
                    IcingaExitCode.UNKNOWN, "UNKNOWN - Service name required for service checks"
                )
            elif not args.provider:
                result = IcingaCheckResult(
                    IcingaExitCode.UNKNOWN, "UNKNOWN - Provider required for service checks"
                )
            else:
                plugin = ServiceCostCheckPlugin(config)
                result = await plugin.check(
                    provider=args.provider,
                    service_name=args.service,
                    warning_threshold=args.warning,
                    critical_threshold=args.critical,
                    time_period=args.period,
                )

    except Exception as e:
        result = IcingaCheckResult(
            IcingaExitCode.UNKNOWN, f"UNKNOWN - Check execution failed: {str(e)}"
        )

    # Output result and exit
    print(result.format_output(not args.no_perfdata))
    sys.exit(result.exit_code.value)


if __name__ == "__main__":
    asyncio.run(main())
