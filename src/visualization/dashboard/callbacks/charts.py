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


def _filter_savings_plans(daily_costs, cost_data):
    """Filter out Savings Plans and Reserved Instances from daily costs.

    This function identifies days with anomalous spikes (likely Savings Plan payments)
    and removes those costs to show operational spending trends.
    """
    # Calculate average AWS daily cost to identify spikes
    aws_costs = [day.get("provider_breakdown", {}).get("aws", 0) for day in daily_costs]

    if not aws_costs:
        return daily_costs

    # Sort to find median (more robust than mean for spike detection)
    sorted_costs = sorted(aws_costs)
    median_cost = sorted_costs[len(sorted_costs) // 2]

    # Calculate threshold: costs > 2x median are likely savings plan payments
    spike_threshold = median_cost * 2

    logger.info(
        f"💰 AWS median daily cost: ${median_cost:,.2f}, spike threshold: ${spike_threshold:,.2f}"
    )

    # Create a copy of daily_costs and cap spikes at threshold
    filtered_costs = []
    for day in daily_costs:
        day_copy = day.copy()
        day_copy["provider_breakdown"] = day["provider_breakdown"].copy()

        aws_cost = day_copy["provider_breakdown"].get("aws", 0)

        if aws_cost > spike_threshold:
            # Cap AWS cost at threshold (removes the savings plan spike)
            adjusted_aws = spike_threshold
            day_copy["provider_breakdown"]["aws"] = adjusted_aws

            # Recalculate total_cost
            day_copy["total_cost"] = sum(day_copy["provider_breakdown"].values())

            logger.info(
                f"📅 Adjusted {day['date']}: AWS ${aws_cost:,.2f} -> ${adjusted_aws:,.2f} "
                f"(removed ${aws_cost - adjusted_aws:,.2f} spike)"
            )

        filtered_costs.append(day_copy)

    return filtered_costs


def setup_chart_callbacks(dashboard):
    """Set up all chart-related callbacks."""
    _setup_cost_trend_chart_callback(dashboard)
    _setup_provider_breakdown_callback(dashboard)
    _setup_service_provider_selector_callback(dashboard)
    _setup_service_breakdown_callback(dashboard)


def _setup_cost_trend_chart_callback(dashboard):
    """Set up cost trend chart callback."""

    @dashboard.app.callback(
        Output("cost-trend-chart", "figure"),
        [
            Input("cost-data-store", "data"),
            Input("provider-selector", "value"),
            Input("include-savings-plans-toggle", "value"),
            Input("log-scale-toggle", "value"),
        ],
    )
    def update_cost_trend_chart(cost_data, selected_provider, include_savings_plans, log_scale):
        """Update the cost trend chart."""
        logger.info(
            f"📊 CHART CALLBACK: Cost trend chart triggered - provider: {selected_provider}, "
            f"include_savings_plans: {include_savings_plans}, log_scale: {log_scale}"
        )
        chart_start_time = time.time()

        # Return loading chart if no data
        if not cost_data or "daily_costs" not in cost_data:
            logger.warning("Returning loading chart - no data or no daily_costs")
            return _create_loading_chart("Daily Costs by Provider")

        # Get daily costs data
        daily_costs = cost_data["daily_costs"]
        if not daily_costs:
            logger.info("📊 CHART: No daily costs data - creating N/C/Y chart")
            return _create_no_data_chart("Daily Costs by Provider")

        # Filter out savings plans if toggle is unchecked
        include_sp = "include" in (include_savings_plans or [])
        if not include_sp:
            daily_costs = _filter_savings_plans(daily_costs, cost_data)

        # Check if log scale is enabled
        use_log_scale = "log" in (log_scale or [])

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
        _update_chart_layout(fig, selected_provider, use_log_scale)

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


def _create_no_data_chart(title):
    """Create a chart showing N/C/Y for all providers when no data is available."""
    from datetime import date

    no_data_fig = go.Figure()

    # Show N/C/Y bars for all providers
    providers = ["AWS", "Azure", "GCP"]
    colors = ["#ff9800", "#00bcd4", "#4caf50"]  # AWS orange, Azure cyan, GCP green
    today_str = date.today().strftime("%Y-%m-%d")

    for _, (provider, color) in enumerate(zip(providers, colors, strict=False)):
        no_data_fig.add_trace(
            go.Bar(
                x=[today_str],
                y=[0.5],  # Give it some height so text is visible
                name=provider,
                marker=dict(color=color, opacity=0.3),
                text=["N/C/Y"],
                textposition="inside",
                textfont=dict(size=14, color="gray"),
                hovertemplate=f"<b>{provider}</b><br>Date: %{{x}}<br>Cost: No Cost Yet<extra></extra>",
            )
        )

    no_data_fig.update_layout(
        title=title,
        xaxis_title="Date",
        barmode="group",
        **DashboardTheme.LAYOUT,
        yaxis=dict(range=[0, 1], title="Cost ($)"),  # Small range to show the N/C/Y text clearly
        annotations=[
            dict(
                text="N/C/Y = No Cost Yet",
                xref="paper",
                yref="paper",
                x=1.02,
                y=0.02,
                xanchor="left",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=12, color="gray"),
            )
        ],
    )

    return no_data_fig


def _add_all_providers_traces(fig, daily_costs, dates, today_str):
    """Add traces for all providers to the chart."""
    providers = ["aws", "azure", "gcp"]

    # Pre-calculate if we'll need log scale
    all_values = []
    for provider in providers:
        values = [item.get("provider_breakdown", {}).get(provider, 0) for item in daily_costs]
        all_values.extend([v for v in values if v > 0])

    # Determine if log scale is needed
    will_use_log_scale = False
    if len(all_values) > 1:
        ratio = max(all_values) / min(all_values) if min(all_values) > 0 else 1
        will_use_log_scale = ratio > 50

    for provider in providers:
        values = [item.get("provider_breakdown", {}).get(provider, 0) for item in daily_costs]

        # Prepare display values and text labels
        display_values = []
        hover_values = []
        text_labels = []

        for _, (_, value) in enumerate(zip(daily_costs, values, strict=False)):
            if value == 0:
                # Show N/C/Y for any provider with zero cost
                display_values.append(0.5)  # Small visible height for N/C/Y
                hover_values.append(0)
                text_labels.append("N/C/Y")
            else:
                # Show actual cost data
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
                textposition="auto",  # Let Plotly decide best position
                textfont=dict(size=12, color="black"),
                hovertemplate=f"<b>{provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{customdata:.2f}}<extra></extra>",
                customdata=hover_values,
            )
        )


def _add_single_provider_trace(fig, daily_costs, dates, selected_provider, today_str, dashboard):
    """Add trace for a single selected provider."""
    values = [item.get("provider_breakdown", {}).get(selected_provider, 0) for item in daily_costs]

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
                    dashboard._format_currency_compact(value) if value > 0 else "N/C/Y"
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
                text=["N/C/Y" if v == 0 else dashboard._format_currency_compact(v) for v in values],
                textposition="outside",
                hovertemplate=f"<b>{selected_provider.upper()}</b><br>Date: %{{x}}<br>Cost: $%{{y:.2f}}<extra></extra>",
            )
        )


def _update_chart_layout(fig, selected_provider, use_log_scale=False):
    """Update the chart layout with appropriate styling."""
    title = (
        f"Daily Costs - {selected_provider.upper()}"
        if selected_provider != "all"
        else "Daily Costs by Provider"
    )

    if use_log_scale:
        title += " (Log Scale)"

    yaxis_config = dict(
        tickformat="$,.0f",
        gridcolor="rgba(200,200,200,0.3)",
    )

    if use_log_scale:
        yaxis_config["type"] = "log"

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Cost ($)" + (" - Logarithmic" if use_log_scale else ""),
        **DashboardTheme.LAYOUT,
        hovermode="x unified",
        showlegend=selected_provider == "all",
        barmode="group" if selected_provider == "all" else "relative",
        xaxis=dict(
            tickmode="linear",
            dtick="D1" if len(fig.data[0].x if fig.data else []) <= 31 else "D7",
            tickangle=-45,
        ),
        yaxis=yaxis_config,
    )

    # Add explanation for N/C/Y when showing all providers (legend is visible)
    if selected_provider == "all":
        fig.add_annotation(
            text="N/C/Y = No Cost Yet",
            xref="paper",
            yref="paper",
            x=1.02,
            y=0.02,  # Position to the right, near bottom
            xanchor="left",
            yanchor="bottom",
            showarrow=False,
            font=dict(size=10, color="gray"),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(200,200,200,0.5)",
            borderwidth=1,
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


def _setup_service_provider_selector_callback(dashboard):
    """Set up service provider selector dropdown callback."""

    @dashboard.app.callback(
        [
            Output("service-provider-selector", "options"),
            Output("service-provider-selector", "value"),
        ],
        [Input("cost-data-store", "data")],
    )
    def update_service_provider_selector(cost_data):
        """Update service provider selector options."""
        if not cost_data or "service_breakdown" not in cost_data:
            return [], None

        providers = list(cost_data["service_breakdown"].keys())
        options = [{"label": p.upper(), "value": p} for p in providers]

        return options, providers[0] if providers else None


def _setup_service_breakdown_callback(dashboard):
    """Set up service breakdown chart callback."""

    @dashboard.app.callback(
        Output("service-breakdown-chart", "figure"),
        [Input("cost-data-store", "data"), Input("service-provider-selector", "value")],
    )
    def update_service_breakdown_chart(cost_data, selected_provider):
        """Update the service breakdown chart."""
        # Return loading chart if no data
        if (
            not cost_data
            or "service_breakdown" not in cost_data
            or not selected_provider
            or selected_provider not in cost_data["service_breakdown"]
        ):
            title = f"Service Breakdown - {selected_provider.upper() if selected_provider else 'Loading...'}"
            return _create_loading_chart(title)

        fig = go.Figure()

        service_data = cost_data["service_breakdown"][selected_provider]
        # Filter out services with costs less than $100 and sort by cost (highest to lowest)
        filtered_services = [(k, v) for k, v in service_data.items() if v >= 100.0]
        sorted_services = sorted(filtered_services, key=lambda x: x[1], reverse=True)

        if not sorted_services:
            return _create_loading_chart(
                f"{selected_provider.upper()} Services (No services ≥$100)"
            )

        services = [s[0] for s in sorted_services]
        values = [s[1] for s in sorted_services]
        # Replace zero values with small positive number for log scale
        log_values = [max(v, 0.01) for v in values]

        fig.add_trace(
            go.Bar(
                x=log_values,  # Log-safe values on x-axis (horizontal bars)
                y=services,  # Service names on y-axis
                orientation="h",  # Horizontal orientation
                marker_color=DashboardTheme.COLORS.get(selected_provider, "#000000"),
                text=[dashboard._format_currency_compact(v) if v > 0 else "$0.00" for v in values],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>Cost: $%{customdata:.2f}<extra></extra>",
                customdata=values,  # Store original values for hover
            )
        )

        fig.update_layout(
            title=f"Service Breakdown - {selected_provider.upper()} (Log Scale, ≥$100)",
            xaxis_title="Cost (USD) - Logarithmic Scale",
            xaxis_type="log",  # Use logarithmic scale for cost differences
            yaxis_title="Service",
            height=400,
            **DashboardTheme.LAYOUT,
        )

        return fig
