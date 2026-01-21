#!/usr/bin/env python3
"""
Direct Azure subscription cost test - pool-01-400
"""

import asyncio
import os
import json
from datetime import datetime, date, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient

async def test_azure_subscription_costs():
    subscription_id = "48c192cb-4b83-4023-b1b1-1893e5182f43"  # pool-01-400

    print(f"Testing Azure subscription: {subscription_id} (pool-01-400)")

    try:
        # Use Azure default credentials
        credential = DefaultAzureCredential()

        # Create Cost Management client
        cost_client = CostManagementClient(credential)

        print(f"✅ Azure credentials initialized")

        # Set up date range (use dates from a few months back since cost data has lag)
        # Using dates from late 2025 instead of 2026
        from_date = datetime(2025, 12, 24)
        to_date = datetime(2025, 12, 31)

        print(f"📅 Querying costs from {from_date.date()} to {to_date.date()}")

        # Query cost data using Azure Cost Management API
        scope = f"/subscriptions/{subscription_id}"

        query_definition = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": from_date,
                "to": to_date
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {
                    "totalCost": {
                        "name": "Cost",
                        "function": "Sum"
                    }
                },
                "grouping": [
                    {
                        "type": "Dimension",
                        "name": "ServiceName"
                    }
                ]
            }
        }

        print(f"🔍 Querying Azure Cost Management API...")

        # Execute query
        response = cost_client.query.usage(scope=scope, parameters=query_definition)

        print(f"✅ Query executed successfully")

        # Process results
        if hasattr(response, 'rows') and response.rows:
            print(f"📊 Found {len(response.rows)} cost entries")

            total_cost = 0
            services = {}

            for row in response.rows:
                # Assuming columns are: [cost, date, service_name, currency]
                cost = row[0] if len(row) > 0 else 0
                date_str = row[1] if len(row) > 1 else "Unknown"
                service = row[2] if len(row) > 2 else "Unknown Service"
                currency = row[3] if len(row) > 3 else "USD"

                total_cost += cost

                if service not in services:
                    services[service] = 0
                services[service] += cost

            print(f"\n💰 Total cost: ${total_cost:.2f}")
            print(f"🏗️ Number of services: {len(services)}")

            # Show top services by cost
            sorted_services = sorted(services.items(), key=lambda x: x[1], reverse=True)
            print(f"\n🔝 Top 5 services by cost:")
            for i, (service, cost) in enumerate(sorted_services[:5]):
                print(f"  {i+1}. {service}: ${cost:.2f}")

        else:
            print(f"❌ No cost data found for subscription {subscription_id}")
            print(f"Response: {response}")

    except Exception as e:
        print(f"❌ Error testing Azure subscription: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_azure_subscription_costs())