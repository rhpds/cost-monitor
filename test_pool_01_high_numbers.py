#!/usr/bin/env python3
"""
Test high-numbered pool-01 subscriptions to see if there's an activity pattern
"""

import asyncio
from datetime import datetime
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.subscription import SubscriptionClient

async def test_high_numbered_pool01():
    print("🎯 Testing high-numbered pool-01 subscriptions for activity patterns...")

    try:
        credential = DefaultAzureCredential()
        subscription_client = SubscriptionClient(credential)
        cost_client = CostManagementClient(credential)

        # Get all subscriptions
        print("📋 Finding pool-01 subscriptions...")
        pool_01_subs = []

        for subscription in subscription_client.subscriptions.list():
            state = subscription.state.value if hasattr(subscription.state, 'value') else str(subscription.state)
            if state == 'Enabled' and 'pool-01-' in subscription.display_name:
                try:
                    number = int(subscription.display_name.split('-')[-1])
                    pool_01_subs.append({
                        'id': subscription.subscription_id,
                        'name': subscription.display_name,
                        'number': number
                    })
                except ValueError:
                    pass  # Skip if can't extract number

        # Sort by number
        pool_01_subs.sort(key=lambda x: x['number'])
        print(f"📊 Found {len(pool_01_subs)} pool-01 subscriptions")
        print(f"📊 Range: pool-01-{pool_01_subs[0]['number']} to pool-01-{pool_01_subs[-1]['number']}")

        # Test high-numbered subscriptions (last 20)
        test_subs = pool_01_subs[-20:]  # Last 20 (highest numbers)

        print(f"\n🎯 Testing highest 20 numbered subscriptions:")
        for sub in test_subs:
            print(f"  • {sub['name']}")

        # Set up date range
        from_date = datetime(2025, 12, 24)
        to_date = datetime(2025, 12, 31)
        print(f"\n💰 Querying costs from {from_date.date()} to {to_date.date()}")

        # Test each subscription
        results = []
        for i, subscription in enumerate(test_subs):
            print(f"\n📊 Testing {i+1}/20: {subscription['name']}")

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

                response = cost_client.query.usage(scope=scope, parameters=query_definition)

                if hasattr(response, 'rows') and response.rows:
                    total_cost = sum(row[0] for row in response.rows if len(row) > 0)
                    results.append({
                        'name': subscription['name'],
                        'number': subscription['number'],
                        'cost': total_cost,
                        'entries': len(response.rows)
                    })
                    print(f"  ✅ ${total_cost:.2f} ({len(response.rows)} entries)")
                else:
                    results.append({
                        'name': subscription['name'],
                        'number': subscription['number'],
                        'cost': 0.0,
                        'entries': 0
                    })
                    print(f"  ⚪ $0.00 (no data)")

            except Exception as e:
                print(f"  ❌ Error: {str(e)[:60]}...")

        # Analyze results
        print(f"\n📈 High-Number Pool-01 Results:")
        active_results = [r for r in results if r['cost'] > 0]
        total_cost = sum(r['cost'] for r in results)

        print(f"  📊 Active subscriptions: {len(active_results)}/{len(results)}")
        print(f"  💰 Total cost (7 days): ${total_cost:.2f}")

        if active_results:
            avg_active_cost = sum(r['cost'] for r in active_results) / len(active_results)
            print(f"  📊 Average cost per active subscription: ${avg_active_cost:.2f}")

            print(f"\n🏆 Active high-numbered subscriptions:")
            for r in sorted(active_results, key=lambda x: x['cost'], reverse=True):
                print(f"    💵 {r['name']}: ${r['cost']:.2f}")

        # Look for patterns
        if len(results) > 0:
            activity_rate_high = len(active_results) / len(results)
            print(f"\n📊 Activity Analysis:")
            print(f"  🎯 Activity rate in high numbers (381-400): {activity_rate_high:.1%}")

            # Compare to what we know about lower numbers
            print(f"  🔍 Previous sample showed 40% overall activity rate")

            if activity_rate_high > 0.4:
                print(f"  ✅ High-numbered subscriptions are MORE active!")
            elif activity_rate_high < 0.4:
                print(f"  ❌ High-numbered subscriptions are LESS active")
            else:
                print(f"  ⚪ Similar activity rate to overall average")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_high_numbered_pool01())