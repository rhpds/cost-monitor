"""
Interactive Plotly dashboard for multi-cloud cost monitoring.

Provides a web-based dashboard with real-time cost visualization,
multi-cloud comparison, and interactive analysis capabilities.
"""

import logging
import asyncio
import time
import os
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)
logger.info("🚀 Dashboard module starting to load...")


class DataWrapper:
    """Simple wrapper to provide attribute access to dictionary data for compatibility."""
    def __init__(self, data_dict):
        for key, value in data_dict.items():
            setattr(self, key, value)

try:
    import dash
    from dash import dcc, html, Input, Output, State, callback, dash_table, ALL
    import dash_bootstrap_components as dbc
    import plotly.graph_objects as go
    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

import requests
import json

# Import configuration classes
try:
    from src.config.settings import CloudConfig, get_config
except ImportError:
    # Fallback for development
    CloudConfig = None
    get_config = lambda: None

# Import threshold monitor
try:
    from src.monitoring.alerts import ThresholdMonitor
except ImportError:
    # Fallback if monitoring not available
    class ThresholdMonitor:
        def __init__(self, config): pass

# Export functionality replaced with static JSON template
EXPORT_AVAILABLE = False

logger = logging.getLogger(__name__)


class DateRangeDebouncer:
    """Simple debouncer for date range changes to improve performance."""

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.last_change_time = 0

    def should_process(self) -> bool:
        """Check if enough time has passed since last change."""
        current_time = time.time()
        if current_time - self.last_change_time >= self.delay:
            self.last_change_time = current_time
            return True
        return False


class ChartMemoizer:
    """Simple chart memoization helper for performance optimization."""

    def __init__(self, max_cache_size: int = 50):
        self.cache = {}
        self.access_times = {}
        self.max_size = max_cache_size

    def get_cache_key(self, data, params) -> str:
        """Generate cache key from data and parameters."""
        import hashlib
        import json
        key_data = {
            'data_hash': hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest() if data else 'empty',
            'params': params
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

    def get(self, cache_key):
        """Get cached figure if it exists."""
        if cache_key in self.cache:
            self.access_times[cache_key] = time.time()
            return self.cache[cache_key]
        return None

    def set(self, cache_key, figure):
        """Set cached figure, evicting oldest if necessary."""
        if len(self.cache) >= self.max_size:
            # Remove oldest cache entry
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]

        self.cache[cache_key] = figure
        self.access_times[cache_key] = time.time()


class PerformanceMonitor:
    """Simple performance monitoring for dashboard operations."""

    def __init__(self):
        self.metrics = {}
        self.operation_times = {}

    def start_operation(self, operation_name: str):
        """Start timing an operation."""
        self.operation_times[operation_name] = time.time()

    def end_operation(self, operation_name: str, breakdown: Dict[str, float] = None):
        """End timing an operation and log the result with optional breakdown."""
        if operation_name in self.operation_times:
            duration = time.time() - self.operation_times[operation_name]

            if operation_name not in self.metrics:
                self.metrics[operation_name] = []

            self.metrics[operation_name].append(duration)

            # Keep only last 10 measurements per operation
            if len(self.metrics[operation_name]) > 10:
                self.metrics[operation_name] = self.metrics[operation_name][-10:]

            avg_time = sum(self.metrics[operation_name]) / len(self.metrics[operation_name])

            # Log performance info
            logger.info(f"⚡ Performance: {operation_name} took {duration:.3f}s (avg: {avg_time:.3f}s)")

            # Warn if operation is slow with breakdown details
            if duration > 2.0:
                breakdown_str = ""
                if breakdown:
                    breakdown_parts = [f"{k}:{v:.3f}s" for k, v in breakdown.items()]
                    breakdown_str = f" [Breakdown: {', '.join(breakdown_parts)}]"
                logger.warning(f"🐌 Slow operation detected: {operation_name} took {duration:.3f}s{breakdown_str}")

            del self.operation_times[operation_name]

    def get_stats(self):
        """Get current performance statistics."""
        stats = {}
        for operation, times in self.metrics.items():
            stats[operation] = {
                'count': len(times),
                'avg_time': sum(times) / len(times),
                'last_time': times[-1] if times else 0,
                'max_time': max(times) if times else 0
            }
        return stats


class DashboardTheme:
    """Dashboard theme configuration."""

    COLORS = {
        'primary': '#2E86AB',
        'secondary': '#A23B72',
        'success': '#F18F01',
        'warning': '#C73E1D',
        'danger': '#C73E1D',
        'info': '#17A2B8',
        'light': '#F8F9FA',
        'dark': '#343A40',
        'aws': '#FF9900',
        'azure': '#0078D4',
        'gcp': '#34A853',
        'background': '#FFFFFF',
        'surface': '#F8F9FA',
        'text': '#212529'
    }

    LAYOUT = {
        'margin': {'l': 20, 'r': 20, 't': 40, 'b': 20},
        'font_family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'font_size': 12
    }


class CostDataManager:
    """Manages cost data retrieval from the data service API with Redis caching."""

    def __init__(self, config=None):
        self.data_service_url = os.getenv('DATA_SERVICE_URL', 'http://cost-data-service:8000')
        self._dashboard_cache = None
        self._last_fetch_times = {}  # Track last fetch times per cache key

        # Initialize Redis cache for dashboard-level caching
        try:
            from src.utils.cache import RedisCache
            self._dashboard_cache = RedisCache(
                default_ttl=60,  # Short TTL for dashboard cache (1 minute)
                prefix='cost-monitor:dashboard:'
            )
            logger.info(f"Dashboard Redis cache initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize dashboard Redis cache: {e}")
            self._dashboard_cache = None

        logger.info(f"CostDataManager initialized for API mode, using data service at: {self.data_service_url}")

    async def initialize(self):
        """Initialize the data manager for API mode."""
        logger.info("Data manager initialized for API mode")
        return True

    def _get_cache_key(self, start_date: date, end_date: date, force_refresh: bool = False) -> str:
        """Generate cache key for the request."""
        return f"cost_data:{start_date}:{end_date}:{force_refresh}"


    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        force_refresh: bool = False
    ) -> Optional[dict]:
        """Get cost data from data service API with Redis caching."""
        cache_key = self._get_cache_key(start_date, end_date, force_refresh)
        current_time = time.time()

        # Check dashboard Redis cache first (unless force_refresh)
        if not force_refresh and self._dashboard_cache:
            try:
                cached_data = self._dashboard_cache.get(cache_key)
                if cached_data:
                    logger.info(f"Dashboard cache HIT for {start_date} to {end_date}")
                    return cached_data
            except Exception as e:
                logger.warning(f"Dashboard cache get failed: {e}")

        # Check if we've fetched this data very recently (prevent rapid duplicate calls)
        last_fetch = self._last_fetch_times.get(cache_key, 0)
        if current_time - last_fetch < 5:  # 5 second cooldown
            logger.warning(f"Rate limiting API call for {start_date} to {end_date} (last fetch {current_time - last_fetch:.1f}s ago)")
            return None

        logger.info(f"Fetching cost data from API for {start_date} to {end_date} (force_refresh={force_refresh})")
        self._last_fetch_times[cache_key] = current_time

        try:
            # Call data service API - now returns data in dashboard format
            url = f"{self.data_service_url}/api/v1/costs/summary"
            params = {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'providers': ['aws', 'azure', 'gcp'],
                'force_refresh': force_refresh  # Pass force_refresh to API
            }

            # Calculate appropriate timeout based on date range
            date_range_days = (end_date - start_date).days + 1 if start_date and end_date else 1
            if date_range_days > 7:
                # Long operations need more time for account collection
                api_timeout = min(600, 60 + (date_range_days * 5))  # Max 10 minutes, ~5 seconds per day
                logger.info(f"📊 Using extended timeout {api_timeout}s for {date_range_days}-day range")
            else:
                api_timeout = 30  # Standard timeout for short ranges

            response = requests.get(url, params=params, timeout=api_timeout)
            response.raise_for_status()

            # API now returns data in the exact format dashboard expects
            api_data = response.json()

            # Cache the API response in Redis for dashboard-level caching
            if self._dashboard_cache:
                try:
                    self._dashboard_cache.set(cache_key, api_data)
                    logger.debug(f"Cached dashboard data for {start_date} to {end_date}")
                except Exception as e:
                    logger.warning(f"Failed to cache dashboard data: {e}")

            logger.info(f"Retrieved cost data from API, total: ${api_data['total_cost']:.2f}")
            return DataWrapper(api_data)

        except Exception as e:
            logger.error(f"Failed to get cost data from API: {e}")
            # Return a proper empty DataWrapper instead of None to prevent attribute errors
            empty_data = {
                'total_cost': 0.0,
                'currency': 'USD',
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'provider_breakdown': {},
                'combined_daily_costs': [],
                'provider_data': {},
                'account_breakdown': {}
            }
            return DataWrapper(empty_data)


    async def initialize(self):
        """Initialize the data manager."""
        logger.info("Data manager initialized for API mode")
        return True


    async def get_service_breakdown(
        self,
        provider: str,
        start_date: date,
        end_date: date,
        top_n: int = 10
    ) -> Dict[str, float]:
        """Get service cost breakdown for a specific provider from API."""
        try:
            url = f"{self.data_service_url}/api/v1/costs"
            params = {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'providers': [provider]
            }

            # Calculate appropriate timeout based on date range
            date_range_days = (end_date - start_date).days + 1 if start_date and end_date else 1
            if date_range_days > 7:
                # Long operations need more time for data collection
                api_timeout = min(600, 60 + (date_range_days * 5))  # Max 10 minutes, ~5 seconds per day
                logger.info(f"📊 Service breakdown using extended timeout {api_timeout}s for {date_range_days}-day range")
            else:
                api_timeout = 30  # Standard timeout for short ranges

            response = requests.get(url, params=params, timeout=api_timeout)
            response.raise_for_status()

            detailed_data = response.json()
            service_costs = {}

            for item in detailed_data:
                if item.get('provider') == provider:
                    service = item.get('service_name', 'Unknown')
                    cost = item.get('cost', 0)
                    service_costs[service] = service_costs.get(service, 0) + cost

            # Return top N services
            sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[:top_n]
            return dict(sorted_services)

        except Exception as e:
            logger.error(f"Failed to get service breakdown for {provider}: {e}")
            return {}

    async def get_account_breakdown_data(
        self,
        start_date: date,
        end_date: date,
        force_refresh: bool = False
    ) -> Optional[dict]:
        """Get account breakdown data from API."""
        logger.info(f"Fetching account breakdown data for {start_date} to {end_date}")

        # Use the same data as regular cost data, process for account breakdown
        cost_data = await self.get_cost_data(start_date, end_date, force_refresh)
        if cost_data:
            return getattr(cost_data, 'account_breakdown', {})
        return {}






class CostMonitorDashboard:
    """Main dashboard application class."""

    def __init__(self, config):

        logger.info("🏗️ Initializing CostMonitorDashboard...")
        if not DASH_AVAILABLE:
            raise ImportError("Dash is required for the dashboard. Install with: pip install dash plotly")

        logger.info("📝 Getting configuration...")
        from src.config.settings import get_config
        self.config = config or get_config()
        self.data_manager = CostDataManager(self.config)

        logger.info("✅ Dashboard initialization complete")

    def create_app(self):
        """Create Dash app (placeholder method)."""
        pass

# End of broken class - real class follows below

# The real CostMonitorDashboard class follows below

class CostMonitorDashboard:
    """Main dashboard application class."""

    def __init__(self, config=None):
        """Initialize dashboard (placeholder)."""
        pass


# Real CostMonitorDashboard class below



class CostMonitorDashboard:
    """Main dashboard application class."""

    def __init__(self, config: CloudConfig = None):
        logger.info("🏗️ Initializing CostMonitorDashboard...")
        if not DASH_AVAILABLE:
            raise ImportError("Dash is required for the dashboard. Install with: pip install dash plotly")

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
        self.host = dashboard_config.get('host', '0.0.0.0')
        self.port = dashboard_config.get('port', 8050)
        self.debug = dashboard_config.get('debug', False)
        self.auto_refresh = dashboard_config.get('auto_refresh', True)
        self.refresh_interval = dashboard_config.get('refresh_interval', 300) * 1000  # Convert to ms

        # Initialize Dash app
        logger.debug("🚀 DEBUG: Creating Dash app with styling...")
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
            title="Multi-Cloud Cost Monitor",
            update_title=None,
            assets_folder='assets'
        )

        # Add custom CSS for spinner animation
        self.app.index_string = '''
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

                /* Make loading spinners more visible */
                ._dash-loading {
                    margin: 2rem auto !important;
                    width: 60px !important;
                    height: 60px !important;
                }

                /* Hide chart content completely when loading */
                *[data-dash-is-loading="true"] {
                    visibility: hidden !important;
                }

                /* Show loading message for all loading components */
                *[data-dash-is-loading="true"]::before {
                    content: "📊 Loading chart data...";
                    visibility: visible !important;
                    display: flex !important;
                    justify-content: center;
                    align-items: center;
                    text-align: center;
                    font-size: 1.4rem;
                    color: #0d6efd;
                    font-weight: bold;
                    padding: 4rem 2rem;
                    background-color: rgba(13, 110, 253, 0.08);
                    border-radius: 12px;
                    margin: 1rem 0;
                    border: 2px solid rgba(13, 110, 253, 0.2);
                    position: absolute;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    z-index: 1000;
                }

                /* Specific styling for chart containers */
                .dash-graph[data-dash-is-loading="true"]::before {
                    content: "📊 Loading chart data...";
                    height: 400px;
                }

                /* Account breakdown loading */
                #account-breakdown-content[data-dash-is-loading="true"]::before {
                    content: "📊 Loading account data...";
                    height: 300px;
                }

                /* Data table loading */
                #cost-data-table[data-dash-is-loading="true"]::before {
                    content: "📊 Loading cost table...";
                    height: 200px;
                }

                /* Ensure parent containers are positioned for absolute positioning */
                ._dash-loading {
                    position: relative !important;
                    min-height: 400px;
                }

                /* Better positioning for account breakdown */
                #account-breakdown-content._dash-loading {
                    min-height: 300px;
                }

                /* Better positioning for data table */
                #cost-data-table._dash-loading {
                    min-height: 200px;
                }

                /* Style error messages prominently */
                .error-message {
                    background-color: #f8d7da !important;
                    color: #721c24 !important;
                    border: 2px solid #f5c6cb !important;
                    border-radius: 8px !important;
                    padding: 1rem !important;
                    margin: 1rem 0 !important;
                    font-weight: bold !important;
                    font-size: 1.1rem !important;
                    text-align: center !important;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
                }

                /* Make database error messages even more prominent */
                .database-error {
                    background-color: #ffeaa7 !important;
                    color: #d63031 !important;
                    border: 3px solid #fd79a8 !important;
                    animation: error-pulse 2s infinite !important;
                }

                @keyframes error-pulse {
                    0% { box-shadow: 0 0 0 0 rgba(214, 48, 49, 0.7); }
                    70% { box-shadow: 0 0 0 10px rgba(214, 48, 49, 0); }
                    100% { box-shadow: 0 0 0 0 rgba(214, 48, 49, 0); }
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
        '''
        logger.debug("✅ DEBUG: Dash app created")

        # Disable Plotly branding and debug elements globally
        self.app.config.suppress_callback_exceptions = True

        # Enable request logging but disable other dev tools
        self.app.enable_dev_tools(
            dev_tools_ui=False,
            dev_tools_props_check=False,
            dev_tools_serve_dev_bundles=False,
            dev_tools_hot_reload=False,
            dev_tools_silence_routes_logging=False  # Enable request logging
        )

        # Set up layout and callbacks
        self._setup_layout()
        self._setup_callbacks()

    def _get_month_start(self, target_date: date = None) -> date:
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

    def _get_week_start(self, target_date: date = None) -> date:
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
        """Create an initial loading chart for immediate display."""
        loading_fig = go.Figure()
        loading_fig.add_annotation(
            text='Loading data...',
            xref='paper', yref='paper',
            x=0.5, y=0.5,
            xanchor='center', yanchor='middle',
            showarrow=False,
            font=dict(size=16, color='gray')
        )
        loading_fig.update_layout(
            title=title,
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            **DashboardTheme.LAYOUT
        )
        return loading_fig

    def _setup_layout(self):
        """Set up the dashboard layout."""
        self.app.layout = dbc.Container([
            # Header
            dbc.Row([
                dbc.Col([
                    html.H1("Multi-Cloud Cost Monitor", className="text-primary mb-0"),
                    html.P("Real-time cost monitoring across AWS, Azure, and GCP",
                           className="text-muted mb-3")
                ], width=6),
                dbc.Col([
                    html.Div(id="last-update-time", className="text-right text-muted mb-2")
                ], width=6)
            ], className="mb-4"),

            # Alert Banner
            html.Div(id="alert-banner"),

            # Loading Banner
            html.Div(id="loading-banner"),

            # Controls Row
            dbc.Row([
                dbc.Col([
                    html.Label("Date Range:"),
                    dbc.InputGroup([
                        dcc.DatePickerRange(
                            id="date-range-picker",
                            start_date=self._get_month_start(),
                            end_date=date.today(),
                            display_format='YYYY-MM-DD',
                            style={'width': '100%'}
                        ),
                        dbc.Button(
                            "Apply",
                            id="btn-apply-dates",
                            color="success",
                            size="sm",
                            style={'marginLeft': '8px'}
                        )
                    ], style={'alignItems': 'center', 'display': 'flex'}),
                    html.Div([
                        html.Small("Quick ranges: ", className="text-muted me-2"),
                        dbc.ButtonGroup([
                            dbc.Button([
                                html.Span("Latest (MTD)"),
                                html.Span("⟳", id="latest-spinner", style={"marginLeft": "8px", "display": "none", "animation": "spin 1s linear infinite"})
                            ], id="btn-latest", size="sm", outline=False, color="primary"),
                            dbc.Button("This Month", id="btn-this-month", size="sm", outline=True, color="secondary"),
                            dbc.Button("Last Month", id="btn-last-month", size="sm", outline=True, color="secondary"),
                            dbc.Button("This Week", id="btn-this-week", size="sm", outline=True, color="secondary"),
                            dbc.Button("Last Week", id="btn-last-week", size="sm", outline=True, color="secondary"),
                            dbc.Button("Last 30 Days", id="btn-last-30-days", size="sm", outline=True, color="secondary"),
                            dbc.Button("Last 7 Days", id="btn-last-7-days", size="sm", outline=True, color="secondary"),
                        ], size="sm")
                    ], className="mt-2")
                ], width=12)
            ], className="mb-4"),

            # Key Metrics Row
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H4(id="total-cost-metric", className="card-title text-primary"),
                            html.P("Total Cost", className="card-text")
                        ])
                    ], className="h-100")
                ], width=3),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H4(id="daily-average-metric", className="card-title text-info"),
                            html.P("Daily Average", className="card-text")
                        ])
                    ], className="h-100")
                ], width=3),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H4(id="monthly-projection-metric", className="card-title text-warning"),
                            html.P("Monthly Projection", className="card-text")
                        ])
                    ], className="h-100")
                ], width=3),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H4(id="cost-trend-metric", className="card-title"),
                            html.P("7-Day Trend", className="card-text")
                        ])
                    ], className="h-100")
                ], width=3)
            ], className="mb-4"),

            # Charts Row 1 - Daily Costs by Provider (Full Width)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            "Daily Costs by Provider",
                            dcc.Dropdown(
                                id="provider-selector",
                                options=[
                                    {'label': 'All Providers', 'value': 'all'},
                                    {'label': 'AWS', 'value': 'aws'},
                                    {'label': 'Azure', 'value': 'azure'},
                                    {'label': 'GCP', 'value': 'gcp'}
                                ],
                                value='all',
                                clearable=False,
                                placeholder="Select provider...",
                                className="float-right",
                                style={'width': '200px'}
                            )
                        ], className="d-flex justify-content-between align-items-center"),
                        dbc.CardBody([
                            dcc.Loading([
                                dcc.Graph(
                                    id="cost-trend-chart",
                                    figure=self._create_initial_loading_chart("Daily Costs by Provider"),
                                    config={
                                        'displayModeBar': False,
                                        'displaylogo': False,
                                        'staticPlot': False,
                                        'plotlyServerURL': "",
                                        'linkText': "",
                                        'showLink': False
                                    }
                                )
                            ], type="default", color="#0d6efd")
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),

            # Charts Row 1.5 - Provider Breakdown
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Provider Breakdown"),
                        dbc.CardBody([
                            dcc.Loading([
                                dcc.Graph(
                                    id="provider-breakdown-chart",
                                    figure=self._create_initial_loading_chart("Provider Distribution"),
                                    config={
                                        'displayModeBar': False,
                                        'displaylogo': False,
                                        'staticPlot': False,
                                        'plotlyServerURL': "",
                                        'linkText': "",
                                        'showLink': False
                                    }
                                )
                            ], type="default", color="#0d6efd")
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),

            # Charts Row 2 - Service Breakdown
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            "Service Breakdown",
                            dcc.Dropdown(
                                id="service-provider-selector",
                                options=[],
                                value=None,
                                placeholder="Select provider...",
                                className="float-right",
                                style={'width': '200px'}
                            )
                        ], className="d-flex justify-content-between align-items-center"),
                        dbc.CardBody([
                            dcc.Loading([
                                dcc.Graph(
                                    id="service-breakdown-chart",
                                    figure=self._create_initial_loading_chart("Service Breakdown"),
                                    config={
                                        'displayModeBar': False,
                                        'displaylogo': False,
                                        'staticPlot': False,
                                        'plotlyServerURL': "",
                                        'linkText': "",
                                        'showLink': False
                                    }
                                )
                            ], type="default", color="#0d6efd")
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),

            # Account/Project/Subscription Breakdown
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            dbc.Row([
                                dbc.Col([
                                    html.H5("📊 Account/Project/Subscription Breakdown", className="mb-0")
                                ], width=4),
                                dbc.Col([
                                    dbc.Row([
                                        dbc.Col([
                                            dcc.Dropdown(
                                                id="account-provider-filter",
                                                options=[
                                                    {'label': 'All Providers', 'value': 'all'},
                                                    {'label': 'AWS', 'value': 'aws'},
                                                    {'label': 'Azure', 'value': 'azure'},
                                                    {'label': 'GCP', 'value': 'gcp'}
                                                ],
                                                value="all",
                                                clearable=False,
                                                placeholder="Provider"
                                            )
                                        ], width=6),
                                        dbc.Col([
                                            dcc.Dropdown(
                                                id="account-sort-dropdown",
                                                options=[
                                                    {'label': 'Cost (High-Low)', 'value': 'cost_desc'},
                                                    {'label': 'Cost (Low-High)', 'value': 'cost_asc'},
                                                    {'label': 'Name (A-Z)', 'value': 'name_asc'},
                                                    {'label': 'Provider', 'value': 'provider'}
                                                ],
                                                value="cost_desc",
                                                clearable=False,
                                                placeholder="Sort by"
                                            )
                                        ], width=6)
                                    ])
                                ], width=4),
                                dbc.Col([
                                    dbc.ButtonGroup([
                                        dbc.Button([html.I(className="fas fa-search me-1"), "Search"],
                                                  id="account-search-btn", size="sm", outline=True),
                                        dbc.Button([html.I(className="fas fa-chart-bar me-1"), "Chart"],
                                                  id="account-chart-btn", size="sm", outline=True),
                                        dbc.Button([html.I(className="fas fa-download me-1"), "Export"],
                                                  id="account-export-btn", size="sm", outline=True)
                                    ], className="float-right")
                                ], width=4, className="text-end")
                            ], className="align-items-center")
                        ]),
                        dbc.CardBody([
                            # Search input (shown when search button is clicked)
                            html.Div([
                                dcc.Input(
                                    id="account-search-input",
                                    type="text",
                                    placeholder="🔍 Search accounts, projects, subscriptions...",
                                    className="form-control mb-3",
                                    debounce=True,
                                    style={'display': 'none'}  # Hidden by default
                                )
                            ], id="account-search-controls", style={'display': 'none'}),

                            # Summary info
                            html.Div(id="account-summary", className="mb-3"),

                            # Account breakdown content
                            dcc.Loading([
                                html.Div(id="account-breakdown-content")
                            ], type="default", color="#0d6efd")
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),

            # Data Table
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Detailed Cost Data"),
                        dbc.CardBody([
                            dcc.Loading([
                                html.Div(id="cost-data-table")
                            ], type="default", color="#0d6efd")
                        ])
                    ])
                ])
            ], className="mb-4"),

            # Auto-refresh interval - default to 30 minutes for Latest mode
            dcc.Interval(
                id='interval-component',
                interval=1800000,  # 30 minutes (1800000ms)
                n_intervals=0,
                disabled=True  # Disabled by default during development
            ),

            # Store for sharing data between callbacks
            dcc.Store(id='cost-data-store'),
            dcc.Store(id='alert-data-store'),
            dcc.Store(id='loading-store', data={'loading': True}),  # Start with loading=True
            dcc.Store(id='date-range-type-store', data={'type': 'latest'}),  # Start with Latest mode by default
            dcc.Store(id='show-all-accounts-store', data={'show_all': False}),  # Track view all state

        ], fluid=True)

    def _setup_callbacks(self):
        """Set up dashboard callbacks."""


        @self.app.callback(
            [Output('cost-data-store', 'data'),
             Output('alert-data-store', 'data'),
             Output('last-update-time', 'children'),
             Output('loading-store', 'data')],
            [Input('interval-component', 'n_intervals'),
             Input('btn-apply-dates', 'n_clicks'),
             Input('btn-latest', 'n_clicks'),
             Input('btn-this-month', 'n_clicks'),
             Input('btn-last-month', 'n_clicks'),
             Input('btn-this-week', 'n_clicks'),
             Input('btn-last-week', 'n_clicks'),
             Input('btn-last-30-days', 'n_clicks'),
             Input('btn-last-7-days', 'n_clicks')],
            [State('date-range-picker', 'start_date'),
             State('date-range-picker', 'end_date')],
            prevent_initial_call=False
        )
        def update_data_store(n_intervals, apply_clicks, latest_clicks, this_month_clicks,
                            last_month_clicks, this_week_clicks, last_week_clicks,
                            last_30_clicks, last_7_clicks, start_date_picker, end_date_picker):
            """Update the main data store."""
            try:
                import dash
                ctx = dash.callback_context

                # Determine which button was pressed to get the date range
                today = date.today()
                triggered_prop = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

                # DEBUG: Log button click details
                logger.info(f"🔘 BUTTON DEBUG: Triggered by {triggered_prop}")
                logger.info(f"🔘 BUTTON DEBUG: Today: {today}")

                # Check if preset button was pressed (immediate update) or Apply button (manual dates)
                if triggered_prop == 'btn-latest':
                    start_date_obj = self._get_month_start(today)
                    end_date_obj = today
                elif triggered_prop == 'btn-this-month':
                    start_date_obj = self._get_month_start(today)
                    end_date_obj = today
                    logger.info(f"🔘 BUTTON DEBUG: This Month calculated - start: {start_date_obj}, end: {end_date_obj}")
                elif triggered_prop == 'btn-last-month':
                    start_date_obj, end_date_obj = self._get_last_month()
                    logger.info(f"🔘 BUTTON DEBUG: Last Month calculated - start: {start_date_obj}, end: {end_date_obj}")
                elif triggered_prop == 'btn-this-week':
                    start_date_obj = self._get_week_start(today)
                    end_date_obj = today
                elif triggered_prop == 'btn-last-week':
                    start_date_obj, end_date_obj = self._get_last_week()
                elif triggered_prop == 'btn-last-30-days':
                    start_date_obj = today - timedelta(days=30)
                    end_date_obj = today
                elif triggered_prop == 'btn-last-7-days':
                    start_date_obj = today - timedelta(days=7)
                    end_date_obj = today
                elif triggered_prop == 'btn-apply-dates':
                    # Use date picker values for Apply button
                    if start_date_picker and end_date_picker:
                        start_date_obj = datetime.strptime(start_date_picker, '%Y-%m-%d').date()
                        end_date_obj = datetime.strptime(end_date_picker, '%Y-%m-%d').date()
                        logger.info(f"🔘 BUTTON DEBUG: Apply button - using picker dates: {start_date_obj} to {end_date_obj}")
                    else:
                        # Fallback if date picker values are missing
                        start_date_obj = self._get_month_start(today)
                        end_date_obj = today
                        logger.warning(f"🔘 BUTTON DEBUG: Apply button - missing picker dates, using This Month fallback")
                elif triggered_prop == 'interval-component':
                    # Auto-refresh: use This Month for consistency (no access to date picker values)
                    start_date_obj = self._get_month_start(today)
                    end_date_obj = today
                    logger.info(f"🔘 BUTTON DEBUG: Interval refresh using This Month - start: {start_date_obj}, end: {end_date_obj}")
                else:
                    # Default case or initial load
                    start_date_obj = self._get_month_start(today)
                    end_date_obj = today

                # Start performance monitoring for data fetch
                self.performance_monitor.start_operation("data_fetch")

                # Get real cost data using the data manager
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError as e:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                data_manager = self.data_manager

                # Quick cache check to avoid unnecessary loading screens
                cache_key = data_manager._get_cache_key(start_date_obj, end_date_obj, False)
                cached_data = None

                # DEBUG: Log cache key and date range used
                logger.info(f"🔘 CACHE DEBUG: Using date range {start_date_obj} to {end_date_obj}")
                logger.info(f"🔘 CACHE DEBUG: Cache key: {cache_key}")

                # Quick cache check to avoid unnecessary loading screens
                if data_manager._dashboard_cache:
                    try:
                        cached_data = data_manager._dashboard_cache.get(cache_key)
                        if cached_data:
                            logger.info(f"🎯 CACHE HIT: {start_date_obj} to {end_date_obj}")
                            real_cost_data = DataWrapper(cached_data)
                            data_fetch_time = 0.001  # Near-instant cache hit
                    except Exception as e:
                        logger.warning(f"Cache check failed: {e}")

                if not cached_data:
                    logger.info(f"Cache miss - fetching data from API for {start_date_obj} to {end_date_obj}")

                    async def fetch_data():
                        return await data_manager.get_cost_data(start_date_obj, end_date_obj, force_refresh=False)

                    data_fetch_start = time.time()
                    real_cost_data = loop.run_until_complete(fetch_data())
                    data_fetch_time = time.time() - data_fetch_start
                    logger.info(f"Data fetch completed in {data_fetch_time:.2f}s")
                else:
                    # Use cached data
                    real_cost_data = cached_data

                # Continue to newer transformation logic below...

            except Exception as e:
                logger.error(f"Error in main callback: {e}")
                # Return proper empty data structure and ALWAYS clear loading state on error
                empty_cost_data = {
                    'total_cost': 0.0,
                    'provider_breakdown': {},
                    'daily_costs': [],
                    'service_breakdown': {},
                    'account_breakdown': {}
                }
                empty_alert_data = {
                    'active_alerts': 0,
                    'critical_alerts': 0,
                    'alerts': []
                }
                error_div = html.Div([f"❌ Error: {str(e)}"], className="error-message")
                return empty_cost_data, empty_alert_data, error_div, {'loading': False}

            import dash

            # Use the date objects we already calculated from button logic
            start_date = start_date_obj
            end_date = end_date_obj

            # Determine if this is a forced refresh (only for specific triggers)
            ctx = dash.callback_context
            force_refresh = False  # Use cache when available

            # Debug logging
            logger.info(f"Callback triggered: interval={n_intervals}")
            logger.info(f"Context triggered: {ctx.triggered}")

            if ctx.triggered:
                prop_id = ctx.triggered[0]['prop_id']
                logger.info(f"Triggered by: {prop_id}")

                # Handle date range changes (only force refresh if explicitly needed)
                if 'date-range-picker' in prop_id:
                    # Use debouncer to prevent rapid successive calls
                    if self.date_debouncer.should_process():
                        # Use cache for date changes unless data is missing
                        force_refresh = False
                    else:
                        # Skip this update - too soon after last change
                        raise dash.exceptions.PreventUpdate

                # Handle auto-refresh interval (use cache unless stale)
                elif 'interval-component' in prop_id:
                    force_refresh = False  # Use cache for auto-refresh

                # Handle initial load (use cache if available)
                elif prop_id == '.':
                    force_refresh = False  # Use cache on initial load

            # Get real cost data using the data manager
            try:
                print("📊 Starting callback data fetch")
                start_total_time = time.time()

                # Start performance monitoring for data fetch
                self.performance_monitor.start_operation("data_fetch")

                # Cancel any existing data fetching task
                if self.current_data_task and not self.current_data_task.done():
                    self.current_data_task.cancel()

                print("🔄 Setting up asyncio event loop")
                # Use asyncio to run the async data manager method
                import asyncio
                try:
                    # Try to get event loop
                    loop = asyncio.get_event_loop()
                    print("✅ Got existing event loop")
                except RuntimeError as e:
                    # Create new event loop if none exists
                    print(f"🔧 Creating new event loop: {e}")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                # Get data manager
                data_manager = self.data_manager

                print("🚀 About to call async data fetch")
                # Create a new task for data fetching with cancellation support
                async def fetch_data():
                    print("📡 Inside fetch_data function")
                    return await data_manager.get_cost_data(start_date, end_date, force_refresh=force_refresh)

                self.current_data_task = loop.create_task(fetch_data())

                # Get real cost data from providers
                print("⏳ Calling loop.run_until_complete - CRITICAL POINT")
                data_fetch_start = time.time()
                real_cost_data = loop.run_until_complete(self.current_data_task)
                data_fetch_time = time.time() - data_fetch_start
                print(f"✅ loop.run_until_complete completed in {data_fetch_time:.3f}s")

                if real_cost_data:
                    # Ensure real_cost_data is a DataWrapper, not a dict
                    if isinstance(real_cost_data, dict):
                        real_cost_data = DataWrapper(real_cost_data)

                    # Convert real data to dashboard format using correct MultiCloudCostSummary structure
                    provider_breakdown = real_cost_data.provider_breakdown
                    daily_costs = real_cost_data.combined_daily_costs
                    service_breakdown = {}

                    total_cost = real_cost_data.total_cost

                    # Debug logging for data transformation
                    logger.info(f"Data transformation debug:")
                    logger.info(f"  Total cost: {total_cost}")
                    logger.info(f"  Provider breakdown: {provider_breakdown}")
                    logger.info(f"  Daily costs length: {len(daily_costs)}")
                    logger.info(f"  Daily costs sample: {daily_costs[:3] if daily_costs else 'None'}")

                    # Build service breakdown from provider_data
                    for provider_name, provider_data in real_cost_data.provider_data.items():
                        # provider_data is a dict from API, use dict access instead of attribute access
                        if isinstance(provider_data, dict):
                            service_breakdown[provider_name.lower()] = provider_data.get('service_breakdown', {})
                        else:
                            # Fallback for object attribute access
                            service_breakdown[provider_name.lower()] = getattr(provider_data, 'service_breakdown', {})

                    # Transform daily costs to match frontend chart expectations
                    for daily_entry in daily_costs:
                        if 'date' in daily_entry:
                            # Ensure we're showing 2025 dates, not 2024
                            date_obj = datetime.strptime(daily_entry['date'], '%Y-%m-%d').date()
                            daily_entry['date'] = date_obj.strftime('%Y-%m-%d')

                            # Flatten provider breakdown to top level for chart compatibility
                            if 'provider_breakdown' in daily_entry:
                                provider_breakdown_data = daily_entry['provider_breakdown']
                                aws_val = provider_breakdown_data.get('aws', 0)
                                azure_val = provider_breakdown_data.get('azure', 0)
                                gcp_val = provider_breakdown_data.get('gcp', 0)

                                daily_entry['aws'] = aws_val
                                daily_entry['azure'] = azure_val
                                daily_entry['gcp'] = gcp_val

                                # Debug the transformation
                                logger.info(f"🔄 TRANSFORM DEBUG: {daily_entry['date']} - AWS: {aws_val}, GCP: {gcp_val}, Azure: {azure_val}")
                            else:
                                logger.warning(f"🔄 TRANSFORM DEBUG: No provider_breakdown for {daily_entry['date']}")

                    # Extract account breakdown from the existing API response
                    account_breakdown = getattr(real_cost_data, 'account_breakdown', {})

                    # Debug: Log what we get from the API for account breakdown
                    logger.info(f"🏦 API ACCOUNT DEBUG: account_breakdown from API type: {type(account_breakdown)}")
                    if account_breakdown and isinstance(account_breakdown, dict):
                        logger.info(f"🏦 API ACCOUNT DEBUG: account_breakdown providers: {list(account_breakdown.keys())}")
                        for provider, accounts in account_breakdown.items():
                            if accounts:
                                sample_key = list(accounts.keys())[0]
                                sample_data = accounts[sample_key]
                                logger.info(f"🏦 API ACCOUNT DEBUG: {provider} sample from API: {sample_data}")
                                logger.info(f"🏦 API ACCOUNT DEBUG: {provider} sample keys from API: {list(sample_data.keys()) if isinstance(sample_data, dict) else 'not dict'}")
                    else:
                        logger.info(f"🏦 API ACCOUNT DEBUG: account_breakdown is empty or not dict: {account_breakdown}")

                    cost_data = {
                        'total_cost': total_cost,
                        'provider_breakdown': provider_breakdown,
                        'daily_costs': daily_costs,
                        'service_breakdown': service_breakdown,
                        'account_breakdown': account_breakdown
                    }

                    # Debug the transformed daily costs structure
                    logger.info(f"🏪 DATA STORE: Final cost_data structure: total={cost_data['total_cost']}, daily_count={len(cost_data['daily_costs'])}")
                    logger.info(f"🏪 DATA STORE: Provider breakdown: {cost_data['provider_breakdown']}")

                    if cost_data['daily_costs']:
                        sample_entry = cost_data['daily_costs'][0]
                        logger.info(f"🏪 DATA STORE: Sample transformed daily entry: {sample_entry}")
                        logger.info(f"🏪 DATA STORE: Sample entry keys: {list(sample_entry.keys())}")

                        # Calculate provider totals from transformed daily data
                        aws_total = sum(entry.get('aws', 0) for entry in cost_data['daily_costs'])
                        gcp_total = sum(entry.get('gcp', 0) for entry in cost_data['daily_costs'])
                        azure_total = sum(entry.get('azure', 0) for entry in cost_data['daily_costs'])
                        logger.info(f"🏪 DATA STORE: Transformed daily totals - AWS: ${aws_total:.2f}, GCP: ${gcp_total:.2f}, Azure: ${azure_total:.2f}")

                        # Show last few entries with provider breakdown
                        for i, entry in enumerate(cost_data['daily_costs'][-3:]):
                            logger.info(f"🏪 DATA STORE: Daily entry {len(cost_data['daily_costs'])-2+i}: {entry['date']} - AWS: ${entry.get('aws', 0):.2f}, GCP: ${entry.get('gcp', 0):.2f}")
                else:
                    # No data available - return empty structure
                    logger.warning("No cost data available from providers")
                    cost_data = {
                        'total_cost': 0.0,
                        'provider_breakdown': {},
                        'daily_costs': [],
                        'service_breakdown': {},
                        'account_breakdown': {}
                    }

                # Simple alert data (could be enhanced with real alert logic)
                alert_data = {
                    'active_alerts': 0,
                    'critical_alerts': 0,
                    'alerts': []
                }

                last_update = f"Last updated: {datetime.now().strftime('%H:%M:%S')}"

                # Calculate timing breakdown for slow operation analysis
                total_time = time.time() - start_total_time
                breakdown = {
                    "data_fetch": data_fetch_time,
                    "processing": total_time - data_fetch_time
                }

                # End performance monitoring with breakdown
                self.performance_monitor.end_operation("data_fetch", breakdown)

                # Check API data collection status to determine if we should keep loading
                api_collection_status = cost_data.get('data_collection_status', 'complete')

                # Calculate date range for enhanced loading messaging
                try:
                    if start_date and end_date:
                        # Ensure dates are date objects for arithmetic
                        date_range_days = (end_date - start_date).days + 1
                    else:
                        date_range_days = 0
                except Exception as e:
                    logger.warning(f"Date arithmetic failed: {e}")
                    date_range_days = 0
                is_long_range = date_range_days > 7

                # Keep loading if API indicates data collection is still in progress
                # BUT prioritize cache hits and add safety mechanisms
                if data_fetch_time < 0.1:  # Cache hit (very fast response)
                    logger.info(f"📊 CACHE HIT: Data loaded instantly ({data_fetch_time:.3f}s) - clearing loading state")
                    loading_state = {'loading': False}
                elif api_collection_status == "in_progress":
                    # Check if this is historical data (> 2 days old) - should not be "in progress"
                    days_since_end = (datetime.now().date() - end_date).days
                    if days_since_end > 2:
                        logger.warning(f"📊 SAFETY: Historical data ({days_since_end} days old) showing 'in_progress' - forcing complete status")
                        loading_state = {'loading': False}
                    else:
                        logger.info(f"📊 API data collection status: IN PROGRESS - returning empty data to maintain loading state")
                        loading_state = {'loading': True}
                        # Return empty data to charts so they continue showing loading indicators
                        # instead of incomplete/partial data that causes gray charts
                        empty_cost_data = {
                            'total_cost': 0.0,
                            'provider_breakdown': {},
                            'daily_costs': [],
                            'service_breakdown': {},
                            'account_breakdown': {},
                            'data_collection_status': 'in_progress'
                        }
                        empty_alert_data = {
                            'active_alerts': 0,
                            'critical_alerts': 0,
                            'alerts': []
                        }
                        last_update = "Collecting missing data..."
                        return empty_cost_data, empty_alert_data, last_update, loading_state
                else:
                    logger.info(f"📊 API data collection status: COMPLETE - clearing loading state")
                    loading_state = {'loading': False}
                return cost_data, alert_data, last_update, loading_state

            except asyncio.CancelledError:
                self.performance_monitor.end_operation("data_fetch")
                logger.info("Data fetch cancelled - request superseded")
                # Return current data without error since this is expected behavior
                loading_state = {'loading': False}
                return {}, {}, "Request cancelled", loading_state
            except Exception as e:
                self.performance_monitor.end_operation("data_fetch")
                import traceback
                logger.error(f"Error updating data store: {e}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                loading_state = {'loading': False}

                # Provide specific error messages for common issues
                error_message = str(e)
                if "no partition of relation" in error_message and "found for row" in error_message:
                    # Database partitioning error - most prominent styling
                    formatted_error = html.Div([
                        "❌ Database Error: No data partition exists for the selected date range. Please choose a different date range or contact your administrator."
                    ], className="error-message database-error")
                elif "500 Internal Server Error" in error_message:
                    formatted_error = html.Div([
                        "❌ Server Error: The cost monitoring service encountered an internal error. Please try again or select a different date range."
                    ], className="error-message")
                elif "authentication" in error_message.lower() or "unauthorized" in error_message.lower():
                    formatted_error = html.Div([
                        "❌ Authentication Error: Unable to authenticate with cloud providers. Please check your credentials."
                    ], className="error-message")
                elif "timeout" in error_message.lower() or "connection" in error_message.lower():
                    formatted_error = html.Div([
                        "❌ Connection Error: Unable to connect to cloud providers. Please check your network connection and try again."
                    ], className="error-message")
                else:
                    formatted_error = html.Div([
                        f"❌ Error: {str(e)}"
                    ], className="error-message")

                return {}, {}, formatted_error, loading_state

        @self.app.callback(
            [Output('total-cost-metric', 'children'),
             Output('daily-average-metric', 'children'),
             Output('monthly-projection-metric', 'children'),
             Output('cost-trend-metric', 'children'),
             Output('cost-trend-metric', 'className')],
            [Input('cost-data-store', 'data'),
             Input('provider-selector', 'value')]
        )
        def update_key_metrics(cost_data, selected_provider):
            """Update key metrics cards."""
            if not cost_data:
                return "Loading...", "Loading...", "Loading...", "Loading...", "card-title"

            daily_costs = cost_data.get('daily_costs', [])

            # Calculate provider-specific metrics
            if selected_provider == 'all':
                # Use total cost across all providers
                total_cost = cost_data.get('total_cost', 0)
                daily_values = [day.get('total_cost', 0) for day in daily_costs]
            else:
                # Filter to selected provider only
                daily_values = [day.get(selected_provider, 0) for day in daily_costs]
                total_cost = sum(daily_values)

            # Calculate metrics based on filtered data
            daily_average = total_cost / max(len(daily_costs), 1)
            monthly_projection = daily_average * 30

            # Calculate 7-day trend if we have enough data
            trend_percentage = 0.0
            trend_text = "N/A"
            trend_class = "card-title text-secondary"

            if len(daily_values) >= 7:
                # Calculate average of last 7 days vs previous 7 days
                sorted_costs = sorted(zip(daily_costs, daily_values), key=lambda x: x[0]['date'])
                last_7_days_values = [item[1] for item in sorted_costs[-7:]]
                prev_7_days_values = [item[1] for item in sorted_costs[-14:-7]] if len(sorted_costs) >= 14 else []

                if prev_7_days_values and last_7_days_values:
                    last_avg = sum(last_7_days_values) / 7
                    prev_avg = sum(prev_7_days_values) / 7

                    if prev_avg > 0:
                        trend_percentage = ((last_avg - prev_avg) / prev_avg) * 100
                        trend_class = "card-title text-success" if trend_percentage > 0 else "card-title text-danger"
                        trend_text = f"+{trend_percentage:.1f}%" if trend_percentage > 0 else f"{trend_percentage:.1f}%"

            return (
                f"${total_cost:,.2f}",
                f"${daily_average:,.2f}",
                f"${monthly_projection:,.2f}",
                trend_text,
                trend_class
            )

        @self.app.callback(
            Output('alert-banner', 'children'),
            [Input('alert-data-store', 'data')]
        )
        def update_alert_banner(alert_data):
            """Update alert banner."""
            if not alert_data or alert_data.get('active_alerts', 0) == 0:
                return ""

            critical_count = alert_data.get('critical_alerts', 0)
            total_count = alert_data.get('active_alerts', 0)

            if critical_count > 0:
                alert_type = "danger"
                icon = "fas fa-exclamation-triangle"
            else:
                alert_type = "warning"
                icon = "fas fa-exclamation-circle"

            return dbc.Alert([
                html.I(className=f"{icon} me-2"),
                f"{total_count} active alert{'s' if total_count != 1 else ''}"
                + (f" ({critical_count} critical)" if critical_count > 0 else "")
            ], color=alert_type, className="mb-3")

        @self.app.callback(
            Output('loading-store', 'data', allow_duplicate=True),
            [Input('btn-apply-dates', 'n_clicks'),
             Input('btn-latest', 'n_clicks'),
             Input('btn-this-month', 'n_clicks'),
             Input('btn-last-month', 'n_clicks'),
             Input('btn-this-week', 'n_clicks'),
             Input('btn-last-week', 'n_clicks'),
             Input('btn-last-30-days', 'n_clicks'),
             Input('btn-last-7-days', 'n_clicks')],
            prevent_initial_call=True
        )
        def trigger_loading_state(*args):
            """Trigger loading state when any data refresh is initiated."""
            import dash
            ctx = dash.callback_context

            if ctx.triggered:
                trigger_prop = ctx.triggered[0]['prop_id']
                logger.info(f"🔄 LOADING TRIGGERED by: {trigger_prop}")
                logger.debug(f"🔄 LOADING TRIGGERED by: {trigger_prop}")  # Console output for debugging
            else:
                logger.info("🔄 LOADING TRIGGERED but no context")
                logger.debug("🔄 LOADING TRIGGERED but no context")

            return {'loading': True}

        @self.app.callback(
            Output('loading-banner', 'children'),
            [Input('loading-store', 'data'),
             Input('cost-data-store', 'data')],
            [State('date-range-picker', 'start_date'),
             State('date-range-picker', 'end_date')]
        )
        def update_loading_banner(loading_data, cost_data, start_date, end_date):
            """Smart loading banner - only shows for actual data fetches, not cache hits."""

            # Show loading only if:
            # 1. Loading store explicitly says to show loading AND
            # 2. We don't have cost data yet OR the API says data collection is in progress
            should_show_loading = (
                loading_data and loading_data.get('loading', False) and
                (not cost_data or cost_data.get('data_collection_status') == 'in_progress')
            )

            if not should_show_loading:
                return ""

            # Prominent loading banner and overlay for actual data fetches
            return html.Div([
                # Top banner
                dbc.Alert([
                    dbc.Spinner(size="lg", color="primary", spinnerClassName="me-3"),
                    html.Div([
                        html.H5("🔄 Loading Cost Data", className="mb-1", style={"color": "#004085"}),
                        html.P(f"Fetching data for {start_date} to {end_date}..." if start_date and end_date else "Loading cost information...",
                               className="mb-0", style={"fontSize": "0.9rem", "color": "#004085"})
                    ])
                ], color="info", className="mb-3 py-3 text-center",
                  style={
                      "border": "2px solid #0066cc",
                      "backgroundColor": "#e6f3ff",
                      "boxShadow": "0 2px 4px rgba(0,0,0,0.1)"
                  }),

                # Semi-transparent overlay to indicate loading state
                html.Div([
                    html.Div([
                        dbc.Spinner(size="xl", color="primary"),
                        html.H4("Loading...", className="mt-3 text-primary")
                    ], className="text-center")
                ], style={
                    "position": "fixed",
                    "top": "0",
                    "left": "0",
                    "width": "100%",
                    "height": "100%",
                    "backgroundColor": "rgba(255,255,255,0.7)",
                    "zIndex": "999",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center"
                })
            ])

        @callback(
            Output('cost-trend-chart', 'figure'),
            [Input('cost-data-store', 'data'),
             Input('provider-selector', 'value')]
        )
        def update_cost_trend_chart(cost_data, selected_provider):
            """Update the cost trend chart."""
            logger.info(f"📊 CHART CALLBACK: Cost trend chart triggered - provider: {selected_provider}")
            chart_start_time = time.time()

            # Enhanced debugging for chart data
            logger.info(f"📊 CHART DEBUG: cost_data type: {type(cost_data)}")
            logger.info(f"📊 CHART DEBUG: cost_data keys: {list(cost_data.keys()) if isinstance(cost_data, dict) else 'not dict'}")

            if cost_data:
                if 'daily_costs' in cost_data:
                    daily_costs = cost_data['daily_costs']
                    logger.info(f"📊 CHART DEBUG: daily_costs length: {len(daily_costs)}")
                    if daily_costs:
                        sample_entry = daily_costs[0]
                        logger.info(f"📊 CHART DEBUG: Sample daily cost entry: {sample_entry}")
                        logger.info(f"📊 CHART DEBUG: Sample entry keys: {list(sample_entry.keys())}")

                        # Check provider totals in the data
                        aws_total = sum(entry.get('aws', 0) for entry in daily_costs)
                        gcp_total = sum(entry.get('gcp', 0) for entry in daily_costs)
                        azure_total = sum(entry.get('azure', 0) for entry in daily_costs)
                        logger.info(f"📊 CHART DEBUG: Provider totals - AWS: ${aws_total:.2f}, GCP: ${gcp_total:.2f}, Azure: ${azure_total:.2f}")
                else:
                    logger.warning(f"📊 CHART DEBUG: No 'daily_costs' in cost_data")

                if 'provider_breakdown' in cost_data:
                    logger.info(f"📊 CHART DEBUG: Provider breakdown: {cost_data['provider_breakdown']}")

            # Disable cache temporarily for debugging bar chart issues
            # cache_key = self.chart_memoizer.get_cache_key(cost_data, {'chart_type': 'cost_trend', 'provider': selected_provider})
            # cached_figure = self.chart_memoizer.get(cache_key)
            # if cached_figure:
            #     cache_time = time.time() - chart_start_time
            #     logger.debug(f"💨 DEBUG: Cost trend chart from cache in {cache_time:.3f}s")
            #     logger.debug("Returning cached cost trend chart")
            #     return cached_figure

            # Return loading chart if no data
            if not cost_data or 'daily_costs' not in cost_data:
                logger.warning(f"📊 CHART DEBUG: Returning loading chart - no data or no daily_costs")
                loading_fig = go.Figure()
                loading_fig.add_annotation(
                    text='Loading data...',
                    xref='paper', yref='paper',
                    x=0.5, y=0.5,
                    xanchor='center', yanchor='middle',
                    showarrow=False,
                    font=dict(size=16, color='gray')
                )
                loading_fig.update_layout(
                    title='Daily Costs by Provider',
                    xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    **DashboardTheme.LAYOUT
                )
                return loading_fig

            fig = go.Figure()

            if cost_data and 'daily_costs' in cost_data:
                daily_costs = cost_data['daily_costs']
                dates = [item['date'] for item in daily_costs]
                today_str = date.today().strftime('%Y-%m-%d')

                logger.info(f"📊 CHART DEBUG: Processing chart data with {len(daily_costs)} daily entries")
                logger.info(f"📊 CHART DEBUG: Date range: {dates[0] if dates else 'none'} to {dates[-1] if dates else 'none'}")

                if selected_provider == 'all':
                    logger.info(f"📊 CHART DEBUG: Creating grouped bars for all providers")

                    # Pre-calculate if we'll need log scale
                    aws_max = max([entry.get('aws', 0) for entry in daily_costs], default=0)
                    gcp_max = max([entry.get('gcp', 0) for entry in daily_costs], default=0)
                    azure_max = max([entry.get('azure', 0) for entry in daily_costs], default=0)
                    all_maxes = [val for val in [aws_max, gcp_max, azure_max] if val > 0]

                    if len(all_maxes) > 1:
                        ratio = max(all_maxes) / min(all_maxes)
                        will_use_log_scale = ratio > 50
                    else:
                        will_use_log_scale = False

                    logger.info(f"📊 CHART DEBUG: Scale analysis - AWS max: ${aws_max:.2f}, GCP max: ${gcp_max:.2f}, Will use log: {will_use_log_scale}")

                    # Show daily costs broken down by provider (grouped bars)
                    for provider in ['aws', 'azure', 'gcp']:
                        values = [item.get(provider, 0) for item in daily_costs]

                        # For log scale, replace zero values with a small positive number
                        if will_use_log_scale:
                            # Use 0.01 as minimum value for log scale visibility
                            display_values = [max(v, 0.01) for v in values]
                            # Keep original values for hover and display
                            hover_values = values
                            text_labels = [self._format_currency_compact(v) if v > 0 else '$0.00' for v in values]
                        else:
                            display_values = values
                            hover_values = values
                            text_labels = [self._format_currency_compact(v) if v > 0 else '$0.00' for v in values]

                        # Debug each provider's values
                        total_value = sum(values)
                        non_zero_count = sum(1 for v in values if v > 0)
                        logger.info(f"📊 CHART DEBUG: {provider.upper()} - Total: ${total_value:.2f}, Non-zero entries: {non_zero_count}/{len(values)}")
                        logger.info(f"📊 CHART DEBUG: {provider.upper()} values sample: {values[:3]}...")

                        fig.add_trace(go.Bar(
                            x=dates,
                            y=display_values,
                            name=provider.upper(),
                            marker_color=DashboardTheme.COLORS.get(provider, '#000000'),
                            marker_line=dict(width=1, color='rgba(0,0,0,0.3)'),
                            text=text_labels,
                            textposition='outside',
                            textfont=dict(size=14, color='black'),
                            hovertemplate=f'<b>{provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{customdata:.2f}}<extra></extra>',
                            customdata=hover_values  # Show actual values in hover, not log-scale adjusted ones
                        ))
                        logger.info(f"📊 CHART DEBUG: Added trace for {provider.upper()}")
                else:
                    # Show selected provider only
                    values = [item.get(selected_provider, 0) for item in daily_costs]

                    # Handle AWS specially when it's the selected provider
                    if selected_provider == 'aws':
                        display_values = []
                        hover_values = []
                        text_labels = []

                        for i, (item, value) in enumerate(zip(daily_costs, values)):
                            is_today = item['date'] == today_str
                            if is_today:
                                # For today's AWS data, show minimal bar and "N/A" text
                                display_values.append(0.01)  # Minimal bar for log scale
                                hover_values.append(0)  # Show $0 in hover
                                text_labels.append('N/A')
                            else:
                                display_values.append(max(value, 0.01))  # Normal handling
                                hover_values.append(value)
                                text_labels.append(self._format_currency_compact(value) if value > 0 else '$0.00')

                        # For AWS single provider view, create dynamic hover data
                        aws_hover_data = []
                        for i, item in enumerate(daily_costs):
                            is_today = item['date'] == today_str
                            if is_today:
                                aws_hover_data.append('N/A (Data lag)')
                            else:
                                aws_hover_data.append(f'${hover_values[i]:.2f}')

                        fig.add_trace(go.Bar(
                            x=dates,
                            y=display_values,
                            name=selected_provider.upper(),
                            marker_color=DashboardTheme.COLORS.get(selected_provider, '#000000'),
                            marker_line=dict(width=1, color='rgba(0,0,0,0.3)'),
                            text=text_labels,
                            textposition='outside',
                            textfont=dict(size=14, color='black'),
                            hovertemplate='<b>AWS</b><br>Date: %{x}<br>Cost: %{customdata}<extra></extra>',
                            customdata=aws_hover_data
                        ))
                    else:
                        # Other providers show normally
                        display_values = [max(v, 0.01) for v in values]
                        hover_values = values
                        text_labels = [self._format_currency_compact(v) if v > 0 else '$0.00' for v in values]
                        hover_template = f'<b>{selected_provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{customdata:.2f}}<extra></extra>'

                        fig.add_trace(go.Bar(
                            x=dates,
                            y=display_values,
                            name=selected_provider.upper(),
                            marker_color=DashboardTheme.COLORS.get(selected_provider, '#000000'),
                            marker_line=dict(width=1, color='rgba(0,0,0,0.3)'),
                            text=text_labels,
                            textposition='outside',
                            textfont=dict(size=14, color='black'),
                            hovertemplate=hover_template,
                            customdata=hover_values
                        ))

            # Create layout with custom margin for the log scale note
            layout_config = DashboardTheme.LAYOUT.copy()
            layout_config['margin'] = {'l': 20, 'r': 20, 't': 40, 'b': 80}  # Increase bottom margin

            # Determine if we should use log scale for better visibility
            # Use log scale if there's a large difference between provider totals
            if cost_data and 'daily_costs' in cost_data:
                daily_costs = cost_data['daily_costs']
                aws_max = max([entry.get('aws', 0) for entry in daily_costs], default=0)
                gcp_max = max([entry.get('gcp', 0) for entry in daily_costs], default=0)
                azure_max = max([entry.get('azure', 0) for entry in daily_costs], default=0)

                # If the largest value is more than 50x the smallest non-zero value, use log scale
                all_maxes = [val for val in [aws_max, gcp_max, azure_max] if val > 0]
                if len(all_maxes) > 1:
                    ratio = max(all_maxes) / min(all_maxes)
                    use_log_scale = ratio > 50
                    logger.info(f"📊 CHART SCALE: Max ratio {ratio:.1f}x, using {'LOG' if use_log_scale else 'LINEAR'} scale")
                else:
                    use_log_scale = False
                    logger.info(f"📊 CHART SCALE: Single provider, using LINEAR scale")
            else:
                use_log_scale = False

            fig.update_layout(
                title="Daily Costs by Provider" + (" (Log Scale)" if use_log_scale else ""),
                xaxis_title="Date",
                yaxis_title="Cost (USD)" + (" - Log Scale" if use_log_scale else ""),
                yaxis_type="log" if use_log_scale else "linear",
                barmode='group',  # Group bars by provider for each date
                hovermode='x unified',
                showlegend=True,  # Show legend to identify providers
                bargap=0.2,  # Gap between date groups
                bargroupgap=0.1,  # Gap between provider bars within each date
                **layout_config
            )

            # Cache disabled for debugging
            # self.chart_memoizer.set(cache_key, fig)

            chart_total_time = time.time() - chart_start_time
            logger.info(f"📈 CHART FINAL: Generated chart with {len(fig.data)} traces, barmode={fig.layout.barmode}, title={fig.layout.title.text}")

            # Log detailed trace information
            for i, trace in enumerate(fig.data):
                trace_sum = sum(trace.y) if hasattr(trace, 'y') and trace.y else 0
                logger.info(f"📈 CHART TRACE {i}: {trace.name} - Total: ${trace_sum:.2f}, Data points: {len(trace.y) if hasattr(trace, 'y') else 0}")

            logger.info(f"📈 CHART DEBUG: Chart generation completed in {chart_total_time:.3f}s")
            return fig

        @callback(
            Output('provider-breakdown-chart', 'figure'),
            [Input('cost-data-store', 'data')]
        )
        def update_provider_breakdown_chart(cost_data):
            """Update the provider breakdown chart."""
            # Cache disabled for debugging account breakdown issues
            # cache_key = self.chart_memoizer.get_cache_key(cost_data, {'chart_type': 'provider_breakdown'})
            # cached_figure = self.chart_memoizer.get(cache_key)
            # if cached_figure:
            #     logger.debug("Returning cached provider breakdown chart")
            #     return cached_figure

            # Return loading chart if no data
            if not cost_data or 'provider_breakdown' not in cost_data:
                loading_fig = go.Figure()
                loading_fig.add_annotation(
                    text='Loading data...',
                    xref='paper', yref='paper',
                    x=0.5, y=0.5,
                    xanchor='center', yanchor='middle',
                    showarrow=False,
                    font=dict(size=16, color='gray')
                )
                loading_fig.update_layout(
                    title='Provider Distribution',
                    xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    **DashboardTheme.LAYOUT
                )
                return loading_fig

            fig = go.Figure()

            if cost_data and 'provider_breakdown' in cost_data:
                provider_breakdown = cost_data['provider_breakdown']

                providers = list(provider_breakdown.keys())
                values = list(provider_breakdown.values())
                colors = [DashboardTheme.COLORS.get(p, '#000000') for p in providers]

                fig.add_trace(go.Pie(
                    labels=[p.upper() for p in providers],
                    values=values,
                    hole=0.4,
                    marker_colors=colors,
                    textinfo='label+percent',
                    textposition='outside'
                ))

            fig.update_layout(
                title="Provider Distribution",
                **DashboardTheme.LAYOUT
            )

            # Cache disabled for debugging account breakdown issues
            # self.chart_memoizer.set(cache_key, fig)
            return fig

        @callback(
            [Output('service-provider-selector', 'options'),
             Output('service-provider-selector', 'value')],
            [Input('cost-data-store', 'data')]
        )
        def update_service_provider_selector(cost_data):
            """Update service provider selector options."""
            if not cost_data or 'service_breakdown' not in cost_data:
                return [], None

            providers = list(cost_data['service_breakdown'].keys())
            options = [{'label': p.upper(), 'value': p} for p in providers]

            return options, providers[0] if providers else None

        @callback(
            Output('service-breakdown-chart', 'figure'),
            [Input('cost-data-store', 'data'),
             Input('service-provider-selector', 'value')]
        )
        def update_service_breakdown_chart(cost_data, selected_provider):
            """Update the service breakdown chart."""
            # Return loading chart if no data
            if (not cost_data or 'service_breakdown' not in cost_data or
                not selected_provider or selected_provider not in cost_data['service_breakdown']):
                title = f'Service Breakdown - {selected_provider.upper() if selected_provider else "Loading..."}'
                loading_fig = go.Figure()
                loading_fig.add_annotation(
                    text='Loading data...',
                    xref='paper', yref='paper',
                    x=0.5, y=0.5,
                    xanchor='center', yanchor='middle',
                    showarrow=False,
                    font=dict(size=16, color='gray')
                )
                loading_fig.update_layout(
                    title=title,
                    xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                    **DashboardTheme.LAYOUT
                )
                return loading_fig

            fig = go.Figure()

            if (cost_data and 'service_breakdown' in cost_data and
                selected_provider and selected_provider in cost_data['service_breakdown']):

                service_data = cost_data['service_breakdown'][selected_provider]
                # Filter out services with costs less than $100 and sort by cost (highest to lowest)
                filtered_services = [(k, v) for k, v in service_data.items() if v >= 100.0]
                sorted_services = sorted(filtered_services, key=lambda x: x[1], reverse=True)
                services = [s[0] for s in sorted_services]
                values = [s[1] for s in sorted_services]
                # Replace zero values with small positive number for log scale
                log_values = [max(v, 0.01) for v in values]

                fig.add_trace(go.Bar(
                    x=log_values,  # Log-safe values on x-axis (horizontal bars)
                    y=services,  # Service names on y-axis
                    orientation='h',  # Horizontal orientation
                    marker_color=DashboardTheme.COLORS.get(selected_provider, '#000000'),
                    text=[self._format_currency_compact(v) if v > 0 else "$0.00" for v in values],
                    textposition='outside',
                    hovertemplate='<b>%{y}</b><br>Cost: $%{customdata:.2f}<extra></extra>',
                    customdata=values  # Store original values for hover
                ))

            fig.update_layout(
                title=f"Service Breakdown - {selected_provider.upper() if selected_provider else 'N/A'} (Log Scale, ≥$100)",
                xaxis_title="Cost (USD) - Logarithmic Scale",
                xaxis_type="log",  # Use logarithmic scale for cost differences
                yaxis_title="Service",
                height=400,  # Increase height to accommodate horizontal bars
                **DashboardTheme.LAYOUT
            )

            return fig

        # Account Breakdown Callbacks
        @callback(
            [Output('account-search-controls', 'style'),
             Output('account-search-input', 'style')],
            [Input('account-search-btn', 'n_clicks')],
            prevent_initial_call=False
        )
        def toggle_account_search(n_clicks):
            """Toggle visibility of search input."""
            if n_clicks and n_clicks % 2 == 1:
                # Odd number of clicks - show search input
                return {'display': 'block'}, {'display': 'block'}
            # Even number of clicks (including 0) or no clicks - hide search input
            return {'display': 'none'}, {'display': 'none'}

        @callback(
            Output('account-summary', 'children'),
            [Input('cost-data-store', 'data')]
        )
        def update_account_summary(cost_data):
            """Update account breakdown summary."""
            if not cost_data or 'account_breakdown' not in cost_data:
                return "Loading account data..."

            account_breakdown = cost_data['account_breakdown']
            if not account_breakdown:
                return "No account data available."

            # Handle nested structure: account_breakdown[provider][account_id] = account_data
            total_accounts = 0
            total_cost = 0
            provider_counts = {}

            for provider, accounts in account_breakdown.items():
                provider_counts[provider] = len(accounts)
                total_accounts += len(accounts)
                for account_data in accounts.values():
                    total_cost += account_data['cost']

            # Build summary text
            provider_summary = ", ".join([f"{count} {provider.upper()}" for provider, count in provider_counts.items()])

            return html.Div([
                html.P([
                    html.Strong(f"📈 Summary: "),
                    f"${total_cost:,.2f} across {total_accounts:,} accounts ({provider_summary})"
                ], className="mb-0")
            ])

        @callback(
            Output('account-breakdown-content', 'children'),
            [Input('cost-data-store', 'data'),
             Input('account-search-input', 'value'),
             Input('account-provider-filter', 'value'),
             Input('account-sort-dropdown', 'value'),
             Input('show-all-accounts-store', 'data')],
            prevent_initial_call=False
        )
        def update_account_breakdown_content(cost_data, search_term, provider_filter, sort_option, show_all_data):
            """Update the main account breakdown content."""
            # Get data manager for account name resolution
            data_manager = self.data_manager


            if not cost_data or 'account_breakdown' not in cost_data:
                return "Loading account data..."

            account_breakdown = cost_data['account_breakdown']
            if not account_breakdown:
                return "No account data available."

            # Debug: Log the structure of account breakdown data
            logger.info(f"🏦 ACCOUNT DEBUG: account_breakdown keys: {list(account_breakdown.keys())}")
            for provider, accounts in account_breakdown.items():
                logger.info(f"🏦 ACCOUNT DEBUG: {provider} has {len(accounts)} accounts")
                if accounts:
                    sample_key = list(accounts.keys())[0]
                    sample_data = accounts[sample_key]
                    logger.info(f"🏦 ACCOUNT DEBUG: {provider} sample account data: {sample_data}")
                    logger.info(f"🏦 ACCOUNT DEBUG: {provider} sample account keys: {list(sample_data.keys())}")

            # Convert nested structure to flat list for filtering and sorting
            accounts_list = []
            for provider, accounts in account_breakdown.items():
                for account_key, account_data in accounts.items():
                    # Only include accounts with non-zero costs
                    if account_data.get('cost', 0) > 0:
                        # Get account details from the API response
                        account_id = account_data.get('account_id', account_key)
                        account_name = account_data.get('account_name', account_id)

                        # Use the account name from API if available, otherwise format appropriately
                        if 'account_name' in account_data and account_name != account_id:
                            # API provided a proper account name, use it
                            formatted_name = account_name
                        else:
                            # Fallback formatting for when account name is missing
                            if provider == 'gcp' and account_id.startswith('MultiProject'):
                                # For GCP: Extract project name from MultiProject(name) format
                                import re
                                match = re.search(r'MultiProject\(([^)]+)\)', account_id)
                                if match:
                                    project_name = match.group(1)
                                    formatted_name = project_name
                                else:
                                    formatted_name = account_id
                            elif provider == 'aws':
                                # For AWS: Show account ID with label
                                formatted_name = f"AWS Account ({account_id})"
                            elif provider == 'azure':
                                # For Azure: Show subscription ID with label
                                formatted_name = f"Azure Subscription ({account_id})"
                            else:
                                formatted_name = account_id

                        accounts_list.append({
                            'key': account_key,
                            'account_name': formatted_name,
                            'total_cost': account_data['cost'],
                            'provider': account_data['provider'],
                            'currency': account_data['currency'],
                            **account_data
                        })

            # Apply filters
            if provider_filter and provider_filter != 'all':
                accounts_list = [acc for acc in accounts_list if acc['provider'] == provider_filter]

            if search_term:
                search_lower = search_term.lower()
                accounts_list = [acc for acc in accounts_list
                               if search_lower in acc['account_name'].lower()
                               or search_lower in acc['account_id'].lower()]

            # Apply sorting
            if sort_option == 'cost_desc':
                accounts_list.sort(key=lambda x: x['total_cost'], reverse=True)
            elif sort_option == 'cost_asc':
                accounts_list.sort(key=lambda x: x['total_cost'])
            elif sort_option == 'name_asc':
                accounts_list.sort(key=lambda x: x['account_name'].lower())
            elif sort_option == 'provider':
                accounts_list.sort(key=lambda x: (x['provider'], -x['total_cost']))

            # Get show_all state from store
            show_all = show_all_data.get('show_all', False) if show_all_data else False

            # Show top 20 by default, or all if "View All" was clicked
            if show_all:
                display_accounts = accounts_list
                remaining_count = 0
            else:
                display_accounts = accounts_list[:20]
                remaining_count = len(accounts_list) - 20

            # Calculate percentages for display accounts
            total_cost_all = sum(acc['total_cost'] for acc in accounts_list)
            for account in display_accounts:
                account['percentage'] = (account['total_cost'] / total_cost_all * 100) if total_cost_all > 0 else 0

            # Resolve AWS account names for only the accounts that will be displayed
            # Account data already contains necessary information for display
            # No need for additional account name resolution

            # Create table rows
            table_rows = []
            for i, account in enumerate(display_accounts, 1):
                # Color coding for cost levels
                cost = account['total_cost']
                if cost > 10000:  # Hot
                    badge_color = "danger"
                    badge_text = "🔥 Hot"
                elif cost > 1000:  # Warm
                    badge_color = "warning"
                    badge_text = "🟡 Warm"
                else:  # Cool
                    badge_color = "secondary"
                    badge_text = "❄️ Cool"

                table_rows.append(
                    html.Tr([
                        html.Td(str(i), className="text-center"),
                        html.Td([
                            html.Div(account['account_name'], className="fw-bold")
                        ]),
                        html.Td(dbc.Badge(account['provider'].upper(), color="info", className="me-2")),
                        html.Td(f"${cost:,.2f}", className="text-end fw-bold"),
                        html.Td([
                            f"{account['percentage']:.1f}%",
                            dbc.Badge(badge_text, color=badge_color, className="ms-2")
                        ], className="text-end"),
                    ])
                )

            # Build table
            table = dbc.Table([
                html.Thead([
                    html.Tr([
                        html.Th("#", className="text-center", style={'width': '5%'}),
                        html.Th("Account/Project/Subscription", style={'width': '40%'}),
                        html.Th("Provider", style={'width': '15%'}),
                        html.Th("Cost", className="text-end", style={'width': '20%'}),
                        html.Th("% of Total", className="text-end", style={'width': '20%'}),
                    ])
                ]),
                html.Tbody(table_rows)
            ], striped=True, hover=True, responsive=True)

            # Add appropriate button based on current view
            content = [table]
            if show_all and len(accounts_list) > 20:
                # When showing all accounts, offer option to go back to top 20
                content.append(
                    html.Div([
                        dbc.Alert([
                            html.I(className="fas fa-check-circle me-2"),
                            f"Showing all {len(accounts_list):,} accounts. ",
                            html.Small("(Tip: Use search/filters above to narrow results)", className="text-muted")
                        ], color="success", className="mt-3")
                    ])
                )
            elif remaining_count > 0:
                # When showing top 20, offer option to view all
                content.append(
                    html.Div([
                        dbc.Alert([
                            html.I(className="fas fa-info-circle me-2"),
                            f"Showing top 20 of {len(accounts_list):,} accounts. ",
                            dbc.Button([
                                html.I(className="fas fa-list me-1"),
                                f"View All {len(accounts_list):,} Accounts"
                            ], id={"type": "view-all-btn", "index": len(accounts_list)}, color="link", size="sm")
                        ], color="info", className="mt-3")
                    ])
                )

            return html.Div(content)

        @callback(
            Output('show-all-accounts-store', 'data'),
            [Input({"type": "view-all-btn", "index": ALL}, 'n_clicks')],
            prevent_initial_call=True
        )
        def toggle_show_all_accounts(n_clicks_list):
            """Toggle the show all accounts state when button is clicked."""
            import dash
            ctx = dash.callback_context

            if ctx.triggered and any(n_clicks_list):
                return {'show_all': True}

            return {'show_all': False}

        @callback(
            Output('show-all-accounts-store', 'data', allow_duplicate=True),
            [Input('account-search-input', 'value'),
             Input('account-provider-filter', 'value'),
             Input('account-sort-dropdown', 'value')],
            prevent_initial_call=True
        )
        def reset_show_all_on_filter_change(search_term, provider_filter, sort_option):
            """Reset show all state when filters change."""
            return {'show_all': False}

        @callback(
            Output('account-chart-btn', 'color'),
            [Input('account-chart-btn', 'n_clicks'),
             Input('cost-data-store', 'data')],
            prevent_initial_call=False
        )
        def handle_account_chart_view(chart_clicks, cost_data):
            """Handle account chart view toggle."""
            # For now, just change button color when clicked
            if chart_clicks and chart_clicks > 0:
                return "primary"
            return "outline-secondary"

        @callback(
            Output('account-export-btn', 'children'),
            [Input('account-export-btn', 'n_clicks'),
             Input('cost-data-store', 'data')],
            prevent_initial_call=False
        )
        def handle_account_export(export_clicks, cost_data):
            """Handle account data export."""
            if export_clicks and export_clicks > 0:
                # Generate export data
                if cost_data and 'account_breakdown' in cost_data:
                    account_breakdown = cost_data['account_breakdown']

                    # Convert nested structure to flat list for export
                    accounts_list = []
                    for provider, accounts in account_breakdown.items():
                        for account_key, account_data in accounts.items():
                            # Use the same formatting logic as display (same as above)
                            account_id = account_data.get('account_id', account_key)
                            account_name = account_data.get('account_name', account_id)

                            # Use the account name from API if available, otherwise format appropriately
                            if 'account_name' in account_data and account_name != account_id:
                                # API provided a proper account name, use it
                                formatted_name = account_name
                            else:
                                # Fallback formatting for when account name is missing
                                if provider == 'gcp' and account_id.startswith('MultiProject'):
                                    # For GCP: Extract project name from MultiProject(name) format
                                    import re
                                    match = re.search(r'MultiProject\(([^)]+)\)', account_id)
                                    if match:
                                        project_name = match.group(1)
                                        formatted_name = project_name
                                    else:
                                        formatted_name = account_id
                                elif provider == 'aws':
                                    # For AWS: Show account ID with label
                                    formatted_name = f"AWS Account ({account_id})"
                                elif provider == 'azure':
                                    # For Azure: Show subscription ID with label
                                    formatted_name = f"Azure Subscription ({account_id})"
                                else:
                                    formatted_name = account_id

                            accounts_list.append({
                                'account_name': formatted_name,
                                'account_id': account_id,
                                'total_cost': account_data['cost'],
                                'provider': account_data['provider']
                            })

                    # Calculate percentages
                    total_cost_all = sum(acc['total_cost'] for acc in accounts_list)
                    for account in accounts_list:
                        account['percentage'] = (account['total_cost'] / total_cost_all * 100) if total_cost_all > 0 else 0

                    # Convert to CSV-friendly format
                    import io
                    import csv
                    from datetime import datetime

                    output = io.StringIO()
                    fieldnames = ['Account_Name', 'Account_ID', 'Provider', 'Cost_USD', 'Percentage', 'Export_Date']
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()

                    for account_data in accounts_list:
                        writer.writerow({
                            'Account_Name': account_data['account_name'],
                            'Account_ID': account_data['account_id'],
                            'Provider': account_data['provider'].upper(),
                            'Cost_USD': f"{account_data['total_cost']:.2f}",
                            'Percentage': f"{account_data['percentage']:.1f}%",
                            'Export_Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })

                    # Return success indication
                    return [html.I(className="fas fa-check me-1"), "Exported!"]
                else:
                    return [html.I(className="fas fa-exclamation me-1"), "No Data"]

            return [html.I(className="fas fa-download me-1"), "Export"]

        @callback(
            Output('cost-data-table', 'children'),
            [Input('cost-data-store', 'data')]
        )
        def update_cost_data_table(cost_data):
            """Update the detailed cost data table."""
            if not cost_data or 'daily_costs' not in cost_data:
                return "Loading cost data..."

            daily_costs = cost_data['daily_costs']
            today_str = date.today().strftime('%Y-%m-%d')

            # Convert to DataFrame format for display
            df_data = []
            for item in daily_costs:
                # Check if this is today's date
                is_today = item['date'] == today_str

                # For AWS, show "N/A" if it's today (due to data lag), otherwise show the cost
                aws_cost = item.get('aws', 0)
                aws_display = "N/A" if is_today else f"${aws_cost:.2f}"

                # Other providers show normally (they might have more current data)
                azure_cost = item.get('azure', 0)
                gcp_cost = item.get('gcp', 0)

                # For total, exclude AWS if it's today and showing N/A
                total_cost = sum([item.get('azure', 0), item.get('gcp', 0)])
                if not is_today:
                    total_cost += aws_cost

                row = {
                    'Date': item['date'],
                    'AWS': aws_display,
                    'Azure': f"${azure_cost:.2f}",
                    'GCP': f"${gcp_cost:.2f}",
                    'Total': f"${total_cost:.2f}" if not is_today or total_cost > 0 else "N/A*"
                }
                df_data.append(row)

            return dash_table.DataTable(
                data=df_data,
                columns=[
                    {'name': 'Date', 'id': 'Date'},
                    {'name': 'AWS', 'id': 'AWS'},
                    {'name': 'Azure', 'id': 'Azure'},
                    {'name': 'GCP', 'id': 'GCP'},
                    {'name': 'Total', 'id': 'Total'}
                ],
                style_cell={'textAlign': 'left'},
                style_header={'backgroundColor': DashboardTheme.COLORS['primary'], 'color': 'white'},
                style_data={'backgroundColor': DashboardTheme.COLORS['light']},
                page_size=15,  # Increased page size for better UX
                page_action='native',  # Enable pagination
                sort_action='native',  # Enable sorting
                filter_action='native',  # Enable filtering
                export_format='xlsx',  # Enable export
                export_headers='display',
                style_table={'overflowX': 'auto'}  # Better responsive design
            )

        @callback(
            [Output('date-range-picker', 'start_date'),
             Output('date-range-picker', 'end_date')],
            [Input('btn-latest', 'n_clicks'),
             Input('btn-this-month', 'n_clicks'),
             Input('btn-last-month', 'n_clicks'),
             Input('btn-this-week', 'n_clicks'),
             Input('btn-last-week', 'n_clicks'),
             Input('btn-last-30-days', 'n_clicks'),
             Input('btn-last-7-days', 'n_clicks'),
             Input('interval-component', 'n_intervals')],
            [State('date-range-type-store', 'data')],
            prevent_initial_call=True
        )
        def update_date_range(latest_clicks, this_month_clicks, last_month_clicks, this_week_clicks, last_week_clicks, last_30_clicks, last_7_clicks, n_intervals, date_range_type):
            """Update date range based on quick select buttons or auto-refresh."""
            import dash
            ctx = dash.callback_context

            if not ctx.triggered:
                return dash.no_update, dash.no_update

            trigger_prop = ctx.triggered[0]['prop_id'].split('.')[0]
            today = date.today()

            # Handle auto-refresh for Latest mode
            if trigger_prop == 'interval-component':
                # Only auto-update if we're in "latest" mode
                if date_range_type and date_range_type.get('type') == 'latest':
                    logger.info("Auto-refresh triggered for Latest range (month-to-date)")
                    # Latest: Month-to-date
                    start_date = self._get_month_start(today)
                    end_date = today
                    return start_date, end_date
                else:
                    return dash.no_update, dash.no_update

            # Handle button clicks
            if trigger_prop == 'btn-latest':
                # Latest: Month-to-date (auto-updates daily)
                start_date = self._get_month_start(today)
                end_date = today
            elif trigger_prop == 'btn-this-month':
                # First day of current month to today
                start_date = self._get_month_start(today)
                end_date = today
            elif trigger_prop == 'btn-last-month':
                # First day to last day of previous month
                start_date, end_date = self._get_last_month_range()
            elif trigger_prop == 'btn-this-week':
                # Monday of current week to today
                start_date = self._get_week_start(today)
                end_date = today
            elif trigger_prop == 'btn-last-week':
                # Monday to Sunday of previous week
                start_date, end_date = self._get_last_week_range()
            elif trigger_prop == 'btn-last-30-days':
                # 30 days ago to today
                start_date = today - timedelta(days=30)
                end_date = today
            elif trigger_prop == 'btn-last-7-days':
                # 7 days ago to today
                start_date = today - timedelta(days=7)
                end_date = today
            else:
                return dash.no_update, dash.no_update

            return start_date, end_date

        @callback(
            [Output('btn-latest', 'outline'),
             Output('btn-latest', 'color'),
             Output('btn-this-month', 'outline'),
             Output('btn-this-month', 'color'),
             Output('btn-last-month', 'outline'),
             Output('btn-last-month', 'color'),
             Output('btn-this-week', 'outline'),
             Output('btn-this-week', 'color'),
             Output('btn-last-week', 'outline'),
             Output('btn-last-week', 'color'),
             Output('btn-last-30-days', 'outline'),
             Output('btn-last-30-days', 'color'),
             Output('btn-last-7-days', 'outline'),
             Output('btn-last-7-days', 'color')],
            [Input('btn-latest', 'n_clicks'),
             Input('btn-this-month', 'n_clicks'),
             Input('btn-last-month', 'n_clicks'),
             Input('btn-this-week', 'n_clicks'),
             Input('btn-last-week', 'n_clicks'),
             Input('btn-last-30-days', 'n_clicks'),
             Input('btn-last-7-days', 'n_clicks'),
             Input('btn-apply-dates', 'n_clicks'),
             Input('interval-component', 'n_intervals')],
            [State('date-range-picker', 'start_date'),
             State('date-range-picker', 'end_date')],
             [State('date-range-type-store', 'data')],
            prevent_initial_call=False
        )
        def update_button_styles(*args):
            """Update button styles based on which button was clicked or date picker changed."""
            import dash
            ctx = dash.callback_context

            # Extract the date range type state from the last argument
            date_range_type = args[-1] if args else None

            # Define all buttons and their default styles
            buttons = ['btn-latest', 'btn-this-month', 'btn-last-month', 'btn-this-week',
                      'btn-last-week', 'btn-last-30-days', 'btn-last-7-days']

            # On initial call (no triggers), default to Latest mode active
            if not ctx.triggered:
                result = []
                for button in buttons:
                    if button == 'btn-latest':
                        # Latest button active by default
                        result.extend([False, 'primary'])  # outline=False, color='primary'
                    else:
                        # Other buttons inactive
                        result.extend([True, 'secondary'])  # outline=True, color='secondary'
                return result

            # Get what was triggered
            triggered_prop = ctx.triggered[0]['prop_id'].split('.')[0]

            # Build the return values (outline, color pairs for each button)
            result = []

            # Handle different trigger types
            if triggered_prop == 'date-range-picker':
                # If date picker was manually changed, make all buttons inactive
                for button in buttons:
                    result.extend([True, 'secondary'])  # All buttons outlined secondary
            elif triggered_prop == 'interval-component':
                # Auto-refresh triggered - preserve current state based on date range type
                if date_range_type and date_range_type.get('type') == 'latest':
                    # Keep Latest button active during auto-refresh
                    for button in buttons:
                        if button == 'btn-latest':
                            result.extend([False, 'primary'])  # Latest active
                        else:
                            result.extend([True, 'secondary'])  # Others inactive
                else:
                    # For non-latest modes during auto-refresh, don't change button states
                    import dash
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
            else:
                # A button was clicked - determine which one should be active
                clicked_button = triggered_prop

                # If the date range type indicates we're in latest mode, keep latest button active
                # This handles cases where auto-refresh or other triggers might reset button states
                if date_range_type and date_range_type.get('type') == 'latest' and clicked_button.startswith('btn-'):
                    active_button = clicked_button
                else:
                    active_button = clicked_button

                for button in buttons:
                    if button == active_button:
                        # Active button: solid primary color
                        result.extend([False, 'primary'])  # outline=False, color='primary'
                    else:
                        # Inactive buttons: outlined secondary color
                        result.extend([True, 'secondary'])  # outline=True, color='secondary'

            return result

        @callback(
            [Output('date-range-type-store', 'data'),
             Output('interval-component', 'interval'),
             Output('interval-component', 'disabled')],
            [Input('btn-latest', 'n_clicks'),
             Input('btn-this-month', 'n_clicks'),
             Input('btn-last-month', 'n_clicks'),
             Input('btn-this-week', 'n_clicks'),
             Input('btn-last-week', 'n_clicks'),
             Input('btn-last-30-days', 'n_clicks'),
             Input('btn-last-7-days', 'n_clicks'),
             Input('btn-apply-dates', 'n_clicks')],
            [State('date-range-picker', 'start_date'),
             State('date-range-picker', 'end_date')],
            prevent_initial_call=True
        )
        def update_auto_refresh_settings(*args):
            """Update auto-refresh settings based on selected date range."""
            import dash
            ctx = dash.callback_context

            if not ctx.triggered:
                return dash.no_update, dash.no_update, dash.no_update

            trigger_prop = ctx.triggered[0]['prop_id']

            # Check if Latest button was clicked
            if 'btn-latest' in trigger_prop:
                logger.info("Latest range selected - enabling frequent auto-refresh")
                return (
                    {'type': 'latest'},
                    1800000,  # 30 minutes = 1800000 milliseconds (more frequent for rolling data)
                    False  # Enable auto-refresh
                )

            # For any other button or manual date picker change, use default settings
            elif any(btn in trigger_prop for btn in ['btn-', 'date-range-picker']):
                logger.info("Non-latest range selected - using default auto-refresh")
                return (
                    {'type': 'default'},
                    self.refresh_interval,  # Use default refresh interval (5 minutes)
                    not self.auto_refresh  # Use default auto-refresh setting
                )

            return dash.no_update, dash.no_update, dash.no_update

        @callback(
            Output('latest-spinner', 'style'),
            [Input('date-range-type-store', 'data')],
            prevent_initial_call=False
        )
        def update_latest_spinner(date_range_type):
            """Control spinner visibility for Latest mode - always visible when Latest is enabled."""
            # Show spinner whenever Latest mode is enabled
            is_latest_mode = date_range_type and date_range_type.get('type') == 'latest'

            if is_latest_mode:
                logger.info("Latest mode enabled - showing spinner")
                return {"marginLeft": "8px", "display": "inline-block", "animation": "spin 1s linear infinite"}
            else:
                logger.info("Latest mode disabled - hiding spinner")
                return {"marginLeft": "8px", "display": "none", "animation": "none"}

            # Note: All dashboard callbacks have been set up successfully

    async def run(self):
        """Initialize and run the dashboard."""
        try:
            print("🔧 Initializing data manager...")
            init_start = time.time()
            await self.data_manager.initialize()
            init_time = time.time() - init_start
            print(f"✅ Data manager initialized in {init_time:.3f}s")
            print(f"🚀 Starting dashboard on {self.host}:{self.port}")


            # Use app.run instead of run_server for newer Dash versions
            self.app.run(
                host=self.host,
                port=self.port,
                debug=self.debug
            )

        except Exception as e:
            logger.error(f"Failed to start dashboard: {e}")
            raise


async def main():
    """Main entry point for the dashboard."""
    # Configure logging to see all the debug output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Set specific loggers to INFO level for debugging
    logging.getLogger('dashboard').setLevel(logging.INFO)
    logging.getLogger(__name__).setLevel(logging.INFO)

    logger.info("🚀 Starting dashboard with enhanced debug logging")

    if not DASH_AVAILABLE:
        logger.error("Error: Dashboard requires Dash and Plotly. Install with:")
        logger.error("pip install dash plotly dash-bootstrap-components")
        return

    try:
        config = get_config()
        dashboard = CostMonitorDashboard(config)
        await dashboard.run()

    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise


if __name__ == '__main__':
    asyncio.run(main())