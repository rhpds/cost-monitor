"""
AWS cost breakdown callbacks for the dashboard.

Handles page toggle, data fetching, chart rendering, and summary table
for the AWS breakdown view.
"""

import asyncio
import logging

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate

from ..themes import DashboardTheme

logger = logging.getLogger(__name__)

# Color palette for breakdown items (distinct from provider colors)
BREAKDOWN_COLORS = [
    "#FF9900",  # AWS orange
    "#146EB4",  # AWS dark blue
    "#232F3E",  # AWS squid ink
    "#FF6600",
    "#1A8CFF",
    "#00A1C9",
    "#D45B07",
    "#7D8998",
    "#2E73B8",
    "#E07941",
    "#3F8624",
    "#8C4FFF",
    "#C7511F",
    "#007185",
    "#B12704",
    "#067D68",
    "#CC5500",
    "#5C687A",
    "#DD4477",
    "#316395",
    "#994499",
    "#22AA99",
    "#AAAA11",
    "#6633CC",
    "#E67300",
]


def setup_aws_breakdown_callbacks(dashboard):
    """Set up all AWS breakdown-related callbacks."""
    _setup_page_toggle_callback(dashboard)
    _setup_data_fetch_callback(dashboard)
    _setup_chart_callback(dashboard)
    _setup_table_callback(dashboard)


def _setup_page_toggle_callback(dashboard):
    """Set up page toggle between main dashboard and breakdown view."""

    @dashboard.app.callback(
        [
            Output("main-dashboard-content", "style"),
            Output("aws-breakdown-content", "style"),
            Output("current-page-store", "data"),
        ],
        [
            Input("btn-aws-breakdown", "n_clicks"),
            Input("btn-back-to-dashboard", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_page(breakdown_clicks, back_clicks):
        """Toggle between main dashboard and AWS breakdown view."""
        import dash

        ctx = dash.callback_context
        if not ctx.triggered:
            raise PreventUpdate

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if triggered_id == "btn-aws-breakdown":
            return (
                {"display": "none"},
                {"display": "block"},
                {"page": "aws-breakdown"},
            )
        else:
            return (
                {"display": "block"},
                {"display": "none"},
                {"page": "main"},
            )


def _setup_data_fetch_callback(dashboard):
    """Set up data fetching callback for breakdown view."""

    @dashboard.app.callback(
        [
            Output("aws-breakdown-data-store", "data"),
            Output("breakdown-loading", "children"),
            Output("breakdown-date-range-display", "children"),
        ],
        [
            Input("current-page-store", "data"),
            Input("breakdown-dimension-selector", "value"),
            Input("breakdown-top-n", "value"),
        ],
        [
            State("date-range-picker", "start_date"),
            State("date-range-picker", "end_date"),
        ],
        prevent_initial_call=True,
    )
    def fetch_breakdown_data(page_data, dimension, top_n_str, start_date_str, end_date_str):
        """Fetch AWS breakdown data when on the breakdown page."""
        if not page_data or page_data.get("page") != "aws-breakdown":
            raise PreventUpdate

        if not start_date_str or not end_date_str:
            raise PreventUpdate

        from datetime import datetime

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        top_n = int(top_n_str) if top_n_str else 25

        date_display = f"Date range: {start_date} to {end_date}"

        # Fetch data using async pattern from data_store.py
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        data_manager = dashboard.data_manager

        async def fetch():
            return await data_manager.get_aws_breakdown(
                start_date, end_date, group_by=dimension, top_n=top_n
            )

        try:
            result = loop.run_until_complete(fetch())
        except Exception as e:
            logger.error(f"Error fetching AWS breakdown: {e}")
            result = None

        if result is None:
            return (
                None,
                html.Div(
                    "Failed to load AWS breakdown data.",
                    className="text-danger",
                ),
                date_display,
            )

        return result, "", date_display


def _setup_chart_callback(dashboard):
    """Set up stacked bar chart callback for breakdown data."""

    @dashboard.app.callback(
        Output("aws-breakdown-chart", "figure"),
        [Input("aws-breakdown-data-store", "data")],
    )
    def update_breakdown_chart(breakdown_data):
        """Render stacked bar chart from breakdown data."""
        if not breakdown_data or not breakdown_data.get("items"):
            fig = go.Figure()
            fig.add_annotation(
                text="No data available. Click 'AWS Breakdown' to load.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="gray"),
            )
            fig.update_layout(
                xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                **DashboardTheme.LAYOUT,
            )
            return fig

        items = breakdown_data["items"]
        group_by = breakdown_data.get("group_by", "LINKED_ACCOUNT")

        # Collect all dates across all items and sort
        all_dates = set()
        for item in items:
            all_dates.update(item.get("daily_costs", {}).keys())
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            fig = go.Figure()
            fig.update_layout(**DashboardTheme.LAYOUT)
            return fig

        fig = go.Figure()

        for i, item in enumerate(items):
            daily_costs = item.get("daily_costs", {})
            values = [daily_costs.get(d, 0) for d in sorted_dates]
            color = BREAKDOWN_COLORS[i % len(BREAKDOWN_COLORS)]
            display_name = item.get("display_name", item.get("key", ""))

            # Truncate long names for legend
            legend_name = display_name[:40] + "..." if len(display_name) > 40 else display_name

            fig.add_trace(
                go.Bar(
                    x=sorted_dates,
                    y=values,
                    name=legend_name,
                    marker_color=color,
                    hovertemplate=(
                        f"<b>{display_name}</b><br>"
                        "Date: %{x}<br>"
                        "Cost: $%{y:,.2f}<extra></extra>"
                    ),
                )
            )

        title = (
            "Daily Costs by Linked Account"
            if group_by == "LINKED_ACCOUNT"
            else "Daily Costs by EC2 Instance Type"
        )

        fig.update_layout(
            title=title,
            barmode="stack",
            xaxis_title="Date",
            yaxis_title="Cost ($)",
            yaxis=dict(tickformat="$,.0f"),
            xaxis=dict(
                tickmode="linear",
                dtick="D1" if len(sorted_dates) <= 31 else "D7",
                tickangle=-45,
            ),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.2,
                xanchor="center",
                x=0.5,
                font=dict(size=10),
            ),
            font_family=DashboardTheme.LAYOUT["font_family"],
            font_size=DashboardTheme.LAYOUT["font_size"],
            margin={"l": 60, "r": 20, "t": 40, "b": 120},
        )

        return fig


def _setup_table_callback(dashboard):
    """Set up summary table callback for breakdown data."""

    @dashboard.app.callback(
        Output("aws-breakdown-table", "children"),
        [Input("aws-breakdown-data-store", "data")],
    )
    def update_breakdown_table(breakdown_data):
        """Render summary table from breakdown data."""
        if not breakdown_data or not breakdown_data.get("items"):
            return html.Div("No data available.", className="text-muted text-center p-3")

        items = breakdown_data["items"]
        grand_total = breakdown_data.get("total_cost", 0)

        # Build table rows
        header = html.Thead(
            html.Tr(
                [
                    html.Th("Rank", style={"width": "60px"}),
                    html.Th("Name"),
                    html.Th("Total Cost", style={"textAlign": "right"}),
                    html.Th(
                        "% of Total",
                        style={"textAlign": "right", "width": "100px"},
                    ),
                    html.Th(
                        "Trend",
                        style={"textAlign": "right", "width": "120px"},
                    ),
                ]
            )
        )

        rows = []
        for rank, item in enumerate(items, 1):
            total_cost = item.get("total_cost", 0)
            display_name = item.get("display_name", item.get("key", ""))
            pct = (total_cost / grand_total * 100) if grand_total > 0 else 0

            # Calculate trend: avg of last 3 days vs first 3 days
            daily_costs = item.get("daily_costs", {})
            sorted_dates = sorted(daily_costs.keys())
            trend_text = ""
            trend_color = "text-muted"

            if len(sorted_dates) >= 6:
                first_3 = [daily_costs[d] for d in sorted_dates[:3]]
                last_3 = [daily_costs[d] for d in sorted_dates[-3:]]
                first_avg = sum(first_3) / 3
                last_avg = sum(last_3) / 3

                if first_avg > 0:
                    change_pct = ((last_avg - first_avg) / first_avg) * 100
                    if abs(change_pct) < 2:
                        trend_text = "Stable"
                    elif change_pct > 0:
                        trend_text = f"+{change_pct:.1f}%"
                        trend_color = "text-danger"
                    else:
                        trend_text = f"{change_pct:.1f}%"
                        trend_color = "text-success"

            rows.append(
                html.Tr(
                    [
                        html.Td(str(rank)),
                        html.Td(
                            display_name,
                            style={
                                "maxWidth": "400px",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                                "whiteSpace": "nowrap",
                            },
                            title=display_name,
                        ),
                        html.Td(
                            f"${total_cost:,.2f}",
                            style={"textAlign": "right"},
                        ),
                        html.Td(f"{pct:.1f}%", style={"textAlign": "right"}),
                        html.Td(
                            trend_text,
                            className=trend_color,
                            style={"textAlign": "right"},
                        ),
                    ]
                )
            )

        return dbc.Table(
            [header, html.Tbody(rows)],
            bordered=True,
            hover=True,
            striped=True,
            responsive=True,
            size="sm",
        )
