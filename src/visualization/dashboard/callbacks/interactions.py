"""
User interaction callbacks for the dashboard.

Handles button clicks, loading states, search functionality,
and other user interface interactions.
"""

import logging

from dash import Input, Output, State, html

logger = logging.getLogger(__name__)


def setup_interaction_callbacks(dashboard):
    """Set up all user interaction callbacks."""
    _setup_loading_callbacks(dashboard)
    _setup_button_style_callbacks(dashboard)
    _setup_search_callbacks(dashboard)
    _setup_export_callbacks(dashboard)


def _setup_loading_callbacks(dashboard):
    """Set up loading state callbacks."""

    @dashboard.app.callback(
        Output("loading-store", "data", allow_duplicate=True),
        [
            Input("btn-apply-dates", "n_clicks"),
            Input("btn-latest", "n_clicks"),
            Input("btn-this-month", "n_clicks"),
            Input("btn-last-month", "n_clicks"),
            Input("btn-this-week", "n_clicks"),
            Input("btn-last-week", "n_clicks"),
            Input("btn-last-30-days", "n_clicks"),
            Input("btn-last-7-days", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def trigger_loading_state(*args):
        """Trigger loading state when buttons are clicked."""
        return {"loading": True}

    @dashboard.app.callback(
        Output("loading-banner", "children"),
        [
            Input("loading-store", "data"),
            Input("cost-data-store", "data"),
            State("date-range-picker", "start_date"),
            State("date-range-picker", "end_date"),
        ],
    )
    def update_loading_banner(loading_data, cost_data, start_date, end_date):
        """Update loading banner display."""
        if loading_data and loading_data.get("loading"):
            return html.Div(
                [
                    html.I(className="fa fa-spinner fa-spin me-2"),
                    f"Loading cost data for {start_date or 'current month'} to {end_date or 'today'}...",
                ],
                className="alert alert-info mb-3",
            )
        return ""


def _setup_button_style_callbacks(dashboard):
    """Set up button styling callbacks."""

    @dashboard.app.callback(
        [
            Output("btn-latest", "color"),
            Output("btn-this-month", "color"),
            Output("btn-last-month", "color"),
            Output("btn-this-week", "color"),
            Output("btn-last-week", "color"),
            Output("btn-last-30-days", "color"),
            Output("btn-last-7-days", "color"),
        ],
        [
            Input("btn-latest", "n_clicks"),
            Input("btn-this-month", "n_clicks"),
            Input("btn-last-month", "n_clicks"),
            Input("btn-this-week", "n_clicks"),
            Input("btn-last-week", "n_clicks"),
            Input("btn-last-30-days", "n_clicks"),
            Input("btn-last-7-days", "n_clicks"),
        ],
    )
    def update_button_styles(*args):
        """Update button styles based on selection."""
        import dash

        ctx = dash.callback_context
        if not ctx.triggered:
            return _get_initial_button_styles()

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Reset all buttons to outline style
        styles = ["outline-secondary"] * 7

        # Highlight the active button
        button_map = {
            "btn-latest": 0,
            "btn-this-month": 1,
            "btn-last-month": 2,
            "btn-this-week": 3,
            "btn-last-week": 4,
            "btn-last-30-days": 5,
            "btn-last-7-days": 6,
        }

        if triggered_id in button_map:
            styles[button_map[triggered_id]] = "primary"

        return styles


def _get_initial_button_styles():
    """Get initial button styles with 'This Month' highlighted."""
    styles = ["outline-secondary"] * 7
    styles[1] = "primary"  # This Month button
    return styles


def _setup_search_callbacks(dashboard):
    """Set up search and filter callbacks."""

    @dashboard.app.callback(
        Output("account-search-toggle", "color"), [Input("account-search-toggle", "n_clicks")]
    )
    def toggle_account_search(n_clicks):
        """Toggle account search visibility."""
        if n_clicks and n_clicks % 2 == 1:
            return "primary"
        return "outline-secondary"


def _setup_export_callbacks(dashboard):
    """Set up data export callbacks."""

    @dashboard.app.callback(
        Output("account-export-csv", "color"), [Input("account-export-csv", "n_clicks")]
    )
    def handle_account_export(n_clicks):
        """Handle account data export."""
        if n_clicks:
            logger.info("Account data export requested")
            # Export logic would go here
            return "success"
        return "outline-success"

    @dashboard.app.callback(
        Output("account-chart-view", "color"), [Input("account-chart-view", "n_clicks")]
    )
    def handle_account_chart_view(n_clicks):
        """Handle account chart view toggle."""
        if n_clicks:
            logger.info("Account chart view toggled")
            # Chart view logic would go here
            return "primary"
        return "outline-primary"
