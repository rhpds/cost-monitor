"""
Multi-cloud cost monitoring dashboard - modular implementation.

This is the new modular version of the dashboard that replaces
the monolithic dashboard.py implementation.
"""

# Import the main dashboard class from the modular implementation
from .dashboard.core import CostMonitorDashboard
from .dashboard.data_manager import CostDataManager
from .dashboard.themes import DashboardTheme
from .dashboard.utils import ChartMemoizer, DataWrapper, PerformanceMonitor


# For backward compatibility, export the main function
async def main():
    """Main entry point for the dashboard."""
    # Configure logging to see all the debug output
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Set specific loggers to INFO level for debugging
    logging.getLogger("dashboard").setLevel(logging.INFO)
    logging.getLogger(__name__).setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting dashboard with enhanced debug logging")

    try:
        from src.config.settings import get_config

        config = get_config()
        dashboard = CostMonitorDashboard(config)
        await dashboard.run()

    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise


# Export commonly used classes for compatibility
__all__ = [
    "CostMonitorDashboard",
    "DashboardTheme",
    "DataWrapper",
    "ChartMemoizer",
    "PerformanceMonitor",
    "CostDataManager",
    "main",
]
