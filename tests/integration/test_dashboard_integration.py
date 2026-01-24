"""
Dashboard integration tests.

Tests the Dash dashboard functionality including data loading,
chart generation, and interactive components.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

# Dashboard imports with availability check
try:
    import dash
    from dash.testing.application_runners import import_app
    from selenium.webdriver.chrome.options import Options

    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False


# Skip all dashboard tests if Dash is not available
pytestmark = pytest.mark.skipif(not DASH_AVAILABLE, reason="Dash not available")


class TestDashboardInitialization:
    """Test dashboard initialization and configuration."""

    def test_dashboard_app_creation(self, test_config):
        """Test dashboard app can be created with configuration."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            assert dashboard.config == test_config
            assert dashboard.app is not None
            assert dashboard.host == test_config.get("dashboard", {}).get("host", "0.0.0.0")
            assert dashboard.port == test_config.get("dashboard", {}).get("port", 8050)

    def test_dashboard_theme_application(self, test_config):
        """Test that dashboard themes are properly applied."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            # Verify external stylesheets are applied
            assert dashboard.app.external_stylesheets is not None
            # Should include Bootstrap and Font Awesome
            stylesheets = [str(s) for s in dashboard.app.external_stylesheets]
            assert any("bootstrap" in s.lower() for s in stylesheets)

    def test_dashboard_data_manager_initialization(self, test_config):
        """Test data manager initialization."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            with patch(
                "src.visualization.dashboard.data_manager.CostDataManager"
            ) as mock_data_manager:
                dashboard = CostMonitorDashboard(test_config)

                mock_data_manager.assert_called_once_with(test_config)
                assert dashboard.data_manager is not None

    def test_dashboard_callback_setup(self, test_config):
        """Test that callbacks are properly set up."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            with patch(
                "src.visualization.dashboard.callbacks.data_store.setup_data_store_callbacks"
            ) as mock_data_callbacks, patch(
                "src.visualization.dashboard.callbacks.charts.setup_chart_callbacks"
            ) as mock_chart_callbacks, patch(
                "src.visualization.dashboard.callbacks.interactions.setup_interaction_callbacks"
            ) as mock_interaction_callbacks:
                dashboard = CostMonitorDashboard(test_config)

                mock_data_callbacks.assert_called_once()
                mock_chart_callbacks.assert_called_once()
                mock_interaction_callbacks.assert_called_once()


class TestDashboardDataManager:
    """Test dashboard data management functionality."""

    @pytest.mark.asyncio
    async def test_data_manager_initialization(self, test_config, mock_auth_manager):
        """Test data manager initialization with providers."""
        from src.visualization.dashboard.data_manager import CostDataManager

        with patch(
            "src.visualization.dashboard.data_manager.MultiCloudAuthManager",
            return_value=mock_auth_manager,
        ):
            data_manager = CostDataManager(test_config)

            await data_manager.initialize()

            assert data_manager.config == test_config
            assert data_manager.auth_manager is not None

    @pytest.mark.asyncio
    async def test_data_manager_fetch_cost_data(self, test_config, mock_auth_manager):
        """Test fetching cost data through data manager."""
        from src.visualization.dashboard.data_manager import CostDataManager

        with patch(
            "src.visualization.dashboard.data_manager.MultiCloudAuthManager",
            return_value=mock_auth_manager,
        ):
            data_manager = CostDataManager(test_config)

            # Mock provider responses
            mock_auth_manager.get_enabled_providers.return_value = ["aws", "azure"]

            with patch(
                "src.providers.base.ProviderFactory.create_provider"
            ) as mock_create_provider:
                mock_provider = MagicMock()
                mock_provider.authenticate.return_value = True
                mock_provider.get_cost_data.return_value = MagicMock(
                    total_cost=1000.0, currency="USD", data_points=[], provider="aws"
                )
                mock_create_provider.return_value = mock_provider

                await data_manager.initialize()

                # Test data fetching
                start_date = date(2024, 1, 1)
                end_date = date(2024, 1, 31)

                cost_data = await data_manager.fetch_cost_summary(start_date, end_date)

                assert cost_data is not None
                mock_auth_manager.get_enabled_providers.assert_called()

    @pytest.mark.asyncio
    async def test_data_manager_caching(self, test_config, mock_auth_manager):
        """Test data manager caching functionality."""
        from src.visualization.dashboard.data_manager import CostDataManager

        with patch(
            "src.visualization.dashboard.data_manager.MultiCloudAuthManager",
            return_value=mock_auth_manager,
        ):
            data_manager = CostDataManager(test_config)

            await data_manager.initialize()

            start_date = date(2024, 1, 1)
            end_date = date(2024, 1, 31)

            # Mock cache operations
            with patch.object(data_manager, "_cache_key") as mock_cache_key, patch.object(
                data_manager, "_get_from_cache"
            ) as mock_get_cache, patch.object(data_manager, "_set_cache") as mock_set_cache:
                mock_cache_key.return_value = "test_cache_key"
                mock_get_cache.return_value = None  # Cache miss

                # First call should fetch and cache
                await data_manager.fetch_cost_summary(start_date, end_date, use_cache=True)

                mock_get_cache.assert_called_once()
                # mock_set_cache should be called to store the result


class TestDashboardLayout:
    """Test dashboard layout components."""

    def test_layout_structure(self, test_config):
        """Test dashboard layout structure."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard
            from src.visualization.dashboard.layout import create_dashboard_layout

            dashboard = CostMonitorDashboard(test_config)
            layout = create_dashboard_layout(dashboard)

            assert layout is not None
            # Layout should be a Dash component
            assert hasattr(layout, "children") or hasattr(layout, "id")

    def test_layout_components_present(self, test_config):
        """Test that required layout components are present."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard
            from src.visualization.dashboard.layout import create_dashboard_layout

            dashboard = CostMonitorDashboard(test_config)
            layout = create_dashboard_layout(dashboard)

            # Convert layout to string to check for component presence
            layout_str = str(layout)

            # Check for key UI components
            expected_components = [
                "Multi-Cloud Cost Monitor",  # Header
                "Date Range",  # Date picker section
                "Key Metrics",  # Metrics row
                "Daily Cost Trends",  # Charts section
                "Provider Breakdown",
            ]

            for component in expected_components:
                assert component in layout_str, f"Missing component: {component}"

    def test_quick_date_buttons(self, test_config):
        """Test quick date selection buttons."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.layout import _create_quick_date_buttons

            buttons = _create_quick_date_buttons()

            assert buttons is not None
            buttons_str = str(buttons)

            # Check for expected quick date options
            expected_buttons = [
                "Latest",
                "This Month",
                "Last Month",
                "This Week",
                "Last Week",
                "Last 30 Days",
                "Last 7 Days",
            ]

            for button_text in expected_buttons:
                assert button_text in buttons_str, f"Missing button: {button_text}"


class TestDashboardUtils:
    """Test dashboard utility functions."""

    def test_date_range_debouncer(self):
        """Test date range debouncing functionality."""
        from src.visualization.dashboard.utils import DateRangeDebouncer

        debouncer = DateRangeDebouncer(delay=0.1)  # 100ms delay for testing

        # Test debouncing behavior
        callback_count = 0

        def test_callback(start_date, end_date):
            nonlocal callback_count
            callback_count += 1

        debouncer.set_callback(test_callback)

        # Multiple rapid calls should be debounced
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)

        debouncer.trigger(start_date, end_date)
        debouncer.trigger(start_date, end_date)
        debouncer.trigger(start_date, end_date)

        # Should have minimal immediate effect due to debouncing
        assert callback_count <= 1

    def test_chart_memoization(self):
        """Test chart memoization for performance."""
        from src.visualization.dashboard.utils import ChartMemoizer

        memoizer = ChartMemoizer(max_cache_size=3)

        # Mock chart creation function
        def create_test_chart(data_key, chart_type):
            return {"data": data_key, "type": chart_type, "created": datetime.now()}

        # Test memoization
        chart1 = memoizer.get_or_create("key1", "bar", create_test_chart)
        chart2 = memoizer.get_or_create("key1", "bar", create_test_chart)  # Should be cached

        assert chart1 is chart2  # Should return same object from cache

        # Test cache size limit
        chart3 = memoizer.get_or_create("key2", "line", create_test_chart)
        chart4 = memoizer.get_or_create("key3", "pie", create_test_chart)
        chart5 = memoizer.get_or_create("key4", "bar", create_test_chart)  # Should evict oldest

        assert len(memoizer._cache) <= 3

    def test_performance_monitoring(self):
        """Test performance monitoring utilities."""
        from src.visualization.dashboard.utils import PerformanceMonitor

        monitor = PerformanceMonitor()

        # Test timing functionality
        with monitor.time_operation("test_operation"):
            import time

            time.sleep(0.01)  # Small delay for testing

        # Check that timing was recorded
        assert "test_operation" in monitor.get_metrics()
        assert monitor.get_metrics()["test_operation"] > 0

    def test_currency_formatting(self, test_config):
        """Test currency formatting utilities."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            # Test compact currency formatting
            assert dashboard._format_currency_compact(1500) == "$1.5K"
            assert dashboard._format_currency_compact(1500000) == "$1.5M"
            assert dashboard._format_currency_compact(50.75) == "$50.75"

    def test_date_helper_methods(self, test_config):
        """Test date helper methods."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            # Test month start calculation
            test_date = date(2024, 1, 15)
            month_start = dashboard._get_month_start(test_date)
            assert month_start == date(2024, 1, 1)

            # Test last month range
            last_month_start, last_month_end = dashboard._get_last_month()
            assert last_month_start < last_month_end
            assert last_month_start.day == 1

            # Test week start calculation
            week_start = dashboard._get_week_start(test_date)
            assert week_start.weekday() == 0  # Monday

            # Test last week range
            last_week_start, last_week_end = dashboard._get_last_week()
            assert last_week_start < last_week_end
            assert last_week_start.weekday() == 0  # Monday
            assert last_week_end.weekday() == 6  # Sunday


class TestDashboardCharts:
    """Test dashboard chart generation."""

    def test_initial_loading_chart(self, test_config):
        """Test initial loading chart creation."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            loading_chart = dashboard._create_initial_loading_chart("Test Chart")

            assert loading_chart is not None
            # Should be a plotly figure
            assert hasattr(loading_chart, "data") or "data" in loading_chart

    def test_chart_theme_application(self, test_config):
        """Test that chart themes are properly applied."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.themes import DashboardTheme

            # Test theme constants
            assert hasattr(DashboardTheme, "LAYOUT")
            assert hasattr(DashboardTheme, "COLORS")

            # Theme should provide consistent styling
            layout_theme = DashboardTheme.LAYOUT
            assert isinstance(layout_theme, dict)


class TestDashboardIntegration:
    """Test full dashboard integration scenarios."""

    @pytest.mark.asyncio
    async def test_dashboard_with_real_data_flow(self, test_config, mock_auth_manager):
        """Test dashboard with simulated real data flow."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            # Mock data manager with real-like data
            mock_cost_summary = {
                "total_cost": 1250.50,
                "currency": "USD",
                "period_start": date(2024, 1, 1),
                "period_end": date(2024, 1, 31),
                "provider_breakdown": {"aws": 750.25, "azure": 300.15, "gcp": 200.10},
                "combined_daily_costs": [
                    {
                        "date": "2024-01-01",
                        "total_cost": 40.25,
                        "provider_breakdown": {"aws": 25.0, "azure": 15.25},
                    },
                    {
                        "date": "2024-01-02",
                        "total_cost": 38.75,
                        "provider_breakdown": {"aws": 23.50, "azure": 15.25},
                    },
                ],
            }

            with patch.object(CostMonitorDashboard, "data_manager") as mock_data_manager:
                mock_data_manager.fetch_cost_summary.return_value = mock_cost_summary

                dashboard = CostMonitorDashboard(test_config)

                # Test that dashboard can be initialized with data
                assert dashboard is not None
                assert dashboard.data_manager is not None

    def test_dashboard_error_handling(self, test_config):
        """Test dashboard error handling scenarios."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            # Test initialization with missing dependencies
            with patch(
                "src.visualization.dashboard.data_manager.CostDataManager"
            ) as mock_data_manager:
                mock_data_manager.side_effect = Exception("Data manager initialization failed")

                try:
                    dashboard = CostMonitorDashboard(test_config)
                    # Should handle initialization errors gracefully
                    assert dashboard is not None
                except Exception as e:
                    # Exception handling is acceptable
                    assert "initialization" in str(e).lower() or "data manager" in str(e).lower()

    def test_dashboard_configuration_validation(self, test_config):
        """Test dashboard configuration validation."""
        # Test with minimal configuration
        minimal_config = {"dashboard": {"host": "localhost", "port": 8050}}

        with patch("src.visualization.dashboard.core.get_config", return_value=minimal_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(minimal_config)

            assert dashboard.host == "localhost"
            assert dashboard.port == 8050
            # Should use defaults for missing configuration

        # Test with full configuration
        full_config = {
            "dashboard": {
                "host": "0.0.0.0",
                "port": 9000,
                "debug": True,
                "auto_refresh": True,
                "refresh_interval": 600,
            }
        }

        with patch("src.visualization.dashboard.core.get_config", return_value=full_config):
            dashboard = CostMonitorDashboard(full_config)

            assert dashboard.host == "0.0.0.0"
            assert dashboard.port == 9000
            assert dashboard.debug is True
            assert dashboard.auto_refresh is True
            assert dashboard.refresh_interval == 600000  # Converted to milliseconds


class TestDashboardPerformance:
    """Test dashboard performance characteristics."""

    def test_dashboard_memory_usage(self, test_config):
        """Test dashboard memory usage patterns."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            # Create multiple dashboard instances to test memory handling
            dashboards = []
            for i in range(3):
                dashboard = CostMonitorDashboard(test_config)
                dashboards.append(dashboard)

            # All should be independent instances
            assert len(dashboards) == 3
            assert all(d is not None for d in dashboards)

            # Cleanup should work properly
            del dashboards

    def test_chart_rendering_performance(self, test_config):
        """Test chart rendering performance."""
        with patch("src.visualization.dashboard.core.get_config", return_value=test_config):
            from src.visualization.dashboard.core import CostMonitorDashboard

            dashboard = CostMonitorDashboard(test_config)

            # Test chart creation performance
            import time

            start_time = time.time()

            # Create multiple charts
            charts = []
            for i in range(5):
                chart = dashboard._create_initial_loading_chart(f"Chart {i}")
                charts.append(chart)

            end_time = time.time()
            render_time = end_time - start_time

            # Should create charts reasonably quickly
            assert render_time < 1.0, f"Chart rendering took {render_time:.2f}s, expected < 1.0s"
            assert len(charts) == 5
