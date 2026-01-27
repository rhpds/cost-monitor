"""
Core dashboard application and initialization.

Contains the main CostMonitorDashboard class with initialization,
layout setup, and helper methods.
"""

import logging
import time
from datetime import date, timedelta

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
        logger.debug("🚀 DEBUG: Creating Dash app with styling...")
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
            title="Multi-Cloud Cost Monitor",
            assets_folder="assets",
        )

        # Add custom CSS for spinner animation
        self.app.index_string = self._get_custom_css_template()

        logger.info("🎯 Dashboard initialized successfully")

        # Set up layout and callbacks
        self._setup_layout()
        self._setup_callbacks()

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
                    color: #6c757d;
                }
                .metric-card {
                    transition: transform 0.2s ease-in-out;
                }
                .metric-card:hover {
                    transform: translateY(-2px);
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
            font=dict(size=16, color="gray"),
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
        from .callbacks.charts import setup_chart_callbacks
        from .callbacks.data_store import setup_data_store_callbacks
        from .callbacks.interactions import setup_interaction_callbacks
        from .callbacks.tables import setup_table_callbacks

        # Setup callback modules
        setup_data_store_callbacks(self)
        setup_chart_callbacks(self)
        setup_interaction_callbacks(self)
        setup_table_callbacks(self)

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
