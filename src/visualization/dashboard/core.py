"""
Core dashboard application and initialization.

Contains the main CostMonitorDashboard class with initialization,
layout setup, and helper methods.
"""

import asyncio
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from flask import Response, request

from .data_manager import CostDataManager
from .themes import DashboardTheme
from .utils import ChartMemoizer, DateRangeDebouncer, PerformanceMonitor

logger = logging.getLogger(__name__)

# Import availability checks
try:
    import dash
    import dash_bootstrap_components as dbc
    import plotly.graph_objects as go

    # Dashboard callback imports handled by specific callback modules

    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

# Import configuration classes
try:
    from src.config.settings import CloudConfig, get_config

    CONFIG_AVAILABLE = True
except ImportError:
    # Fallback for development
    CONFIG_AVAILABLE = False

    # Use a type alias to avoid assignment to imported name
    FallbackConfig = type(None)
    CloudConfig = FallbackConfig  # type: ignore

    def get_config() -> None:  # type: ignore[misc]
        return None


# Import threshold monitor
try:
    from src.monitoring.alerts import ThresholdMonitor

    MONITORING_AVAILABLE = True
except ImportError:
    # Fallback if monitoring not available
    MONITORING_AVAILABLE = False

    class ThresholdMonitor:  # type: ignore[no-redef]
        def __init__(self, config):
            pass


class CostMonitorDashboard:
    """Main dashboard application class."""

    def __init__(self, config: CloudConfig | None = None):
        logger.info("🏗️ Initializing CostMonitorDashboard...")
        if not DASH_AVAILABLE:
            raise ImportError(
                "Dash is required for the dashboard. Install with: pip install dash plotly"
            )

        logger.info("📝 Getting configuration...")
        self.config = config or get_config()
        self.data_manager = CostDataManager(self.config)
        self.threshold_monitor = ThresholdMonitor(self.config)
        self.date_debouncer = DateRangeDebouncer(delay=0.5)  # 500ms debounce
        self.current_data_task = None  # Track current data fetching task for cancellation
        self.chart_memoizer = ChartMemoizer(max_cache_size=5)  # Reduced cache for debugging
        self.performance_monitor = PerformanceMonitor()  # Performance monitoring

        # Dashboard configuration
        dashboard_config = self.config.dashboard
        self.host = dashboard_config.get("host", "0.0.0.0")
        self.port = dashboard_config.get("port", 8050)
        self.debug = dashboard_config.get("debug", False)
        self.auto_refresh = dashboard_config.get("auto_refresh", True)
        self.refresh_interval = (
            dashboard_config.get("refresh_interval", 300) * 1000
        )  # Convert to ms

        # Initialize Dash app
        logger.debug("Creating Dash app with styling...")
        # Use project root assets folder (not relative to this module)
        project_root = Path(__file__).resolve().parents[3]
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.DARKLY, dbc.icons.FONT_AWESOME],
            title="Multi-Cloud Cost Monitor",
            assets_folder=str(project_root / "assets"),
        )

        # Add custom CSS for spinner animation
        self.app.index_string = self._get_custom_css_template()

        logger.info("🎯 Dashboard initialized successfully")

        # Set up layout and callbacks
        self._setup_layout()
        self._setup_callbacks()
        self._setup_auth()

    def _setup_auth(self):
        """Set up Flask before_request hook for group-based authorization."""
        # Configure auth module from config if available
        try:
            from src.auth.openshift_groups import configure

            auth_config = getattr(self.config, "auth", None)
            if auth_config:
                configure(
                    allowed_groups=auth_config.get("allowed_groups", ""),
                    allowed_users=auth_config.get("allowed_users", ""),
                )
        except Exception:
            logger.debug("Auth config not available — using env var defaults")

        server = self.app.server  # Flask instance

        @server.before_request
        def check_authorization():
            """Check user authorization on every request."""
            # Skip auth for internal Dash paths and assets
            path = request.path
            if (
                path.startswith("/_dash-")
                or path.startswith("/assets/")
                or path.startswith("/_reload-hash")
                or path.startswith("/_favicon")
            ):
                return None

            user = request.headers.get("X-Forwarded-Email") or request.headers.get(
                "X-Forwarded-User"
            )

            # In local dev (no proxy headers), fall through gracefully
            import os

            if not user and not os.path.exists(
                "/var/run/secrets/kubernetes.io/serviceaccount/token"
            ):
                return None

            from src.auth.openshift_groups import check_user_allowed

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        allowed, reason = pool.submit(
                            lambda: asyncio.run(check_user_allowed(user))
                        ).result(timeout=10)
                else:
                    allowed, reason = loop.run_until_complete(check_user_allowed(user))
            except RuntimeError:
                allowed, reason = asyncio.run(check_user_allowed(user))

            if not allowed:
                logger.warning(
                    "Access denied for user=%s reason=%s path=%s",
                    user,
                    reason,
                    path,
                )
                return Response(
                    self._access_denied_html(user),
                    status=403,
                    content_type="text/html",
                )

            return None

    @staticmethod
    def _access_denied_html(user: str | None) -> str:
        """Return an access denied HTML page matching the dashboard theme."""
        display_user = user or "unknown"
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Access Denied - Cost Monitor</title>
    <style>
        body {{
            background-color: #1a1b26;
            color: #c0caf5;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }}
        .container {{
            text-align: center;
            max-width: 500px;
            padding: 2rem;
        }}
        .icon {{
            font-size: 4rem;
            margin-bottom: 1rem;
        }}
        h1 {{
            color: #f7768e;
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }}
        p {{
            color: #565f89;
            line-height: 1.6;
        }}
        .user {{
            color: #7aa2f7;
            font-family: monospace;
            background: #24283b;
            padding: 2px 8px;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">&#128274;</div>
        <h1>Access Denied</h1>
        <p>
            User <span class="user">{display_user}</span> is not authorized
            to access the Cost Monitor dashboard.
        </p>
        <p>
            Contact an administrator to request access.
            You need membership in an allowed OpenShift group.
        </p>
    </div>
</body>
</html>"""

    def _get_custom_css_template(self) -> str:
        """Get custom CSS template for the dashboard."""
        return """
        <!DOCTYPE html>
        <html>
            <head>
                {%metas%}
                <title>{%title%}</title>
                {%favicon%}
                {%css%}
                <style>
                :root {
                    --bg: #1a1b26;
                    --bg-surface: #24283b;
                    --bg-tool: #1e2030;
                    --text: #c0caf5;
                    --text-muted: #565f89;
                    --accent: #7aa2f7;
                    --accent-dim: #3d59a1;
                    --border: #3b4261;
                    --success: #9ece6a;
                    --error: #f7768e;
                    --warning: #e0af68;
                }
                body {
                    background-color: var(--bg) !important;
                    color: var(--text) !important;
                }
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
                .spinner-border {
                    animation: spin 1s linear infinite;
                }
                .chart-loading {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 200px;
                    font-size: 18px;
                    color: var(--text-muted);
                }
                .metric-card {
                    transition: transform 0.2s ease-in-out;
                }
                .metric-card:hover {
                    transform: translateY(-2px);
                }
                .container-fluid {
                    background-color: var(--bg) !important;
                }
                .card {
                    background-color: var(--bg-surface) !important;
                    border-color: var(--border) !important;
                    color: var(--text) !important;
                }
                .card-header {
                    background-color: var(--bg-tool) !important;
                    border-bottom-color: var(--border) !important;
                    color: var(--text) !important;
                }
                .card-body {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                }
                .text-primary {
                    color: var(--accent) !important;
                }
                .text-info {
                    color: #7dcfff !important;
                }
                .text-warning {
                    color: var(--warning) !important;
                }
                .text-danger {
                    color: var(--error) !important;
                }
                .text-success {
                    color: var(--success) !important;
                }
                .text-muted {
                    color: var(--text-muted) !important;
                }
                h1, h2, h3, h4, h5, h6 {
                    color: var(--text) !important;
                }
                .form-select, .form-control {
                    background-color: var(--bg-surface) !important;
                    border-color: var(--border) !important;
                    color: var(--text) !important;
                }
                .form-select:focus, .form-control:focus {
                    border-color: var(--accent) !important;
                    box-shadow: 0 0 0 0.2rem rgba(122, 162, 247, 0.25) !important;
                }
                .btn-outline-secondary {
                    color: var(--text-muted) !important;
                    border-color: var(--border) !important;
                }
                .btn-outline-secondary:hover {
                    background-color: var(--bg-tool) !important;
                    color: var(--text) !important;
                    border-color: var(--accent) !important;
                }
                .btn-primary {
                    background-color: var(--accent) !important;
                    border-color: var(--accent) !important;
                    color: var(--bg) !important;
                }
                .btn-primary:hover {
                    background-color: #89b4fa !important;
                    border-color: #89b4fa !important;
                }
                .btn-success {
                    background-color: var(--success) !important;
                    border-color: var(--success) !important;
                    color: var(--bg) !important;
                }
                .btn-warning {
                    background-color: var(--warning) !important;
                    border-color: var(--warning) !important;
                    color: var(--bg) !important;
                }
                .btn-info {
                    background-color: #7dcfff !important;
                    border-color: #7dcfff !important;
                    color: var(--bg) !important;
                }
                .btn-secondary {
                    background-color: var(--accent-dim) !important;
                    border-color: var(--border) !important;
                    color: var(--text) !important;
                }
                .alert-info {
                    background-color: rgba(122, 162, 247, 0.15) !important;
                    border-color: var(--accent-dim) !important;
                    color: var(--text) !important;
                }
                .alert-warning {
                    background-color: rgba(224, 175, 104, 0.15) !important;
                    border-color: var(--warning) !important;
                    color: var(--text) !important;
                }
                .alert-danger {
                    background-color: rgba(247, 118, 142, 0.15) !important;
                    border-color: var(--error) !important;
                    color: var(--text) !important;
                }
                .table {
                    color: var(--text) !important;
                    --bs-table-bg: var(--bg-surface);
                    --bs-table-striped-bg: var(--bg-tool);
                    --bs-table-hover-bg: var(--accent-dim);
                    --bs-table-border-color: var(--border);
                }
                .table thead th {
                    background-color: var(--bg) !important;
                    color: var(--accent) !important;
                    border-color: var(--border) !important;
                    font-weight: 600;
                }
                .table td, .table th {
                    border-color: var(--border) !important;
                }
                .dash-table-container .dash-spreadsheet-container {
                    background-color: var(--bg-surface) !important;
                }
                .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th,
                .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td {
                    color: var(--text) !important;
                }
                .form-check-input:checked {
                    background-color: var(--accent) !important;
                    border-color: var(--accent) !important;
                }
                .form-check-label {
                    color: var(--text) !important;
                }
                /* Dash date picker */
                .dash-datepicker-input-wrapper {
                    background-color: var(--bg-surface) !important;
                    border: 1px solid var(--border) !important;
                    border-radius: 6px !important;
                    padding: 4px 8px !important;
                }
                .dash-datepicker-input {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                    border: none !important;
                }
                .dash-datepicker-input:focus {
                    outline: none !important;
                    color: var(--accent) !important;
                }
                .dash-datepicker-range-arrow,
                .dash-datepicker-caret-icon {
                    color: var(--text-muted) !important;
                }
                /* Date picker calendar popup */
                [data-radix-popper-content-wrapper] {
                    z-index: 9999 !important;
                }
                .dash-datepicker-calendar {
                    background-color: var(--bg-surface) !important;
                    border: 1px solid var(--border) !important;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
                    color: var(--text) !important;
                }
                .dash-datepicker-calendar button {
                    color: var(--text) !important;
                }
                .dash-datepicker-calendar button:hover {
                    background-color: var(--accent-dim) !important;
                }
                .dash-datepicker-calendar [data-selected] {
                    background-color: var(--accent) !important;
                    color: var(--bg) !important;
                }
                .dash-datepicker-calendar [data-today] {
                    border-color: var(--accent) !important;
                }
                /* Plotly chart overrides */
                .js-plotly-plot .plotly .modebar {
                    background-color: transparent !important;
                }
                .js-plotly-plot .plotly .modebar-btn path {
                    fill: var(--text-muted) !important;
                }
                .js-plotly-plot .plotly .modebar-btn:hover path {
                    fill: var(--text) !important;
                }
                .js-plotly-plot .plotly .main-svg:first-child {
                    background-color: var(--bg) !important;
                }
                .js-plotly-plot .plotly .main-svg:not(:first-child) {
                    background-color: transparent !important;
                }
                /* Dash DataTable overrides */
                .dash-spreadsheet-container .dash-spreadsheet-inner input {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                    border-color: var(--border) !important;
                }
                .dash-spreadsheet-container .previous-next-container {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                }
                .dash-spreadsheet-container .previous-next-container button {
                    color: var(--text) !important;
                }
                .dash-spreadsheet-container .current-page-container {
                    color: var(--text) !important;
                }
                .dash-spreadsheet-container .page-number {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                    border-color: var(--border) !important;
                }
                /* Catch-all for any remaining white backgrounds */
                .Select-control, .Select-menu-outer {
                    background-color: var(--bg-surface) !important;
                    border-color: var(--border) !important;
                    color: var(--text) !important;
                }
                .Select-value-label, .Select-placeholder {
                    color: var(--text) !important;
                }
                input, select, textarea {
                    background-color: var(--bg-surface) !important;
                    color: var(--text) !important;
                    border-color: var(--border) !important;
                }
                a {
                    color: var(--accent);
                }
                a:hover {
                    color: #89b4fa;
                }
                ::-webkit-scrollbar {
                    width: 6px;
                }
                ::-webkit-scrollbar-track {
                    background: transparent;
                }
                ::-webkit-scrollbar-thumb {
                    background: var(--border);
                    border-radius: 3px;
                }
                ::-webkit-scrollbar-thumb:hover {
                    background: var(--text-muted);
                }
                </style>
            </head>
            <body>
                {%app_entry%}
                <footer>
                    {%config%}
                    {%scripts%}
                    {%renderer%}
                </footer>
            </body>
        </html>
        """

    # Date helper methods
    def _get_month_start(self, target_date: date | None = None) -> date:
        """Get the first day of the month for the given date (or today)."""
        if target_date is None:
            target_date = date.today()
        return target_date.replace(day=1)

    # Removed _get_month_end helper method since we now use today directly for "This Month"

    def _get_last_month_range(self) -> tuple[date, date]:
        """Get the first and last day of last month."""
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        return first_day_last_month, last_day_last_month

    def _get_last_month(self) -> tuple[date, date]:
        """Get the first and last day of last month (alias for _get_last_month_range)."""
        return self._get_last_month_range()

    def _get_week_start(self, target_date: date | None = None) -> date:
        """Get the start of the week (Monday) for the given date (or today)."""
        if target_date is None:
            target_date = date.today()
        # weekday() returns 0 for Monday, 6 for Sunday
        days_since_monday = target_date.weekday()
        return target_date - timedelta(days=days_since_monday)

    def _get_last_week_range(self) -> tuple[date, date]:
        """Get the start and end of last week (Monday to Sunday)."""
        today = date.today()
        this_week_start = self._get_week_start(today)
        last_week_end = this_week_start - timedelta(days=1)  # Sunday of last week
        last_week_start = self._get_week_start(last_week_end)  # Monday of last week
        return last_week_start, last_week_end

    def _get_last_week(self) -> tuple[date, date]:
        """Get the start and end of last week (alias for _get_last_week_range)."""
        return self._get_last_week_range()

    def _format_currency_compact(self, value: float) -> str:
        """Format currency values with K/M suffixes for large numbers."""
        if value >= 1_000_000:
            return f"${value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value/1_000:.1f}K"
        else:
            return f"${value:.2f}"

    def _create_initial_loading_chart(self, title: str):
        """Create a loading chart placeholder."""
        loading_fig = go.Figure()
        loading_fig.add_annotation(
            text="Loading data...",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            xanchor="center",
            yanchor="middle",
            showarrow=False,
            font=dict(size=16, color=DashboardTheme.COLORS["text_muted"]),
        )
        loading_fig.update_layout(
            title=title,
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            **DashboardTheme.LAYOUT,
        )
        return loading_fig

    def _setup_layout(self):
        """Set up the dashboard layout."""
        # Layout will be extracted to layout.py module
        from .layout import create_dashboard_layout

        self.app.layout = create_dashboard_layout(self)

    def _setup_callbacks(self):
        """Set up all dashboard callbacks."""
        # Import and setup callback modules
        from .callbacks.aws_breakdown import setup_aws_breakdown_callbacks
        from .callbacks.charts import setup_chart_callbacks
        from .callbacks.data_store import setup_data_store_callbacks
        from .callbacks.interactions import setup_interaction_callbacks
        from .callbacks.tables import setup_table_callbacks

        # Setup callback modules
        setup_data_store_callbacks(self)
        setup_chart_callbacks(self)
        setup_interaction_callbacks(self)
        setup_table_callbacks(self)
        setup_aws_breakdown_callbacks(self)

    async def run(self):
        """Start the dashboard server."""
        try:
            # Initialize data manager
            init_start = time.time()
            await self.data_manager.initialize()
            init_time = time.time() - init_start

            print(f"✅ Data manager initialized in {init_time:.3f}s")
            print(f"🚀 Starting dashboard on {self.host}:{self.port}")

            # Use app.run instead of run_server for newer Dash versions
            self.app.run(host=self.host, port=self.port, debug=self.debug)

        except Exception as e:
            logger.error(f"Failed to start dashboard: {e}")
            raise
