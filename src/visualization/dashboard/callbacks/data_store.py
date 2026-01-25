"""
Data store callbacks for the dashboard.

Handles main data fetching, caching, and store management.
This module contains the core data pipeline callbacks.
"""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta

import dash
from dash import Input, Output, State, html

from ..utils import DataWrapper

logger = logging.getLogger(__name__)


def setup_data_store_callbacks(dashboard):
    """Set up data store related callbacks."""
    _setup_main_data_callback(dashboard)
    _setup_key_metrics_callback(dashboard)
    _setup_alert_banner_callback(dashboard)


def _setup_main_data_callback(dashboard):
    """Set up the main data store callback."""

    @dashboard.app.callback(
        [
            Output("cost-data-store", "data"),
            Output("alert-data-store", "data"),
            Output("last-update-time", "children"),
            Output("loading-store", "data"),
        ],
        [
            Input("interval-component", "n_intervals"),
            Input("btn-apply-dates", "n_clicks"),
            Input("btn-latest", "n_clicks"),
            Input("btn-this-month", "n_clicks"),
            Input("btn-last-month", "n_clicks"),
            Input("btn-this-week", "n_clicks"),
            Input("btn-last-week", "n_clicks"),
            Input("btn-last-30-days", "n_clicks"),
            Input("btn-last-7-days", "n_clicks"),
        ],
        [State("date-range-picker", "start_date"), State("date-range-picker", "end_date")],
        prevent_initial_call=False,
    )
    def update_data_store(
        n_intervals,
        apply_clicks,
        latest_clicks,
        this_month_clicks,
        last_month_clicks,
        this_week_clicks,
        last_week_clicks,
        last_30_clicks,
        last_7_clicks,
        start_date_picker,
        end_date_picker,
    ):
        """Update the main data store."""
        try:
            ctx = dash.callback_context

            # Determine date range based on button clicked
            start_date_obj, end_date_obj = _determine_date_range(
                ctx, dashboard, start_date_picker, end_date_picker
            )

            # Start performance monitoring for data fetch
            dashboard.performance_monitor.start_operation("data_fetch")

            # Get real cost data using the data manager
            real_cost_data = _fetch_cost_data(dashboard, start_date_obj, end_date_obj)

            # Transform data for dashboard consumption
            transformed_data = _transform_cost_data(real_cost_data)

            # Get alert data
            alert_data = _get_alert_data(dashboard, real_cost_data)

            # Create update timestamp
            update_time = _create_update_timestamp()

            # End performance monitoring
            dashboard.performance_monitor.end_operation("data_fetch")

            return transformed_data, alert_data, update_time, {"loading": False}

        except Exception as e:
            logger.error(f"Error in main callback: {e}")
            # Return proper empty data structure and ALWAYS clear loading state on error
            empty_cost_data = {
                "total_cost": 0.0,
                "provider_breakdown": {},
                "daily_costs": [],
                "service_breakdown": {},
                "account_breakdown": {},
            }
            empty_alert_data = {"active_alerts": 0, "critical_alerts": 0, "alerts": []}
            error_div = html.Div([f"❌ Error: {str(e)}"], className="error-message")
            return empty_cost_data, empty_alert_data, error_div, {"loading": False}


def _determine_date_range(ctx, dashboard, start_date_picker, end_date_picker):
    """Determine the date range based on the triggered button."""
    today = date.today()
    # Use 2 days ago as safe end date since AWS Cost Explorer data has 1-2 day delay
    safe_end_date = today - timedelta(days=2)
    triggered_prop = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None

    logger.info(f"🔘 BUTTON DEBUG: Triggered by {triggered_prop}")

    if triggered_prop == "btn-latest" or triggered_prop == "btn-this-month":
        start_date_obj = dashboard._get_month_start(today)
        end_date_obj = safe_end_date
    elif triggered_prop == "btn-last-month":
        start_date_obj, end_date_obj = dashboard._get_last_month()
    elif triggered_prop == "btn-this-week":
        start_date_obj = dashboard._get_week_start(today)
        end_date_obj = safe_end_date
    elif triggered_prop == "btn-last-week":
        start_date_obj, end_date_obj = dashboard._get_last_week()
    elif triggered_prop == "btn-last-30-days":
        start_date_obj = today - timedelta(days=30)
        end_date_obj = safe_end_date
    elif triggered_prop == "btn-last-7-days":
        start_date_obj = today - timedelta(days=7)
        end_date_obj = safe_end_date
    elif triggered_prop == "btn-apply-dates":
        # Use date picker values for Apply button
        if start_date_picker and end_date_picker:
            start_date_obj = datetime.strptime(start_date_picker, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date_picker, "%Y-%m-%d").date()
        else:
            # Fallback if date picker values are missing
            start_date_obj = dashboard._get_month_start(today)
            end_date_obj = safe_end_date
    elif triggered_prop == "interval-component":
        # Auto-refresh: use This Month for consistency
        start_date_obj = dashboard._get_month_start(today)
        end_date_obj = safe_end_date
    else:
        # Default case or initial load
        start_date_obj = dashboard._get_month_start(today)
        end_date_obj = safe_end_date

    return start_date_obj, end_date_obj


def _fetch_cost_data(dashboard, start_date_obj, end_date_obj):
    """Fetch cost data from the data manager."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    data_manager = dashboard.data_manager

    # Quick cache check to avoid unnecessary loading screens
    cache_key = data_manager._get_cache_key(start_date_obj, end_date_obj, False)
    cached_data = None

    # Quick cache check to avoid unnecessary loading screens
    if data_manager._dashboard_cache:
        try:
            cached_data = data_manager._dashboard_cache.get(cache_key)
            if cached_data:
                logger.info(f"🎯 CACHE HIT: {start_date_obj} to {end_date_obj}")
                real_cost_data = DataWrapper(cached_data)
                data_fetch_time = 0.001  # Near-instant cache hit
                return real_cost_data
        except Exception as e:
            logger.warning(f"Cache check failed: {e}")

    if not cached_data:
        logger.info(f"Cache miss - fetching data from API for {start_date_obj} to {end_date_obj}")

        async def fetch_data():
            return await data_manager.get_cost_data(
                start_date_obj, end_date_obj, force_refresh=False
            )

        data_fetch_start = time.time()
        real_cost_data = loop.run_until_complete(fetch_data())
        data_fetch_time = time.time() - data_fetch_start
        logger.info(f"Data fetch completed in {data_fetch_time:.2f}s")
    else:
        # Use cached data
        real_cost_data = cached_data

    return real_cost_data


def _transform_cost_data(real_cost_data):
    """Transform cost data for dashboard consumption."""
    if not real_cost_data:
        return {
            "total_cost": 0.0,
            "provider_breakdown": {},
            "daily_costs": [],
            "service_breakdown": {},
            "account_breakdown": {},
        }

    # Extract data from DataWrapper or dict
    if hasattr(real_cost_data, "total_cost"):
        total_cost = real_cost_data.total_cost
        provider_breakdown = getattr(real_cost_data, "provider_breakdown", {})
        daily_costs = getattr(real_cost_data, "combined_daily_costs", [])
        account_breakdown = getattr(real_cost_data, "account_breakdown", {})
    else:
        total_cost = real_cost_data.get("total_cost", 0.0)
        provider_breakdown = real_cost_data.get("provider_breakdown", {})
        daily_costs = real_cost_data.get("combined_daily_costs", [])
        account_breakdown = real_cost_data.get("account_breakdown", {})

    return {
        "total_cost": total_cost,
        "provider_breakdown": provider_breakdown,
        "daily_costs": daily_costs,
        "service_breakdown": {},  # Will be populated by other callbacks
        "account_breakdown": account_breakdown,
    }


def _get_alert_data(dashboard, cost_data):
    """Get alert data based on current cost data."""
    # Placeholder for alert logic
    return {"active_alerts": 0, "critical_alerts": 0, "alerts": []}


def _create_update_timestamp():
    """Create an update timestamp display."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return html.Div([html.Small(f"Last updated: {current_time}", className="text-muted")])


def _setup_key_metrics_callback(dashboard):
    """Set up key metrics callback."""

    @dashboard.app.callback(
        [
            Output("total-cost-metric", "children"),
            Output("daily-average-metric", "children"),
            Output("monthly-projection-metric", "children"),
            Output("cost-trend-metric", "children"),
            Output("cost-trend-metric", "className"),
        ],
        [Input("cost-data-store", "data"), Input("provider-selector", "value")],
    )
    def update_key_metrics(cost_data, selected_provider):
        """Update key metrics display."""
        if not cost_data:
            return "$0.00", "$0.00", "$0.00", "0.0%", "text-muted"

        total_cost = cost_data.get("total_cost", 0)
        daily_costs = cost_data.get("daily_costs", [])

        # Calculate daily average
        daily_average = total_cost / len(daily_costs) if daily_costs else 0

        # Calculate monthly projection (30 days)
        monthly_projection = daily_average * 30

        # Calculate trend (simplified)
        trend_percentage = 0.0
        trend_class = "text-success"

        if len(daily_costs) > 1:
            recent_avg = sum(day.get("total", 0) for day in daily_costs[-7:]) / min(
                7, len(daily_costs)
            )
            earlier_avg = sum(day.get("total", 0) for day in daily_costs[:-7]) / max(
                1, len(daily_costs) - 7
            )
            if earlier_avg > 0:
                trend_percentage = ((recent_avg - earlier_avg) / earlier_avg) * 100
                trend_class = "text-danger" if trend_percentage > 0 else "text-success"

        trend_text = (
            f"+{trend_percentage:.1f}%" if trend_percentage > 0 else f"{trend_percentage:.1f}%"
        )

        return (
            f"${total_cost:,.2f}",
            f"${daily_average:,.2f}",
            f"${monthly_projection:,.2f}",
            trend_text,
            trend_class,
        )


def _setup_alert_banner_callback(dashboard):
    """Set up alert banner callback."""

    @dashboard.app.callback(Output("alert-banner", "children"), [Input("alert-data-store", "data")])
    def update_alert_banner(alert_data):
        """Update alert banner."""
        if not alert_data or alert_data.get("active_alerts", 0) == 0:
            return ""

        total_count = alert_data.get("active_alerts", 0)
        critical_count = alert_data.get("critical_alerts", 0)

        alert_type = "danger" if critical_count > 0 else "warning"

        return html.Div(
            [
                html.I(className="fa fa-exclamation-triangle me-2"),
                f"{total_count} active alert{'s' if total_count != 1 else ''}"
                + (f" ({critical_count} critical)" if critical_count > 0 else ""),
            ],
            className=f"alert alert-{alert_type} mb-3",
        )
