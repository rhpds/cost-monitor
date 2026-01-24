"""
Dashboard layout configuration and HTML structure.

Contains the main layout function and component definitions
for the dashboard UI structure.
"""

from datetime import date

import dash_bootstrap_components as dbc
from dash import dcc, html


def create_dashboard_layout(dashboard):
    """Create the main dashboard layout."""
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
                                                            dcc.DatePickerRange(
                                                                id="date-range-picker",
                                                                start_date=date.today().replace(
                                                                    day=1
                                                                ),
                                                                end_date=date.today(),
                                                                display_format="YYYY-MM-DD",
                                                                style={"width": "100%"},
                                                            )
                                                        ],
                                                        md=6,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Button(
                                                                "Apply Dates",
                                                                id="btn-apply-dates",
                                                                color="primary",
                                                                className="me-2",
                                                            ),
                                                            # Quick date buttons will be added here
                                                            _create_quick_date_buttons(),
                                                        ],
                                                        md=6,
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
                        [html.H5("📊 Key Metrics", className="mb-3"), dbc.Row(id="key-metrics-row")]
                    )
                ],
                className="mb-4",
            ),
            # Charts section
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.H5("💹 Daily Cost Trends", className="mb-0"),
                                            dbc.Select(
                                                id="provider-selector",
                                                options=[
                                                    {"label": "All Providers", "value": "all"},
                                                    {"label": "AWS", "value": "aws"},
                                                    {"label": "Azure", "value": "azure"},
                                                    {"label": "GCP", "value": "gcp"},
                                                ],
                                                value="all",
                                                className="w-25",
                                            ),
                                        ],
                                        className="d-flex justify-content-between align-items-center",
                                    ),
                                    dbc.CardBody(
                                        [
                                            dcc.Graph(
                                                id="cost-trend-chart", style={"height": "400px"}
                                            )
                                        ]
                                    ),
                                ]
                            )
                        ],
                        lg=8,
                    ),
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
                                            )
                                        ]
                                    ),
                                ]
                            )
                        ],
                        lg=4,
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
            dcc.Store(id="loading-store"),
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
        ("Latest", "btn-latest"),
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
