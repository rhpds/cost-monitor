"""
Dashboard theme configuration and styling.

Provides centralized color schemes and layout configurations
for consistent styling across all dashboard components.
"""


class DashboardTheme:
    """Dashboard theme configuration."""

    COLORS = {
        "primary": "#2E86AB",
        "secondary": "#A23B72",
        "success": "#F18F01",
        "warning": "#C73E1D",
        "danger": "#C73E1D",
        "info": "#17A2B8",
        "light": "#F8F9FA",
        "dark": "#343A40",
        "aws": "#FF9900",
        "azure": "#0078D4",
        "gcp": "#34A853",
        "background": "#FFFFFF",
        "surface": "#F8F9FA",
        "text": "#212529",
    }

    LAYOUT = {
        "margin": {"l": 20, "r": 20, "t": 40, "b": 20},
        "font_family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        "font_size": 12,
    }
