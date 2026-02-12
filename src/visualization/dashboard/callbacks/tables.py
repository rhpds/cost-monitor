"""
Table-related callbacks for the dashboard.

Handles account breakdown tables and detailed cost data tables.
"""

import logging
from datetime import date

from dash import Input, Output, dash_table

from ..themes import DashboardTheme

logger = logging.getLogger(__name__)


def setup_table_callbacks(dashboard):
    """Set up all table-related callbacks."""
    _setup_account_breakdown_callback(dashboard)
    _setup_cost_data_table_callback(dashboard)


def _setup_account_breakdown_callback(dashboard):
    """Set up account breakdown table callback."""

    @dashboard.app.callback(
        Output("account-breakdown-content", "children"),
        [Input("cost-data-store", "data")],
    )
    def update_account_breakdown(cost_data):
        """Update the account breakdown table."""
        if not cost_data or "account_breakdown" not in cost_data:
            return "Loading account data..."

        account_breakdown = cost_data["account_breakdown"]
        if not account_breakdown:
            return "No account data available."

        # Convert nested structure to flat list
        accounts_list = []
        for provider, accounts in account_breakdown.items():
            if isinstance(accounts, list):
                # API returns list of account objects
                for account in accounts:
                    if account.get("cost", 0) > 0:
                        accounts_list.append(
                            {
                                "Provider": provider.upper(),
                                "Account": account.get(
                                    "account_name", account.get("account_id", "Unknown")
                                ),
                                "Cost": f"${account.get('cost', 0):.2f}",
                                "Currency": account.get("currency", "USD"),
                                "_cost_raw": account.get("cost", 0),  # For sorting
                            }
                        )
            else:
                # Handle dict format (legacy)
                for account_key, account_data in accounts.items():
                    if account_data.get("cost", 0) > 0:
                        accounts_list.append(
                            {
                                "Provider": provider.upper(),
                                "Account": account_data.get("account_name", account_key),
                                "Cost": f"${account_data.get('cost', 0):.2f}",
                                "Currency": account_data.get("currency", "USD"),
                                "_cost_raw": account_data.get("cost", 0),
                            }
                        )

        if not accounts_list:
            return "No account data available."

        # Sort by cost descending
        accounts_list.sort(key=lambda x: x["_cost_raw"], reverse=True)

        # Remove raw cost field before displaying
        for account in accounts_list:
            del account["_cost_raw"]

        return dash_table.DataTable(
            data=accounts_list,
            columns=[
                {"name": "Provider", "id": "Provider"},
                {"name": "Account", "id": "Account"},
                {"name": "Cost", "id": "Cost"},
                {"name": "Currency", "id": "Currency"},
            ],
            style_cell={"textAlign": "left", "padding": "10px"},
            style_header={
                "backgroundColor": DashboardTheme.COLORS.get("primary", "#2E86AB"),
                "color": "white",
                "fontWeight": "bold",
            },
            style_data={"backgroundColor": "white"},
            style_data_conditional=[
                {
                    "if": {"row_index": "odd"},
                    "backgroundColor": "rgb(248, 248, 248)",
                }
            ],
            page_size=20,
            page_action="native",
            sort_action="native",
            filter_action="native",
        )


def _setup_cost_data_table_callback(dashboard):
    """Set up cost data table callback."""

    @dashboard.app.callback(
        Output("cost-data-table", "children"),
        [Input("cost-data-store", "data")],
    )
    def update_cost_data_table(cost_data):
        """Update the detailed cost data table."""
        if not cost_data or "daily_costs" not in cost_data:
            return "Loading cost data..."

        daily_costs = cost_data["daily_costs"]
        if not daily_costs:
            return "No cost data available."

        today_str = date.today().strftime("%Y-%m-%d")

        # Convert to table format
        table_data = []
        for item in daily_costs:
            is_today = item["date"] == today_str
            provider_breakdown = item.get("provider_breakdown", {})

            # Extract provider costs
            aws_cost = provider_breakdown.get("aws", 0)
            azure_cost = provider_breakdown.get("azure", 0)
            gcp_cost = provider_breakdown.get("gcp", 0)

            # For AWS, show "N/A" if it's today (due to data lag)
            aws_display = "N/A" if is_today else f"${aws_cost:.2f}"

            # Calculate total
            total_cost = azure_cost + gcp_cost
            if not is_today:
                total_cost += aws_cost

            table_data.append(
                {
                    "Date": item["date"],
                    "AWS": aws_display,
                    "Azure": f"${azure_cost:.2f}",
                    "GCP": f"${gcp_cost:.2f}",
                    "Total": f"${total_cost:.2f}" if total_cost > 0 else "N/A",
                }
            )

        return dash_table.DataTable(
            data=table_data,
            columns=[
                {"name": "Date", "id": "Date"},
                {"name": "AWS", "id": "AWS"},
                {"name": "Azure", "id": "Azure"},
                {"name": "GCP", "id": "GCP"},
                {"name": "Total", "id": "Total"},
            ],
            style_cell={"textAlign": "left", "padding": "10px"},
            style_header={
                "backgroundColor": DashboardTheme.COLORS.get("primary", "#2E86AB"),
                "color": "white",
                "fontWeight": "bold",
            },
            style_data={"backgroundColor": "white"},
            style_data_conditional=[
                {
                    "if": {"row_index": "odd"},
                    "backgroundColor": "rgb(248, 248, 248)",
                }
            ],
            page_size=15,
            page_action="native",
            sort_action="native",
        )
