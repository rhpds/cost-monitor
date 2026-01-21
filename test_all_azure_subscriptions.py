#!/usr/bin/env python3
"""
List all Azure subscriptions and query costs for each individually
"""

import asyncio
import os
import json
from datetime import datetime, date, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.subscription import SubscriptionClient

async def test_all_azure_subscriptions():
    print("🔍 Discovering all Azure subscriptions...")

    try:
        # Use Azure default credentials
        credential = DefaultAzureCredential()

        # Create subscription client to list subscriptions
        subscription_client = SubscriptionClient(credential)

        print("✅ Azure credentials initialized")

        # List all subscriptions
        print("📋 Listing all subscriptions...")
        subscriptions = []

        for subscription in subscription_client.subscriptions.list():
            subscriptions.append({
                'id': subscription.subscription_id,
                'name': subscription.display_name,
                'state': subscription.state.value if hasattr(subscription.state, 'value') else str(subscription.state)
            })

        print(f"📊 Found {len(subscriptions)} total subscriptions")

        # Filter to enabled subscriptions
        enabled_subscriptions = [s for s in subscriptions if s['state'] == 'Enabled']
        print(f"✅ Found {len(enabled_subscriptions)} enabled subscriptions")

        # Show some examples
        print(f"\n📋 First 10 enabled subscriptions:")
        for i, sub in enumerate(enabled_subscriptions[:10]):
            print(f"  {i+1}. {sub['name']} ({sub['id']}) - {sub['state']}")

        if len(enabled_subscriptions) > 10:
            print(f"  ... and {len(enabled_subscriptions) - 10} more")

        # Set up date range for cost queries
        from_date = datetime(2025, 12, 24)
        to_date = datetime(2025, 12, 31)

        print(f"\n💰 Querying costs from {from_date.date()} to {to_date.date()}")

        # Create Cost Management client
        cost_client = CostManagementClient(credential)

        # Test cost queries for first 5 subscriptions
        total_costs = {}
        successful_queries = 0
        failed_queries = 0

        print(f"\n🔍 Testing cost queries for first 5 enabled subscriptions...")

        for i, subscription in enumerate(enabled_subscriptions[:5]):
            print(f"\n📊 Testing subscription {i+1}/5: {subscription['name']}")

            try:
                scope = f"/subscriptions/{subscription['id']}"

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
                        }
                    }
                }

                # Execute query
                response = cost_client.query.usage(scope=scope, parameters=query_definition)

                if hasattr(response, 'rows') and response.rows:
                    subscription_total = sum(row[0] for row in response.rows if len(row) > 0)
                    total_costs[subscription['name']] = subscription_total
                    successful_queries += 1
                    print(f"  ✅ ${subscription_total:.2f} total cost ({len(response.rows)} entries)")
                else:
                    total_costs[subscription['name']] = 0.0
                    successful_queries += 1
                    print(f"  ⚪ $0.00 (no cost data)")

            except Exception as e:
                failed_queries += 1
                print(f"  ❌ Error: {str(e)[:100]}...")

        print(f"\n📈 Results Summary:")
        print(f"  ✅ Successful queries: {successful_queries}")
        print(f"  ❌ Failed queries: {failed_queries}")

        # Show cost summary
        if total_costs:
            print(f"\n💰 Cost Summary (7 days):")
            total_all = sum(total_costs.values())
            print(f"  🔥 Combined total: ${total_all:.2f}")

            # Sort by cost
            sorted_costs = sorted(total_costs.items(), key=lambda x: x[1], reverse=True)
            print(f"\n📊 By subscription:")
            for name, cost in sorted_costs:
                if cost > 0:
                    print(f"  💵 {name}: ${cost:.2f}")
                else:
                    print(f"  ⚪ {name}: $0.00")

            # Project monthly cost
            if total_all > 0:
                monthly_projection = total_all * (30/7)  # Scale 7 days to 30 days
                print(f"\n📊 Projections:")
                print(f"  📅 Monthly (30 days): ~${monthly_projection:.2f}")
                print(f"  📅 Daily average: ~${total_all/7:.2f}")

        # Show information about remaining subscriptions
        remaining = len(enabled_subscriptions) - 5
        if remaining > 0:
            print(f"\n⏭️ {remaining} additional enabled subscriptions not tested")
            print(f"📊 Total enabled subscriptions: {len(enabled_subscriptions)}")

            # Suggest which subscription types to focus on
            print(f"\n💡 Recommendations:")
            print(f"  • Query all {len(enabled_subscriptions)} enabled subscriptions in production")
            print(f"  • Focus on subscriptions with 'pool' or 'rhpds' in the name")
            print(f"  • Consider parallel processing for faster results")

    except Exception as e:
        print(f"❌ Error discovering subscriptions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_all_azure_subscriptions())