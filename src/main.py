"""
Main CLI interface for multi-cloud cost monitoring.

Provides command-line interface for cost monitoring, alerting, and dashboard
functionality across AWS, Azure, and GCP.
"""

import asyncio
import logging
import sys
from datetime import date, timedelta

try:
    import click

    CLICK_AVAILABLE = True
except ImportError:
    CLICK_AVAILABLE = False

from .config.settings import get_config, reload_config
from .monitoring.alerts import ThresholdMonitor
from .monitoring.text_alerts import AlertFormatConfig, OutputFormat, TextAlertNotifier

# Import provider implementations to register them
from .providers.base import ProviderFactory
from .utils.auth import MultiCloudAuthManager
from .utils.data_normalizer import CostDataNormalizer
from .visualization.dashboard.core import DASH_AVAILABLE, CostMonitorDashboard

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity settings."""
    # Configure root logger - default is quiet (only show results)
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        # Default behavior: suppress all logs except errors
        logging.getLogger().setLevel(logging.ERROR)

    # Configure cloud provider loggers to reduce noise
    cloud_loggers = [
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity._internal.get_token_mixin",
        "boto3",
        "botocore",
        "urllib3",
        "google.auth",
        "google.cloud",
        "googleapiclient",
    ]

    for logger_name in cloud_loggers:
        logger = logging.getLogger(logger_name)
        if verbose:
            logger.setLevel(logging.INFO)
        else:
            # Default and quiet: suppress all cloud provider logs
            logger.setLevel(logging.ERROR)


@click.group()
@click.option("--config", "-c", help="Path to configuration file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging and debug output")
@click.pass_context
def cli(ctx, config, verbose):
    """Multi-Cloud Cost Monitor - Monitor costs across AWS, Azure, and GCP."""
    if not CLICK_AVAILABLE:
        print("Error: CLI requires Click. Install with: pip install click")
        sys.exit(1)

    setup_logging(verbose)

    # Ensure context object exists
    ctx.ensure_object(dict)

    # Store common options
    ctx.obj["config_file"] = config
    ctx.obj["verbose"] = verbose

    # Load configuration
    try:
        if config:
            # TODO: Implement custom config loading
            pass
        ctx.obj["config"] = get_config()
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["aws", "azure", "gcp", "all"]),
    default="all",
    help="Cloud provider to check (default: all)",
)
@click.option("--warning", "-w", type=float, help="Warning threshold override")
@click.option("--critical", "-c", type=float, help="Critical threshold override")
@click.option(
    "--date", type=click.DateTime(formats=["%Y-%m-%d"]), help="Date to check (default: today)"
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["plain", "colored", "json", "table"]),
    default="colored",
    help="Output format",
)
async def _authenticate_providers_for_check(config, providers_to_check):
    """Authenticate providers and return successfully authenticated ones."""
    auth_manager = MultiCloudAuthManager()
    authenticated_providers = {}

    for provider_name in providers_to_check:
        if not config.is_provider_enabled(provider_name):
            continue

        provider_config = config.get_provider_config(provider_name)
        try:
            provider_instance = ProviderFactory.create_provider(provider_name, provider_config)
            auth_result = await auth_manager.authenticate_provider(provider_name, provider_config)

            if auth_result.success:
                authenticated_providers[provider_name] = provider_instance
            else:
                click.echo(
                    f"Failed to authenticate {provider_name}: {auth_result.error_message}", err=True
                )

        except Exception as e:
            click.echo(f"Error setting up {provider_name}: {e}", err=True)

    return authenticated_providers


async def _gather_cost_data_for_check(authenticated_providers, check_date):
    """Gather cost data from all authenticated providers."""
    provider_costs = {}
    total_cost = 0.0

    for provider_name, provider_instance in authenticated_providers.items():
        try:
            cost_summary = await provider_instance.get_cost_data(check_date, check_date)
            provider_costs[provider_name] = cost_summary.total_cost
            total_cost += cost_summary.total_cost
        except Exception as e:
            click.echo(f"Error getting cost data for {provider_name}: {e}", err=True)

    return provider_costs, total_cost


def _display_check_json_results(check_date, total_cost, provider_costs, alerts):
    """Display check results in JSON format."""
    import json

    result = {
        "date": check_date.isoformat(),
        "total_cost": total_cost,
        "provider_costs": provider_costs,
        "alerts": [alert.to_dict() for alert in alerts],
        "status": "ok" if not alerts else "alert",
    }
    click.echo(json.dumps(result, indent=2))


def _display_check_text_results(notifier, provider_costs, config, alerts, output_format):
    """Display check results in text format."""
    # Show cost status
    notifier.display_cost_status(
        provider_costs,
        {
            p: {
                "warning": config.get_threshold("warning", p),
                "critical": config.get_threshold("critical", p),
            }
            for p in provider_costs
        },
    )

    # Show alerts if any
    if alerts:
        click.echo("\n")
        format_type = OutputFormat(output_format)
        notifier.notify_multiple(alerts, format_type, include_summary=True)
    else:
        click.echo("\n✅ All costs within thresholds")


@click.pass_context
def check(ctx, provider, warning, critical, date, output_format):
    """Check current costs against thresholds."""

    async def _check():
        config = ctx.obj["config"]
        from datetime import date as date_class

        check_date = date.date() if date else date_class.today()

        # Set up components
        threshold_monitor = ThresholdMonitor(config)
        format_config = AlertFormatConfig(
            use_colors=(output_format == "colored"), show_details=True, include_metadata=True
        )
        notifier = TextAlertNotifier(format_config=format_config)

        try:
            # Determine and authenticate providers
            providers_to_check = [provider] if provider != "all" else config.enabled_providers
            authenticated_providers = await _authenticate_providers_for_check(
                config, providers_to_check
            )

            if not authenticated_providers:
                click.echo("No authenticated providers available", err=True)
                return

            # Check thresholds and gather cost data
            alerts = await threshold_monitor.check_thresholds(authenticated_providers, check_date)
            provider_costs, total_cost = await _gather_cost_data_for_check(
                authenticated_providers, check_date
            )

            # Display results based on format
            if output_format == "json":
                _display_check_json_results(check_date, total_cost, provider_costs, alerts)
            else:
                _display_check_text_results(notifier, provider_costs, config, alerts, output_format)

        except Exception as e:
            click.echo(f"Check failed: {e}", err=True)
            sys.exit(1)

    asyncio.run(_check())


@cli.command()
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=str(date.today() - timedelta(days=7)),
    help="Start date for cost data (default: 7 days ago)",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=str(date.today()),
    help="End date for cost data (default: today)",
)
@click.option(
    "--provider",
    type=click.Choice(["aws", "azure", "gcp", "all"]),
    default="all",
    help="Cloud provider to query (default: all)",
)
@click.option(
    "--granularity",
    type=click.Choice(["daily", "monthly"]),
    default="daily",
    help="Data granularity (default: daily)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--currency", default="USD", help="Currency for cost display")
@click.option("--top-services", is_flag=True, help="Include service breakdown by cost")
@click.option(
    "--group-by",
    multiple=True,
    help="Group by dimensions (e.g. SERVICE, LINKED_ACCOUNT for AWS; SERVICE, SUBSCRIPTION_ID for Azure; SERVICE, PROJECT for GCP). Can be specified multiple times.",
)
async def _authenticate_providers_for_costs(config, providers_to_query):
    """Authenticate providers for cost data retrieval."""
    auth_manager = MultiCloudAuthManager()
    authenticated_providers = {}

    for provider_name in providers_to_query:
        if not config.is_provider_enabled(provider_name):
            continue

        provider_config = config.get_provider_config(provider_name)
        try:
            provider_instance = ProviderFactory.create_provider(provider_name, provider_config)
            auth_result = await auth_manager.authenticate_provider(provider_name, provider_config)

            if auth_result.success:
                authenticated_providers[provider_name] = provider_instance
        except Exception as e:
            click.echo(f"Error getting costs for {provider_name}: {e}", err=True)

    return authenticated_providers


async def _collect_cost_data(authenticated_providers, start, end, granularity, group_by):
    """Collect cost data from authenticated providers."""
    from .providers.base import TimeGranularity

    cost_summaries = []
    granularity_enum = TimeGranularity.DAILY if granularity == "daily" else TimeGranularity.MONTHLY
    group_by_list = [g.strip().upper() for g in group_by if g.strip()] if group_by else None

    for provider_name, provider_instance in authenticated_providers.items():
        try:
            cost_summary = await provider_instance.get_cost_data(
                start, end, granularity_enum, group_by=group_by_list
            )
            cost_summaries.append(cost_summary)
        except Exception as e:
            click.echo(f"Error getting costs for {provider_name}: {e}", err=True)

    return cost_summaries


def _display_service_breakdown(data, top_services, provider):
    """Display service breakdown in table format."""
    if top_services and "combined_service_breakdown" in data and data["combined_service_breakdown"]:
        # Multi-provider service breakdown
        provider_context = ""
        if (
            provider == "all"
            and "provider_breakdown" in data
            and len([p for p, c in data["provider_breakdown"].items() if c > 0]) > 1
        ):
            provider_context = " (All Providers)"
        elif provider != "all":
            provider_context = f" ({provider.upper()})"

        click.echo(f"\nTop Services by Cost{provider_context}:")
        sorted_services = sorted(
            data["combined_service_breakdown"].items(), key=lambda x: x[1], reverse=True
        )[:10]
        for service, cost in sorted_services:
            click.echo(f"  {service}: {cost:.2f} {data['currency']}")

    elif top_services and "service_breakdown" in data and data["service_breakdown"]:
        # Single-provider service breakdown
        provider_context = f" ({provider.upper()})" if provider != "all" else ""
        click.echo(f"\nTop Services by Cost{provider_context}:")
        sorted_services = sorted(
            data["service_breakdown"].items(), key=lambda x: x[1], reverse=True
        )[:10]
        for service, cost in sorted_services:
            click.echo(f"  {service}: {cost:.2f} {data['currency']}")


def _display_account_breakdown(data, group_by, cost_summaries):
    """Display account breakdown in table format."""
    if not (group_by and "LINKED_ACCOUNT" in [g.upper() for g in group_by]):
        return

    # Multi-provider account breakdown
    if "combined_account_breakdown" in data and data["combined_account_breakdown"]:
        click.echo("\nTop Accounts by Cost:")
        sorted_accounts = sorted(
            data["combined_account_breakdown"].items(),
            key=lambda x: x[1].get("total_cost", 0),
            reverse=True,
        )[:15]

        for i, (account_key, account_data) in enumerate(sorted_accounts, 1):
            account_name = account_data.get("account_name", account_key.split(":")[-1])
            cost = account_data.get("total_cost", 0)
            percentage = (cost / data["total_cost"]) * 100 if data["total_cost"] > 0 else 0
            click.echo(
                f"  {i:2d}. {account_name}: {cost:.2f} {data['currency']} ({percentage:.1f}%)"
            )

    # Single provider account breakdown
    elif cost_summaries and len(cost_summaries) == 1:
        account_totals = {}
        for point in cost_summaries[0].data_points:
            if point.account_id:
                account_totals[point.account_id] = (
                    account_totals.get(point.account_id, 0) + point.amount
                )

        if account_totals:
            click.echo("\nTop Accounts by Cost:")
            sorted_accounts = sorted(account_totals.items(), key=lambda x: x[1], reverse=True)[:15]
            for i, (account_id, cost) in enumerate(sorted_accounts, 1):
                percentage = (cost / data["total_cost"]) * 100 if data["total_cost"] > 0 else 0
                click.echo(
                    f"  {i:2d}. Account {account_id}: {cost:.2f} {data['currency']} ({percentage:.1f}%)"
                )


def _display_cost_table(data, start, end, top_services, provider, group_by, cost_summaries):
    """Display cost data in table format."""
    click.echo(f"\nCost Summary ({start} to {end})")
    click.echo("=" * 50)
    click.echo(f"Total Cost: {data['total_cost']:.2f} {data['currency']}")

    if "provider_breakdown" in data:
        click.echo("\nProvider Breakdown:")
        for provider_name, cost in data["provider_breakdown"].items():
            click.echo(f"  {provider_name.upper()}: {cost:.2f} {data['currency']}")

    _display_service_breakdown(data, top_services, provider)
    _display_account_breakdown(data, group_by, cost_summaries)


@click.pass_context
def costs(
    ctx,
    start_date,
    end_date,
    provider,
    granularity,
    output_format,
    currency,
    top_services,
    group_by,
):
    """Retrieve and display cost data."""

    async def _costs():
        config = ctx.obj["config"]
        start = start_date.date() if start_date else date.today() - timedelta(days=7)
        end = end_date.date() if end_date else date.today()

        normalizer = CostDataNormalizer(target_currency=currency)

        try:
            # Determine providers to query
            providers_to_query = [provider] if provider != "all" else config.enabled_providers

            # Authenticate providers and collect cost data
            authenticated_providers = await _authenticate_providers_for_costs(
                config, providers_to_query
            )
            cost_summaries = await _collect_cost_data(
                authenticated_providers, start, end, granularity, group_by
            )

            if not cost_summaries:
                click.echo("No cost data available", err=True)
                return

            # Normalize data
            if len(cost_summaries) > 1:
                multi_cloud_summary = normalizer.aggregate_multi_cloud_data(cost_summaries)
                data = multi_cloud_summary.to_dict()
            else:
                normalized_data = normalizer.normalize_cost_summary(cost_summaries[0])
                data = normalized_data.to_dict()

            # Display results based on output format
            if output_format == "json":
                import json

                click.echo(json.dumps(data, indent=2))
            elif output_format == "csv":
                click.echo("CSV output not yet implemented")
            else:
                _display_cost_table(
                    data, start, end, top_services, provider, group_by, cost_summaries
                )

        except Exception as e:
            click.echo(f"Cost retrieval failed: {e}", err=True)
            sys.exit(1)

    asyncio.run(_costs())


@cli.command()
@click.option("--host", default="0.0.0.0", help="Dashboard host (default: 0.0.0.0)")
@click.option("--port", default=8050, help="Dashboard port (default: 8050)")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.pass_context
def dashboard(ctx, host, port, debug):
    """Start the interactive web dashboard."""
    print(f"Starting dashboard at http://{host}:{port}")

    if not DASH_AVAILABLE:
        click.echo("Error: Dashboard requires Dash and Plotly. Install with:")
        click.echo("pip install dash plotly dash-bootstrap-components")
        sys.exit(1)

    async def _dashboard():
        print("Getting config...")
        config = ctx.obj["config"]

        # Override dashboard config with command line options
        dashboard_config = config.dashboard
        dashboard_config["host"] = host
        dashboard_config["port"] = port
        dashboard_config["debug"] = debug

        try:
            print("Creating CostMonitorDashboard instance...")
            dashboard_app = CostMonitorDashboard(config)
            print(f"Dashboard created successfully, starting server at http://{host}:{port}")
            await dashboard_app.run()

        except KeyboardInterrupt:
            click.echo("Dashboard stopped")
        except Exception as e:
            click.echo(f"Dashboard failed: {e}", err=True)
            import traceback

            traceback.print_exc()
            sys.exit(1)

    asyncio.run(_dashboard())


@cli.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "colored", "json"]),
    default="colored",
    help="Output format",
)
@click.option(
    "--level",
    type=click.Choice(["all", "warning", "critical"]),
    default="all",
    help="Alert level filter",
)
@click.pass_context
def alerts(ctx, output_format, level):
    """Display current alerts."""

    async def _alerts():
        config = ctx.obj["config"]
        threshold_monitor = ThresholdMonitor(config)

        try:
            # Get active alerts
            from .monitoring.alerts import AlertLevel

            level_filter = None
            if level == "warning":
                level_filter = AlertLevel.WARNING
            elif level == "critical":
                level_filter = AlertLevel.CRITICAL

            active_alerts = threshold_monitor.get_active_alerts(alert_level=level_filter)

            if output_format == "json":
                import json

                result = {
                    "active_alerts": len(active_alerts),
                    "alerts": [alert.to_dict() for alert in active_alerts],
                }
                click.echo(json.dumps(result, indent=2))
            else:
                format_config = AlertFormatConfig(use_colors=(output_format == "colored"))
                notifier = TextAlertNotifier(format_config=format_config)
                format_type = (
                    OutputFormat.TABLE if output_format == "table" else OutputFormat.COLORED
                )

                notifier.notify_multiple(active_alerts, format_type, include_summary=True)

        except Exception as e:
            click.echo(f"Alert retrieval failed: {e}", err=True)
            sys.exit(1)

    asyncio.run(_alerts())


@cli.command()
@click.pass_context
def test_auth(ctx):
    """Test authentication with all configured providers."""

    async def _test_auth():
        config = ctx.obj["config"]
        auth_manager = MultiCloudAuthManager()

        click.echo("Testing authentication for all providers...\n")

        for provider_name in ["aws", "azure", "gcp"]:
            if not config.is_provider_enabled(provider_name):
                click.echo(f"{provider_name.upper()}: Disabled")
                continue

            provider_config = config.get_provider_config(provider_name)

            try:
                auth_result = await auth_manager.authenticate_provider(
                    provider_name, provider_config
                )

                if auth_result.success:
                    click.echo(f"✅ {provider_name.upper()}: Authenticated ({auth_result.method})")

                    # Test connection
                    try:
                        provider = ProviderFactory.create_provider(provider_name, provider_config)
                        connection_ok = await provider.test_connection()
                        if connection_ok:
                            click.echo("   Connection test: ✅ Passed")
                        else:
                            click.echo("   Connection test: ❌ Failed")
                    except Exception as e:
                        click.echo(f"   Connection test: ❌ Error: {e}")

                else:
                    click.echo(f"❌ {provider_name.upper()}: Failed - {auth_result.error_message}")

            except Exception as e:
                click.echo(f"❌ {provider_name.upper()}: Error - {e}")

        click.echo("\nAuthentication summary:")
        summary = auth_manager.get_authentication_summary()
        for provider, status in summary.items():
            if status["authenticated"]:
                click.echo(f"  {provider.upper()}: ✅ Ready")
            else:
                click.echo(f"  {provider.upper()}: ❌ Not authenticated")

    asyncio.run(_test_auth())


@cli.command()
@click.pass_context
def config_info(ctx):
    """Display current configuration information."""
    config = ctx.obj["config"]

    click.echo("Multi-Cloud Cost Monitor Configuration")
    click.echo("=" * 40)

    # Enabled providers
    click.echo(f"Enabled Providers: {', '.join(config.enabled_providers) or 'None'}")

    # Global thresholds
    global_warning = config.get_threshold("warning")
    global_critical = config.get_threshold("critical")
    click.echo(
        f"Global Warning Threshold: ${global_warning:.2f}"
        if global_warning
        else "Global Warning Threshold: Not set"
    )
    click.echo(
        f"Global Critical Threshold: ${global_critical:.2f}"
        if global_critical
        else "Global Critical Threshold: Not set"
    )

    # Provider-specific settings
    click.echo("\nProvider-Specific Settings:")
    for provider in config.enabled_providers:
        click.echo(f"  {provider.upper()}:")
        provider_warning = config.get_threshold("warning", provider)
        provider_critical = config.get_threshold("critical", provider)

        if provider_warning:
            click.echo(f"    Warning Threshold: ${provider_warning:.2f}")
        if provider_critical:
            click.echo(f"    Critical Threshold: ${provider_critical:.2f}")

    # Dashboard settings
    dashboard_config = config.dashboard
    if dashboard_config.get("enabled", True):
        click.echo("\nDashboard: Enabled")
        click.echo(f"  Host: {dashboard_config.get('host', 'localhost')}")
        click.echo(f"  Port: {dashboard_config.get('port', 8050)}")
        click.echo(f"  Auto-refresh: {dashboard_config.get('auto_refresh', True)}")
    else:
        click.echo("\nDashboard: Disabled")

    # Cache settings
    cache_config = config.cache
    if cache_config.get("enabled", True):
        click.echo("\nCache: Enabled")
        click.echo(f"  TTL: {cache_config.get('ttl', 3600)} seconds")
        click.echo(f"  Type: {cache_config.get('type', 'memory')}")


@cli.command()
@click.confirmation_option(prompt="Are you sure you want to reload configuration?")
@click.pass_context
def reload(ctx):
    """Reload configuration from files."""
    try:
        config = reload_config()
        ctx.obj["config"] = config
        click.echo("✅ Configuration reloaded successfully")
    except Exception as e:
        click.echo(f"❌ Failed to reload configuration: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output", "-o", type=click.Path(), help="Output file for metrics (default: print to stdout)"
)
@click.option("--pushgateway-url", help="Prometheus Pushgateway URL to push metrics to")
@click.option(
    "--provider",
    type=click.Choice(["aws", "azure", "gcp", "all"]),
    default="all",
    help="Cloud provider to export (default: all)",
)
@click.option(
    "--days", "-d", type=int, default=7, help="Number of days of data to include (default: 7)"
)
@click.option("--currency", default="USD", help="Currency for cost display (default: USD)")
@click.option(
    "--job-name", default="cost_monitor", help="Prometheus job name (default: cost_monitor)"
)
@click.option(
    "--instance", default="cost_monitor", help="Prometheus instance name (default: cost_monitor)"
)
@click.pass_context
def export_prometheus(ctx, output, pushgateway_url, provider, days, currency, job_name, instance):
    """Export cost data as Prometheus metrics for batch processing."""

    async def _export_prometheus():
        try:
            from .export.prometheus import export_prometheus_metrics

            # Determine providers to export
            providers = None if provider == "all" else [provider]

            success = await export_prometheus_metrics(
                output_file=output,
                pushgateway_url=pushgateway_url,
                providers=providers,
                days_back=days,
                currency=currency,
                job_name=job_name,
                instance=instance,
            )

            if success:
                if output:
                    click.echo(f"✅ Prometheus metrics exported to: {output}")
                if pushgateway_url:
                    click.echo(f"✅ Metrics pushed to Pushgateway: {pushgateway_url}")
                if not output and not pushgateway_url:
                    # Metrics were printed to stdout
                    pass

                click.echo("\n📊 Export summary:")
                click.echo(f"  Providers: {provider}")
                click.echo(f"  Time range: {days} days")
                click.echo(f"  Currency: {currency}")

                if pushgateway_url:
                    click.echo("\n💡 Rundeck batch job setup:")
                    click.echo(
                        f"  Command: cost-monitor export-prometheus --pushgateway-url {pushgateway_url}"
                    )
                    click.echo("  Schedule: */15 * * * * (every 15 minutes)")

            else:
                click.echo("❌ Export failed. Check logs for details.", err=True)
                sys.exit(1)

        except Exception as e:
            click.echo(f"❌ Export error: {e}", err=True)
            sys.exit(1)

    asyncio.run(_export_prometheus())


@cli.command()
def version():
    """Display version information."""
    from . import __version__

    click.echo(f"Multi-Cloud Cost Monitor v{__version__}")
    click.echo("Monitor costs across AWS, Azure, and GCP")


if __name__ == "__main__":
    cli()
