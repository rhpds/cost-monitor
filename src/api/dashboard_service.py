#!/usr/bin/env python3
"""
Cost Dashboard Service - Dash Frontend
Provides web interface for cost monitoring data
"""

import os
import logging
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import dash
from dash import html, dcc, callback, Input, Output
import plotly.graph_objs as go
import plotly.express as px
import pandas as pd
import requests
import dash_bootstrap_components as dbc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DATA_SERVICE_URL = os.getenv('DATA_SERVICE_URL', 'http://cost-data-service:8000')
DASH_HOST = os.getenv('DASH_HOST', '0.0.0.0')
DASH_PORT = int(os.getenv('DASH_PORT', '8050'))
DASH_DEBUG = os.getenv('DASH_DEBUG', 'false').lower() == 'true'

class DataServiceClient:
    """Client for the cost data service API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 30
    
    def get_cost_summary(self, start_date: date = None, end_date: date = None, providers: List[str] = None) -> Dict:
        """Get cost summary from data service"""
        try:
            params = {}
            if start_date:
                params['start_date'] = start_date.isoformat()
            if end_date:
                params['end_date'] = end_date.isoformat()
            if providers:
                params['providers'] = providers
                
            response = self.session.get(f"{self.base_url}/api/v1/costs/summary", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting cost summary: {e}")
            return {
                "total_cost": 0.0,
                "currency": "USD",
                "period_start": start_date or (date.today() - timedelta(days=30)),
                "period_end": end_date or date.today(),
                "provider_breakdown": {}
            }
    
    def get_costs(self, start_date: date = None, end_date: date = None, providers: List[str] = None, limit: int = 100) -> List[Dict]:
        """Get detailed cost data from data service"""
        try:
            params = {'limit': limit}
            if start_date:
                params['start_date'] = start_date.isoformat()
            if end_date:
                params['end_date'] = end_date.isoformat()
            if providers:
                params['providers'] = providers
                
            response = self.session.get(f"{self.base_url}/api/v1/costs", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting costs: {e}")
            return []
    
    def get_providers(self) -> List[Dict]:
        """Get available providers"""
        try:
            response = self.session.get(f"{self.base_url}/api/v1/providers")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting providers: {e}")
            return []
    
    def health_check(self) -> bool:
        """Check if data service is healthy"""
        try:
            response = self.session.get(f"{self.base_url}/api/health/ready", timeout=5)
            return response.status_code == 200
        except:
            return False

# Initialize client
data_client = DataServiceClient(DATA_SERVICE_URL)

# Initialize Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Cost Monitor Dashboard"
)

# App layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("Cost Monitor Dashboard", className="text-center mb-4"),
            html.Hr()
        ])
    ]),
    
    # Health status
    dbc.Row([
        dbc.Col([
            dbc.Alert(
                id="health-alert",
                dismissable=False,
                className="mb-3"
            )
        ])
    ]),
    
    # Date range selector
    dbc.Row([
        dbc.Col([
            html.Label("Date Range:", className="fw-bold"),
            dcc.DatePickerRange(
                id='date-picker-range',
                start_date=date.today() - timedelta(days=30),
                end_date=date.today(),
                display_format='YYYY-MM-DD',
                className="mb-3"
            )
        ], width=6),
        dbc.Col([
            html.Label("Auto Refresh:", className="fw-bold"),
            dbc.Switch(
                id="auto-refresh-switch",
                label="Enable Auto Refresh (5 min)",
                value=True,
                className="mb-3"
            )
        ], width=6)
    ]),
    
    # Cost summary cards
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(id="total-cost", className="card-title"),
                    html.P("Total Cost", className="card-text text-muted")
                ])
            ])
        ], width=4),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(id="provider-count", className="card-title"),
                    html.P("Active Providers", className="card-text text-muted")
                ])
            ])
        ], width=4),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(id="period-info", className="card-title"),
                    html.P("Period", className="card-text text-muted")
                ])
            ])
        ], width=4)
    ], className="mb-4"),
    
    # Charts
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Provider Breakdown"),
                dbc.CardBody([
                    dcc.Graph(id="provider-pie-chart")
                ])
            ])
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Cost Trends"),
                dbc.CardBody([
                    dcc.Graph(id="cost-trends-chart")
                ])
            ])
        ], width=6)
    ], className="mb-4"),
    
    # Data table
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recent Cost Data"),
                dbc.CardBody([
                    html.Div(id="cost-data-table")
                ])
            ])
        ])
    ]),
    
    # Auto refresh interval
    dcc.Interval(
        id='interval-component',
        interval=5*60*1000,  # 5 minutes
        n_intervals=0
    )
], fluid=True)

# Callbacks
@callback(
    [Output('health-alert', 'children'),
     Output('health-alert', 'color'),
     Output('total-cost', 'children'),
     Output('provider-count', 'children'),
     Output('period-info', 'children'),
     Output('provider-pie-chart', 'figure'),
     Output('cost-trends-chart', 'figure'),
     Output('cost-data-table', 'children')],
    [Input('date-picker-range', 'start_date'),
     Input('date-picker-range', 'end_date'),
     Input('interval-component', 'n_intervals'),
     Input('auto-refresh-switch', 'value')]
)
def update_dashboard(start_date, end_date, n_intervals, auto_refresh):
    """Update all dashboard components"""
    
    # Convert dates
    if start_date:
        start_date = date.fromisoformat(start_date)
    if end_date:
        end_date = date.fromisoformat(end_date)
    
    # Health check
    is_healthy = data_client.health_check()
    if not is_healthy:
        health_alert = "⚠️ Data Service Unavailable"
        health_color = "warning"
    else:
        health_alert = "✅ Data Service Connected"
        health_color = "success"
    
    # Get data
    try:
        summary = data_client.get_cost_summary(start_date, end_date)
        costs = data_client.get_costs(start_date, end_date, limit=200)
        providers = data_client.get_providers()
        
        # Summary cards
        total_cost = f"${summary['total_cost']:,.2f} {summary['currency']}"
        provider_count = str(len(summary['provider_breakdown']))
        period_info = f"{summary['period_start']} to {summary['period_end']}"
        
        # Provider pie chart
        if summary['provider_breakdown']:
            pie_fig = px.pie(
                values=list(summary['provider_breakdown'].values()),
                names=list(summary['provider_breakdown'].keys()),
                title="Cost by Provider"
            )
        else:
            pie_fig = go.Figure()
            pie_fig.add_annotation(text="No data available", x=0.5, y=0.5, showarrow=False)
        
        # Cost trends chart
        if costs:
            df = pd.DataFrame(costs)
            df['date'] = pd.to_datetime(df['date'])
            
            # Group by date and provider
            daily_costs = df.groupby(['date', 'provider'])['cost'].sum().reset_index()
            
            trends_fig = px.line(
                daily_costs,
                x='date',
                y='cost',
                color='provider',
                title="Daily Cost Trends",
                labels={'cost': 'Cost (USD)', 'date': 'Date'}
            )
        else:
            trends_fig = go.Figure()
            trends_fig.add_annotation(text="No cost data available", x=0.5, y=0.5, showarrow=False)
        
        # Data table
        if costs:
            table_data = costs[:20]  # Show last 20 entries
            table = dbc.Table.from_dataframe(
                pd.DataFrame(table_data).round(2),
                striped=True,
                bordered=True,
                hover=True,
                responsive=True,
                className="mb-0"
            )
        else:
            table = html.P("No cost data available for the selected period.", className="text-muted")
        
    except Exception as e:
        logger.error(f"Error updating dashboard: {e}")
        # Return error state
        return (
            f"❌ Error loading data: {str(e)}",
            "danger",
            "Error",
            "Error", 
            "Error",
            go.Figure().add_annotation(text="Error loading data", x=0.5, y=0.5, showarrow=False),
            go.Figure().add_annotation(text="Error loading data", x=0.5, y=0.5, showarrow=False),
            html.P("Error loading cost data.", className="text-danger")
        )
    
    return (
        health_alert,
        health_color,
        total_cost,
        provider_count,
        period_info,
        pie_fig,
        trends_fig,
        table
    )

if __name__ == "__main__":
    logger.info(f"Starting Cost Dashboard on {DASH_HOST}:{DASH_PORT}")
    logger.info(f"Data Service URL: {DATA_SERVICE_URL}")
    
    app.run_server(
        host=DASH_HOST,
        port=DASH_PORT,
        debug=DASH_DEBUG
    )
