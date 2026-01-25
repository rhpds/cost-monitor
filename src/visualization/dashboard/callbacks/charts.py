"""
Chart-related callbacks for the dashboard.

Handles all chart generation and updates including cost trends,
provider breakdowns, service breakdowns, and account visualizations.
"""

import logging
import time
from datetime import date

import plotly.graph_objects as go
from dash import Input, Output

from ..themes import DashboardTheme

logger = logging.getLogger(__name__)


def setup_chart_callbacks(dashboard):
    """Set up all chart-related callbacks."""
    _setup_cost_trend_chart_callback(dashboard)
    _setup_provider_breakdown_callback(dashboard)
    _setup_service_breakdown_callback(dashboard)


def _setup_cost_trend_chart_callback(dashboard):
    """Set up cost trend chart callback."""

    @dashboard.app.callback(
        Output("cost-trend-chart", "figure"),
        [Input("cost-data-store", "data"), Input("provider-selector", "value")],
    )
    def update_cost_trend_chart(cost_data, selected_provider):
        """Update the cost trend chart."""
        logger.info(f"📊 CHART CALLBACK: Cost trend chart triggered - provider: {selected_provider}")
        chart_start_time = time.time()

        # Return loading chart if no data
        if not cost_data or "daily_costs" not in cost_data:
            logger.warning("📊 CHART DEBUG: Returning loading chart - no data or no daily_costs")
            return _create_loading_chart("Daily Costs by Provider")

        # Get daily costs data
        daily_costs = cost_data["daily_costs"]
        if not daily_costs:
            return _create_loading_chart("Daily Costs by Provider")

        # Create the chart figure
        fig = go.Figure()

        # Extract dates for x-axis
        dates = [item["date"] for item in daily_costs]
        today_str = date.today().strftime("%Y-%m-%d")

        if selected_provider == "all":
            # Create grouped bar chart for all providers
            _add_all_providers_traces(fig, daily_costs, dates, today_str)
        else:
            # Show selected provider only
            _add_single_provider_trace(
                fig, daily_costs, dates, selected_provider, today_str, dashboard
            )

        # Update layout
        _update_chart_layout(fig, selected_provider)

        chart_time = time.time() - chart_start_time
        logger.info(f"📊 Cost trend chart updated in {chart_time:.3f}s")

        return fig


def _create_loading_chart(title):
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


def _add_all_providers_traces(fig, daily_costs, dates, today_str):
    """Add traces for all providers to the chart."""
    providers = ["aws", "azure", "gcp"]

    # Pre-calculate if we'll need log scale
    all_values = []
    for provider in providers:
        values = [item.get(provider, 0) for item in daily_costs]
        all_values.extend([v for v in values if v > 0])

    # Determine if log scale is needed
    will_use_log_scale = False
    if len(all_values) > 1:
        ratio = max(all_values) / min(all_values) if min(all_values) > 0 else 1
        will_use_log_scale = ratio > 50

    for provider in providers:
        values = [item.get(provider, 0) for item in daily_costs]

        # Prepare display values and text labels
        display_values = []
        hover_values = []
        text_labels = []

        for _, (item, value) in enumerate(zip(daily_costs, values, strict=False)):
            is_today = item["date"] == today_str

            if provider == "aws" and is_today:
                # Special handling for AWS today's data
                display_values.append(0.01 if will_use_log_scale else 0)
                hover_values.append(0)
                text_labels.append("N/A")
            else:
                display_value = max(value, 0.01) if will_use_log_scale and value <= 0 else value
                display_values.append(display_value)
                hover_values.append(value)
                text_labels.append(f"${value:.0f}" if value >= 1 else f"${value:.2f}")

        fig.add_trace(
            go.Bar(
                x=dates,
                y=display_values,
                name=provider.upper(),
                marker_color=DashboardTheme.COLORS.get(provider, "#000000"),
                marker_line=dict(width=1, color="rgba(0,0,0,0.3)"),
                text=text_labels,
                textposition="outside",
                textfont=dict(size=14, color="black"),
                hovertemplate=f"<b>{provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{customdata:.2f}}<extra></extra>",
                customdata=hover_values,
            )
        )


def _add_single_provider_trace(fig, daily_costs, dates, selected_provider, today_str, dashboard):
    """Add trace for a single selected provider."""
    values = [item.get(selected_provider, 0) for item in daily_costs]

    # Handle AWS specially when it's the selected provider
    if selected_provider == "aws":
        display_values = []
        hover_values = []
        text_labels = []

        for _, (item, value) in enumerate(zip(daily_costs, values, strict=False)):
            is_today = item["date"] == today_str
            if is_today:
                # For today's AWS data, show minimal bar and "N/A" text
                display_values.append(0.01)  # Minimal bar for log scale
                hover_values.append(0)  # Show $0 in hover
                text_labels.append("N/A")
            else:
                display_values.append(max(value, 0.01))  # Normal handling
                hover_values.append(value)
                text_labels.append(
                    dashboard._format_currency_compact(value) if value > 0 else "$0.00"
                )

        fig.add_trace(
            go.Bar(
                x=dates,
                y=display_values,
                name=selected_provider.upper(),
                marker_color=DashboardTheme.COLORS.get(selected_provider, "#007bff"),
                text=text_labels,
                textposition="outside",
                hovertemplate=f"<b>{selected_provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{customdata:.2f}}<extra></extra>",
                customdata=hover_values,
            )
        )
    else:
        # Normal handling for other providers
        fig.add_trace(
            go.Bar(
                x=dates,
                y=values,
                name=selected_provider.upper(),
                marker_color=DashboardTheme.COLORS.get(selected_provider, "#007bff"),
                text=[dashboard._format_currency_compact(v) for v in values],
                textposition="outside",
                hovertemplate=f"<b>{selected_provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{y:.2f}}<extra></extra>",
            )
        )


def _update_chart_layout(fig, selected_provider):
    """Update the chart layout with appropriate styling."""
    title = (
        f"Daily Costs - {selected_provider.upper()}"
        if selected_provider != "all"
        else "Daily Costs by Provider"
    )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Cost ($)",
        **DashboardTheme.LAYOUT,
        hovermode="x unified",
        showlegend=selected_provider == "all",
        barmode="group" if selected_provider == "all" else "relative",
        xaxis=dict(
            tickmode="linear",
            dtick="D1" if len(fig.data[0].x if fig.data else []) <= 31 else "D7",
            tickangle=-45,
        ),
        yaxis=dict(
            tickformat="$,.0f",
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )


def _setup_provider_breakdown_callback(dashboard):
    """Set up provider breakdown chart callback."""

    @dashboard.app.callback(
        Output("provider-breakdown-chart", "figure"), [Input("cost-data-store", "data")]
    )
    def update_provider_breakdown_chart(cost_data):
        """Update the provider breakdown pie chart."""
        if not cost_data:
            return _create_loading_chart("Provider Breakdown")

        provider_breakdown = cost_data.get("provider_breakdown", {})

        if not provider_breakdown:
            return _create_loading_chart("Provider Breakdown")

        # Filter out zero values
        filtered_breakdown = {k: v for k, v in provider_breakdown.items() if v > 0}

        if not filtered_breakdown:
            return _create_loading_chart("Provider Breakdown")

        # Create pie chart
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=[provider.upper() for provider in filtered_breakdown],
                    values=list(filtered_breakdown.values()),
                    hole=0.4,
                    marker_colors=[
                        DashboardTheme.COLORS.get(provider, "#000000")
                        for provider in filtered_breakdown
                    ],
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Cost: $%{value:,.2f}<br>Percentage: %{percent}<extra></extra>",
                )
            ]
        )

        fig.update_layout(
            title="Cost by Provider",
            **DashboardTheme.LAYOUT,
            annotations=[
                dict(
                    text=f"Total<br>${sum(filtered_breakdown.values()):,.0f}",
                    x=0.5,
                    y=0.5,
                    font_size=14,
                    showarrow=False,
                )
            ],
        )

        return fig


def _setup_service_breakdown_callback(dashboard):
    """Set up service breakdown chart callback."""

    @dashboard.app.callback(
        Output("service-breakdown-chart", "figure"),
        [Input("cost-data-store", "data"), Input("service-provider-selector", "value")],
    )
    def update_service_breakdown_chart(cost_data, selected_provider):
        """Update the service breakdown chart."""
        if not cost_data or not selected_provider:
            return _create_loading_chart("Service Breakdown")

        # For now, return a placeholder
        # This would be populated with actual service data
        return _create_loading_chart(f"{selected_provider.upper()} Services")
