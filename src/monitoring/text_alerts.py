"""
Text-based alert functionality for multi-cloud cost monitoring.

Provides console output, text formatting, and notification capabilities
for cost threshold alerts and warnings.
"""

import logging
import sys
from enum import Enum
from typing import Any, TextIO

from pydantic import BaseModel, Field, field_validator

from .alerts import Alert, AlertLevel

logger = logging.getLogger(__name__)


class OutputFormat(Enum):
    """Supported output formats for alerts."""

    PLAIN = "plain"
    COLORED = "colored"
    JSON = "json"
    TABLE = "table"
    MARKDOWN = "markdown"


class Color:
    """ANSI color codes for terminal output."""

    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"  # Reset color

    @classmethod
    def disable(cls):
        """Disable color output."""
        cls.RED = ""
        cls.YELLOW = ""
        cls.GREEN = ""
        cls.BLUE = ""
        cls.CYAN = ""
        cls.WHITE = ""
        cls.BOLD = ""
        cls.UNDERLINE = ""
        cls.END = ""


class AlertFormatConfig(BaseModel):
    """Configuration for alert formatting with validation."""

    show_timestamp: bool = Field(True, description="Whether to show timestamp in alerts")
    show_provider: bool = Field(True, description="Whether to show provider in alerts")
    show_details: bool = Field(True, description="Whether to show detailed alert information")
    use_colors: bool = Field(True, description="Whether to use colors in output")
    max_message_length: int | None = Field(
        None, gt=0, le=10000, description="Maximum message length"
    )
    include_metadata: bool = Field(False, description="Whether to include alert metadata")

    @field_validator("max_message_length")
    @classmethod
    def validate_max_message_length(cls, v: int | None) -> int | None:
        """Validate maximum message length."""
        if v is None:
            return v

        if v <= 0:
            raise ValueError("Maximum message length must be positive")

        # Set reasonable bounds
        if v < 10:
            raise ValueError("Maximum message length too small (minimum 10 characters)")

        if v > 10000:
            raise ValueError("Maximum message length too large (maximum 10000 characters)")

        return v

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class TextAlertFormatter:
    """Formats alerts for text-based output."""

    def __init__(self, config: AlertFormatConfig | None = None):
        self.config = config or AlertFormatConfig(
            show_timestamp=True,
            show_provider=True,
            show_details=True,
            use_colors=True,
            max_message_length=None,
            include_metadata=False,
        )

        # Disable colors if not supported or requested
        if not self.config.use_colors or not self._supports_color():
            Color.disable()

        # Alert level symbols and colors
        self.level_config = {
            AlertLevel.INFO: {"symbol": "ℹ", "color": Color.BLUE, "prefix": "INFO"},
            AlertLevel.WARNING: {"symbol": "⚠", "color": Color.YELLOW, "prefix": "WARNING"},
            AlertLevel.CRITICAL: {"symbol": "🚨", "color": Color.RED, "prefix": "CRITICAL"},
        }

    def _supports_color(self) -> bool:
        """Check if the terminal supports color output."""
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def format_alert(self, alert: Alert, format_type: OutputFormat = OutputFormat.COLORED) -> str:
        """
        Format an alert for text output.

        Args:
            alert: Alert to format
            format_type: Output format type

        Returns:
            Formatted alert string
        """
        if format_type == OutputFormat.JSON:
            import json

            return json.dumps(alert.to_dict(), indent=2)
        elif format_type == OutputFormat.MARKDOWN:
            return self._format_markdown(alert)
        elif format_type == OutputFormat.TABLE:
            return self._format_table_row(alert)
        else:
            return self._format_text(alert, format_type == OutputFormat.COLORED)

    def _format_timestamp(self, alert: Alert, use_colors: bool) -> str | None:
        """Format timestamp part if enabled."""
        if not self.config.show_timestamp:
            return None

        timestamp = alert.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if use_colors:
            return f"{Color.CYAN}{timestamp}{Color.END}"
        return timestamp

    def _format_level(self, alert: Alert, use_colors: bool) -> str:
        """Format alert level with symbol and color."""
        level_config = self.level_config[alert.alert_level]

        if use_colors:
            return f"{level_config['color']}{level_config['symbol']} {level_config['prefix']}{Color.END}"
        return f"[{level_config['prefix']}]"

    def _format_provider(self, alert: Alert, use_colors: bool) -> str | None:
        """Format provider part if enabled."""
        if not (self.config.show_provider and alert.provider):
            return None

        provider_text = alert.provider.upper()
        if use_colors:
            return f"{Color.BOLD}{provider_text}{Color.END}"
        return f"[{provider_text}]"

    def _format_message(self, alert: Alert, use_colors: bool) -> str:
        """Format main alert message."""
        message = alert.message

        if self.config.max_message_length and len(message) > self.config.max_message_length:
            message = message[: self.config.max_message_length - 3] + "..."

        if use_colors and alert.alert_level == AlertLevel.CRITICAL:
            message = f"{Color.BOLD}{message}{Color.END}"

        return message

    def _format_details(self, alert: Alert, use_colors: bool) -> str | None:
        """Format details part if enabled."""
        if not self.config.show_details:
            return None

        details = [
            f"Current: ${alert.current_value:.2f}",
            f"Threshold: ${alert.threshold_value:.2f}",
        ]

        if use_colors:
            return f"{Color.WHITE}({', '.join(details)}){Color.END}"
        return f"({', '.join(details)})"

    def _format_metadata(self, alert: Alert, use_colors: bool) -> str | None:
        """Format metadata part if enabled."""
        if not (self.config.include_metadata and alert.metadata):
            return None

        metadata_items = []
        for key, value in alert.metadata.items():
            if key == "threshold_exceeded_by":
                metadata_items.append(f"Exceeded by: ${value:.2f}")
            elif key == "provider_breakdown":
                breakdown = ", ".join([f"{k}: ${v:.2f}" for k, v in value.items()])
                metadata_items.append(f"Breakdown: {breakdown}")

        if not metadata_items:
            return None

        if use_colors:
            return f"{Color.CYAN}[{'; '.join(metadata_items)}]{Color.END}"
        return f"[{'; '.join(metadata_items)}]"

    def _format_text(self, alert: Alert, use_colors: bool = True) -> str:
        """Format alert as colored text."""
        parts = []

        # Add each part if it exists
        for format_method in [
            self._format_timestamp,
            self._format_level,
            self._format_provider,
            self._format_message,
            self._format_details,
            self._format_metadata,
        ]:
            formatted_part = format_method(alert, use_colors)
            if formatted_part:
                parts.append(formatted_part)

        return " ".join(parts)

    def _format_markdown(self, alert: Alert) -> str:
        """Format alert as Markdown."""
        level_emoji = {AlertLevel.INFO: "ℹ️", AlertLevel.WARNING: "⚠️", AlertLevel.CRITICAL: "🚨"}

        lines = []
        lines.append(
            f"## {level_emoji.get(alert.alert_level, '')} {alert.alert_level.value.title()} Alert"
        )
        lines.append("")
        lines.append(f"**Provider:** {alert.provider.upper()}")
        lines.append(f"**Message:** {alert.message}")
        lines.append(f"**Current Cost:** ${alert.current_value:.2f} {alert.currency}")
        lines.append(f"**Threshold:** ${alert.threshold_value:.2f} {alert.currency}")
        lines.append(f"**Time:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

        if alert.metadata:
            lines.append("")
            lines.append("**Details:**")
            for key, value in alert.metadata.items():
                if key == "threshold_exceeded_by":
                    lines.append(f"- Exceeded by: ${value:.2f}")
                elif key == "provider_breakdown":
                    lines.append("- Provider breakdown:")
                    for provider, cost in value.items():
                        lines.append(f"  - {provider}: ${cost:.2f}")

        return "\n".join(lines)

    def _format_table_row(self, alert: Alert) -> str:
        """Format alert as a table row."""
        return f"{alert.timestamp.strftime('%H:%M:%S'):<10} {alert.alert_level.value.upper():<8} {alert.provider.upper():<10} ${alert.current_value:<8.2f} ${alert.threshold_value:<8.2f} {alert.message}"

    def format_alert_list(
        self,
        alerts: list[Alert],
        format_type: OutputFormat = OutputFormat.COLORED,
        sort_by: str = "timestamp",
    ) -> str:
        """
        Format a list of alerts.

        Args:
            alerts: List of alerts to format
            format_type: Output format type
            sort_by: Field to sort by (timestamp, level, provider)

        Returns:
            Formatted alerts string
        """
        if not alerts:
            return "No alerts to display."

        # Sort alerts
        if sort_by == "level":
            alerts.sort(key=lambda a: (a.alert_level.value, a.timestamp), reverse=True)
        elif sort_by == "provider":
            alerts.sort(key=lambda a: (a.provider, a.timestamp))
        else:  # timestamp
            alerts.sort(key=lambda a: a.timestamp, reverse=True)

        if format_type == OutputFormat.TABLE:
            return self._format_table(alerts)
        elif format_type == OutputFormat.JSON:
            import json

            return json.dumps([alert.to_dict() for alert in alerts], indent=2)
        else:
            formatted_alerts = []
            for alert in alerts:
                formatted_alerts.append(self.format_alert(alert, format_type))
            return "\n".join(formatted_alerts)

    def _format_table(self, alerts: list[Alert]) -> str:
        """Format alerts as a table."""
        lines = []

        # Header
        header = (
            f"{'TIME':<10} {'LEVEL':<8} {'PROVIDER':<10} {'CURRENT':<8} {'THRESHOLD':<8} MESSAGE"
        )
        lines.append(header)
        lines.append("-" * len(header))

        # Rows
        for alert in alerts:
            lines.append(self._format_table_row(alert))

        return "\n".join(lines)

    def format_summary(self, alerts: list[Alert]) -> str:
        """Format a summary of alerts."""
        if not alerts:
            return f"{Color.GREEN}✓ No active alerts{Color.END}"

        total = len(alerts)
        critical = len([a for a in alerts if a.alert_level == AlertLevel.CRITICAL])
        warning = len([a for a in alerts if a.alert_level == AlertLevel.WARNING])
        info = len([a for a in alerts if a.alert_level == AlertLevel.INFO])

        summary_parts = []

        if critical > 0:
            summary_parts.append(f"{Color.RED}{critical} Critical{Color.END}")
        if warning > 0:
            summary_parts.append(f"{Color.YELLOW}{warning} Warning{Color.END}")
        if info > 0:
            summary_parts.append(f"{Color.BLUE}{info} Info{Color.END}")

        if summary_parts:
            return f"🚨 {total} Alert{'s' if total != 1 else ''}: {', '.join(summary_parts)}"
        else:
            return f"{Color.GREEN}✓ No alerts{Color.END}"


class TextAlertNotifier:
    """Handles text-based alert notifications."""

    def __init__(
        self,
        output_stream: TextIO | None = None,
        format_config: AlertFormatConfig | None = None,
    ):
        self.output_stream = output_stream or sys.stdout
        self.formatter = TextAlertFormatter(format_config)

    def notify(self, alert: Alert, format_type: OutputFormat = OutputFormat.COLORED):
        """Send a text notification for an alert."""
        formatted_alert = self.formatter.format_alert(alert, format_type)
        self.output_stream.write(formatted_alert + "\n")
        self.output_stream.flush()

    def notify_multiple(
        self,
        alerts: list[Alert],
        format_type: OutputFormat = OutputFormat.COLORED,
        include_summary: bool = True,
    ):
        """Send notifications for multiple alerts."""
        if not alerts:
            if include_summary:
                summary = self.formatter.format_summary(alerts)
                self.output_stream.write(summary + "\n")
            return

        if include_summary:
            summary = self.formatter.format_summary(alerts)
            self.output_stream.write(summary + "\n\n")

        formatted_alerts = self.formatter.format_alert_list(alerts, format_type)
        self.output_stream.write(formatted_alerts + "\n")
        self.output_stream.flush()

    def display_cost_status(
        self,
        provider_costs: dict[str, float],
        thresholds: dict[str, dict[str, float]],
        currency: str = "USD",
    ):
        """Display current cost status against thresholds."""
        lines = []
        lines.append(f"{Color.BOLD}Current Cost Status{Color.END}")
        lines.append("=" * 50)

        for provider, current_cost in provider_costs.items():
            provider_thresholds = thresholds.get(provider, {})

            # Determine status
            critical_threshold = provider_thresholds.get("critical")
            warning_threshold = provider_thresholds.get("warning")

            status_color = Color.GREEN
            status_text = "OK"

            if critical_threshold and current_cost >= critical_threshold:
                status_color = Color.RED
                status_text = "CRITICAL"
            elif warning_threshold and current_cost >= warning_threshold:
                status_color = Color.YELLOW
                status_text = "WARNING"

            # Format line
            provider_text = f"{Color.BOLD}{provider.upper():<8}{Color.END}"
            cost_text = f"${current_cost:>8.2f} {currency}"
            status_display = f"{status_color}{status_text:>8}{Color.END}"

            line = f"{provider_text} {cost_text} {status_display}"

            # Add threshold information
            if warning_threshold or critical_threshold:
                threshold_info = []
                if warning_threshold:
                    threshold_info.append(f"Warn: ${warning_threshold:.0f}")
                if critical_threshold:
                    threshold_info.append(f"Crit: ${critical_threshold:.0f}")

                threshold_text = f" ({', '.join(threshold_info)})"
                line += f"{Color.CYAN}{threshold_text}{Color.END}"

            lines.append(line)

        # Total cost
        total_cost = sum(provider_costs.values())
        lines.append("-" * 50)
        lines.append(f"{Color.BOLD}TOTAL{Color.END}     ${total_cost:>8.2f} {currency}")

        self.output_stream.write("\n".join(lines) + "\n")
        self.output_stream.flush()


class ConsoleAlertHandler:
    """Handles console-based alert display and interaction."""

    def __init__(
        self, format_config: AlertFormatConfig | None = None, auto_acknowledge: bool = False
    ):
        self.notifier = TextAlertNotifier(format_config=format_config)
        self.auto_acknowledge = auto_acknowledge

    def handle_alert(self, alert: Alert):
        """Handle a single alert."""
        self.notifier.notify(alert)

        if self.auto_acknowledge:
            print(f"{Color.CYAN}Alert automatically acknowledged{Color.END}")
        else:
            # Interactive acknowledgment (if running in interactive mode)
            if sys.stdin.isatty():
                try:
                    response = input("\nAcknowledge this alert? [y/N]: ").lower()
                    if response in ["y", "yes"]:
                        alert.acknowledged = True
                        print(f"{Color.GREEN}Alert acknowledged{Color.END}")
                except (KeyboardInterrupt, EOFError):
                    pass

    def handle_alerts(self, alerts: list[Alert]):
        """Handle multiple alerts."""
        if not alerts:
            self.notifier.notify_multiple(alerts)
            return

        self.notifier.notify_multiple(alerts, include_summary=True)

        if not self.auto_acknowledge and sys.stdin.isatty():
            try:
                response = input("\nAcknowledge all alerts? [y/N]: ").lower()
                if response in ["y", "yes"]:
                    for alert in alerts:
                        alert.acknowledged = True
                    print(f"{Color.GREEN}All alerts acknowledged{Color.END}")
            except (KeyboardInterrupt, EOFError):
                pass

    def display_interactive_menu(self, alerts: list[Alert]):
        """Display an interactive menu for managing alerts."""
        while True:
            print(f"\n{Color.BOLD}Alert Management Menu{Color.END}")
            print("1. View all alerts")
            print("2. View critical alerts only")
            print("3. Acknowledge all alerts")
            print("4. Clear resolved alerts")
            print("5. Exit")

            try:
                choice = input("\nSelect option [1-5]: ").strip()

                if choice == "1":
                    self.notifier.notify_multiple(alerts, OutputFormat.TABLE)
                elif choice == "2":
                    critical_alerts = [a for a in alerts if a.alert_level == AlertLevel.CRITICAL]
                    self.notifier.notify_multiple(critical_alerts, OutputFormat.TABLE)
                elif choice == "3":
                    for alert in alerts:
                        alert.acknowledged = True
                    print(f"{Color.GREEN}All alerts acknowledged{Color.END}")
                elif choice == "4":
                    resolved_count = len([a for a in alerts if a.resolved])
                    alerts[:] = [a for a in alerts if not a.resolved]  # Remove resolved alerts
                    print(f"{Color.GREEN}Cleared {resolved_count} resolved alerts{Color.END}")
                elif choice == "5":
                    break
                else:
                    print(f"{Color.YELLOW}Invalid choice. Please select 1-5.{Color.END}")

            except (KeyboardInterrupt, EOFError):
                print(f"\n{Color.CYAN}Exiting...{Color.END}")
                break
