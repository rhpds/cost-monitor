"""
Dashboard layout configuration and HTML structure.

Contains the main layout function and component definitions
for the dashboard UI structure.
"""

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html


def _get_plotly_config(debug_mode=False):
    """Get Plotly configuration based on environment."""
    if debug_mode:
        # Dev/Debug mode: Show modebar but hide logo
        return {
            'displaylogo': False,
        }
    else:
        # Production mode: Hide logo and unnecessary buttons for clean UI
        return {
            'displaylogo': False,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d']
        }


def create_dashboard_layout(dashboard):
    """Create the main dashboard layout."""
    # Get environment-specific Plotly config
    plotly_config = _get_plotly_config(debug_mode=dashboard.debug)
    return dbc.Container(
        [
            # Header
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H1(
                                "☁️ Multi-Cloud Cost Monitor",
                                className="text-center mb-4",
                                style={"color": "#2E86AB", "font-weight": "bold"},
                            ),
                        ]
                    )
                ],
                className="mb-4",
            ),
            # Alert banner
            dbc.Row([dbc.Col([html.Div(id="alert-banner")])], className="mb-3"),
            # Loading banner
            dbc.Row([dbc.Col([html.Div(id="loading-banner")])], className="mb-3"),
            # Date range controls
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H5("📅 Date Range", className="mb-3"),
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            html.Div(
                                                                [
                                                                    dcc.DatePickerRange(
                                                                        id="date-range-picker",
                                                                        start_date=date.today().replace(
                                                                            day=1
                                                                        ),
                                                                        end_date=date.today()
                                                                        - timedelta(days=2),
                                                                        display_format="YYYY-MM-DD",
                                                                        style={"width": "auto"},
                                                                    ),
                                                                    dbc.Button(
                                                                        "Apply",
                                                                        id="btn-apply-dates",
                                                                        color="success",
                                                                        size="sm",
                                                                        style={"marginLeft": "8px"},
                                                                    ),
                                                                ],
                                                                style={
                                                                    "alignItems": "center",
                                                                    "display": "flex",
                                                                },
                                                            )
                                                        ],
                                                        md=12,
                                                    ),
                                                ]
                                            ),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            html.Div(
                                                                [
                                                                    html.Small(
                                                                        "Quick ranges: ",
                                                                        className="text-muted me-2",
                                                                    ),
                                                                    _create_quick_date_buttons(),
                                                                ],
                                                                className="d-flex align-items-center mt-2",
                                                            )
                                                        ],
                                                        md=12,
                                                    ),
                                                ]
                                            )
                                        ]
                                    )
                                ]
                            ),
                        ],
                        lg=12,
                    )
                ],
                className="mb-4",
            ),
            # Key metrics row
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H5("📊 Key Metrics", className="mb-3"),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            [
                                                dbc.CardHeader("Total Cost"),
                                                dbc.CardBody(
                                                    html.H4(
                                                        "$0.00",
                                                        id="total-cost-metric",
                                                        className="text-primary mb-0",
                                                    )
                                                ),
                                            ],
                                            className="mb-3",
                                        ),
                                        md=3,
                                    ),
                                    dbc.Col(
                                        dbc.Card(
                                            [
                                                dbc.CardHeader("Daily Average"),
                                                dbc.CardBody(
                                                    html.H4(
                                                        "$0.00",
                                                        id="daily-average-metric",
                                                        className="text-info mb-0",
                                                    )
                                                ),
                                            ],
                                            className="mb-3",
                                        ),
                                        md=3,
                                    ),
                                    dbc.Col(
                                        dbc.Card(
                                            [
                                                dbc.CardHeader("Monthly Projection"),
                                                dbc.CardBody(
                                                    html.H4(
                                                        "$0.00",
                                                        id="monthly-projection-metric",
                                                        className="text-warning mb-0",
                                                    )
                                                ),
                                            ],
                                            className="mb-3",
                                        ),
                                        md=3,
                                    ),
                                    dbc.Col(
                                        dbc.Card(
                                            [
                                                dbc.CardHeader("Cost Trend"),
                                                dbc.CardBody(
                                                    html.H4(
                                                        "0.0%",
                                                        id="cost-trend-metric",
                                                        className="text-muted mb-0",
                                                    )
                                                ),
                                            ],
                                            className="mb-3",
                                        ),
                                        md=3,
                                    ),
                                ],
                                id="key-metrics-row",
                            ),
                        ]
                    )
                ],
                className="mb-4",
            ),
            # Daily cost trends chart - full width row
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.H5("💹 Daily Cost Trends", className="mb-0"),
                                            html.Div(
                                                [
                                                    dbc.Checklist(
                                                        id="include-savings-plans-toggle",
                                                        options=[
                                                            {
                                                                "label": "Include Savings Plans",
                                                                "value": "include",
                                                            }
                                                        ],
                                                        value=[],  # Default unchecked
                                                        switch=True,
                                                        className="me-3",
                                                    ),
                                                    dbc.Checklist(
                                                        id="log-scale-toggle",
                                                        options=[
                                                            {
                                                                "label": "Logarithmic Scale",
                                                                "value": "log",
                                                            }
                                                        ],
                                                        value=["log"],  # Default checked (log scale)
                                                        switch=True,
                                                        className="me-3",
                                                    ),
                                                    dbc.Select(
                                                        id="provider-selector",
                                                        options=[
                                                            {"label": "All Providers", "value": "all"},
                                                            {"label": "AWS", "value": "aws"},
                                                            {"label": "Azure", "value": "azure"},
                                                            {"label": "GCP", "value": "gcp"},
                                                        ],
                                                        value="all",
                                                        style={"minWidth": "150px"},
                                                    ),
                                                ],
                                                className="d-flex align-items-center",
                                            ),
                                        ],
                                        className="d-flex justify-content-between align-items-center",
                                    ),
                                    dbc.CardBody(
                                        [
                                            dcc.Graph(
                                                id="cost-trend-chart",
                                                style={"height": "400px"},
                                                config=plotly_config
                                            )
                                        ]
                                    ),
                                ]
                            )
                        ],
                        lg=12,
                    ),
                ],
                className="mb-4",
            ),
            # Provider breakdown chart
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.H5("🔧 Provider Breakdown", className="mb-0")
                                    ),
                                    dbc.CardBody(
                                        [
                                            dcc.Graph(
                                                id="provider-breakdown-chart",
                                                style={"height": "400px"},
                                                config=plotly_config
                                            )
                                        ]
                                    ),
                                ]
                            )
                        ],
                        lg=12,
                    ),
                ],
                className="mb-4",
            ),
            # Service breakdown section
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.H5("⚙️ Top Services", className="mb-0"),
                                            dbc.Select(
                                                id="service-provider-selector",
                                                options=[],
                                                value="aws",
                                                className="w-25",
                                            ),
                                        ],
                                        className="d-flex justify-content-between align-items-center",
                                    ),
                                    dbc.CardBody(
                                        [
                                            dcc.Graph(
                                                id="service-breakdown-chart",
                                                style={"height": "400px"},
                                                config=plotly_config
                                            )
                                        ]
                                    ),
                                ]
                            )
                        ]
                    )
                ],
                className="mb-4",
            ),
            # Account breakdown section
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.H5("👥 Account Breakdown", className="mb-0"),
                                            html.Div(
                                                [
                                                    dbc.Button(
                                                        "🔍",
                                                        id="account-search-toggle",
                                                        color="outline-secondary",
                                                        size="sm",
                                                        className="me-2",
                                                    ),
                                                    dbc.Button(
                                                        "📊",
                                                        id="account-chart-view",
                                                        color="outline-primary",
                                                        size="sm",
                                                        className="me-2",
                                                    ),
                                                    dbc.Button(
                                                        "💾",
                                                        id="account-export-csv",
                                                        color="outline-success",
                                                        size="sm",
                                                    ),
                                                ]
                                            ),
                                        ],
                                        className="d-flex justify-content-between align-items-center",
                                    ),
                                    dbc.CardBody([html.Div(id="account-breakdown-content")]),
                                ]
                            )
                        ]
                    )
                ],
                className="mb-4",
            ),
            # Data table section
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.H5("📋 Detailed Cost Data", className="mb-0")
                                    ),
                                    dbc.CardBody([html.Div(id="cost-data-table")]),
                                ]
                            )
                        ]
                    )
                ],
                className="mb-4",
            ),
            # Hidden components for state management
            dcc.Store(id="cost-data-store"),
            dcc.Store(id="alert-data-store"),
            dcc.Store(id="loading-store", data={"loading": True}),  # Start with loading=True
            dcc.Interval(
                id="interval-component",
                interval=dashboard.refresh_interval,
                n_intervals=0,
                disabled=not dashboard.auto_refresh,
            ),
            html.Div(id="last-update-time", className="text-muted text-center mt-3"),
        ],
        fluid=True,
    )


def _create_quick_date_buttons():
    """Create quick date selection buttons."""
    buttons = [
        ("This Month", "btn-this-month"),
        ("Last Month", "btn-last-month"),
        ("This Week", "btn-this-week"),
        ("Last Week", "btn-last-week"),
        ("Last 30 Days", "btn-last-30-days"),
        ("Last 7 Days", "btn-last-7-days"),
    ]

    return html.Div(
        [
            dbc.Button(
                label, id=btn_id, color="outline-secondary", size="sm", className="me-1 mb-1"
            )
            for label, btn_id in buttons
        ]
    )
