"""
Dashboard theme configuration and styling.

Provides centralized color schemes and layout configurations
for consistent styling across all dashboard components.
"""


class DashboardTheme:
    """Dashboard theme configuration - Tokyonight dark theme."""

    COLORS = {
        "primary": "#7aa2f7",
        "secondary": "#bb9af7",
        "success": "#9ece6a",
        "warning": "#e0af68",
        "danger": "#f7768e",
        "info": "#7dcfff",
        "light": "#24283b",
        "dark": "#1a1b26",
        "aws": "#ff9e64",
        "azure": "#7aa2f7",
        "gcp": "#9ece6a",
        "background": "#1a1b26",
        "surface": "#24283b",
        "text": "#c0caf5",
        "text_muted": "#565f89",
        "border": "#3b4261",
        "accent": "#7aa2f7",
        "accent_dim": "#3d59a1",
    }

    CHART_COLORS = [
        "#7aa2f7",
        "#9ece6a",
        "#e0af68",
        "#f7768e",
        "#bb9af7",
        "#7dcfff",
        "#73daca",
        "#ff9e64",
        "#c0caf5",
        "#a9b1d6",
    ]

    LAYOUT = {
        "margin": {"l": 20, "r": 20, "t": 40, "b": 20},
        "font_family": '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
        "font_size": 12,
        "paper_bgcolor": "#1a1b26",
        "plot_bgcolor": "#1a1b26",
        "font_color": "#c0caf5",
    }
