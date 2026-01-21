#!/usr/bin/env python3
"""
Test a strategic sample of Azure subscriptions to estimate total activity
"""

import asyncio
import re
from datetime import datetime, date, timedelta
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.subscription import SubscriptionClient

async def test_azure_subscription_sample():
    print("🎯 Testing strategic sample of Azure subscriptions...")

    try:
        credential = DefaultAzureCredential()
        subscription_client = SubscriptionClient(credential)
        cost_client = CostManagementClient(credential)

        # List all subscriptions
        print("📋 Getting subscription list...")
        all_subscriptions = []
        for subscription in subscription_client.subscriptions.list():
            all_subscriptions.append({
                'id': subscription.subscription_id,
                'name': subscription.display_name,
                'state': subscription.state.value if hasattr(subscription.state, 'value') else str(subscription.state)
            })

        enabled_subs = [s for s in all_subscriptions if s['state'] == 'Enabled']
        print(f"📊 Total enabled subscriptions: {len(enabled_subs)}")

        # Categorize subscriptions
        rhpds_main = [s for s in enabled_subs if 'RHPDS Subscription' in s['name']]
        pool_00_subs = [s for s in enabled_subs if re.match(r'pool-00-\d+', s['name'])]
        pool_01_subs = [s for s in enabled_subs if re.match(r'pool-01-\d+', s['name'])]
        other_subs = [s for s in enabled_subs if s not in rhpds_main + pool_00_subs + pool_01_subs]

        print(f"📊 Subscription categories:")
        print(f"  🏢 RHPDS Main: {len(rhpds_main)}")
        print(f"  🎱 Pool-00: {len(pool_00_subs)}")
        print(f"  🎱 Pool-01: {len(pool_01_subs)}")
        print(f"  ❓ Other: {len(other_subs)}")

        # Create test sample - strategic selection
        test_sample = []

        # Include all RHPDS main subscriptions (only 3)
        test_sample.extend(rhpds_main)

        # Sample from pool-01 (high-numbered ones are more active)
        if pool_01_subs:
            # Sort pool-01 by number and take samples from different ranges
            pool_01_sorted = sorted(pool_01_subs, key=lambda x: int(x['name'].split('-')[-1]))
            sample_indices = [0, len(pool_01_sorted)//4, len(pool_01_sorted)//2, 3*len(pool_01_sorted)//4, -1]
            for idx in sample_indices:
                if 0 <= idx < len(pool_01_sorted):
                    test_sample.append(pool_01_sorted[idx])
                elif idx == -1:
                    test_sample.append(pool_01_sorted[-1])

        # Sample from pool-00 (fewer samples as they seem less active)
        if pool_00_subs:
            pool_00_sorted = sorted(pool_00_subs, key=lambda x: int(x['name'].split('-')[-1]))
            # Just take a couple from middle and end
            if len(pool_00_sorted) > 1:
                test_sample.append(pool_00_sorted[len(pool_00_sorted)//2])
                test_sample.append(pool_00_sorted[-1])

        # Remove duplicates
        seen = set()
        unique_sample = []
        for sub in test_sample:
            if sub['id'] not in seen:
                seen.add(sub['id'])
                unique_sample.append(sub)

        print(f"\n🎯 Testing {len(unique_sample)} strategic subscriptions:")
        for i, sub in enumerate(unique_sample):
            print(f"  {i+1}. {sub['name']}")

        # Set up date range
        from_date = datetime(2025, 12, 24)
        to_date = datetime(2025, 12, 31)
        print(f"\n💰 Querying costs from {from_date.date()} to {to_date.date()}")

        # Test cost queries
        results = []
        successful = 0
        failed = 0

        for i, subscription in enumerate(unique_sample):
            print(f"\n📊 Testing {i+1}/{len(unique_sample)}: {subscription['name']}")

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
                        'cost': total_cost,
                        'entries': len(response.rows)
                    })
                    successful += 1
                    print(f"  ✅ ${total_cost:.2f} ({len(response.rows)} entries)")
                else:
                    results.append({
                        'name': subscription['name'],
                        'cost': 0.0,
                        'entries': 0
                    })
                    successful += 1
                    print(f"  ⚪ $0.00 (no data)")

            except Exception as e:
                failed += 1
                print(f"  ❌ Error: {str(e)[:80]}...")

        # Analyze results
        print(f"\n📈 Sample Results:")
        print(f"  ✅ Successful: {successful}/{len(unique_sample)}")
        print(f"  ❌ Failed: {failed}/{len(unique_sample)}")

        # Calculate statistics
        sample_total = sum(r['cost'] for r in results)
        active_count = sum(1 for r in results if r['cost'] > 0)

        print(f"\n💰 Sample Cost Analysis:")
        print(f"  🔥 Sample total (7 days): ${sample_total:.2f}")
        print(f"  📊 Active subscriptions: {active_count}/{len(results)}")

        if results:
            avg_cost = sample_total / len(results)
            print(f"  📊 Average per subscription: ${avg_cost:.2f}")

        # Show top contributors
        results_sorted = sorted(results, key=lambda x: x['cost'], reverse=True)
        print(f"\n🏆 Top cost contributors in sample:")
        for r in results_sorted[:5]:
            if r['cost'] > 0:
                print(f"  💵 {r['name']}: ${r['cost']:.2f}")

        # Extrapolate to full subscription base
        if sample_total > 0 and successful > 0:
            # Calculate activity rate
            activity_rate = active_count / len(results)
            average_active_cost = sample_total / active_count if active_count > 0 else 0

            estimated_active_subs = int(len(enabled_subs) * activity_rate)
            estimated_total = estimated_active_subs * average_active_cost

            print(f"\n📊 Extrapolation to all {len(enabled_subs)} subscriptions:")
            print(f"  🎯 Estimated activity rate: {activity_rate:.1%}")
            print(f"  📊 Estimated active subscriptions: {estimated_active_subs}")
            print(f"  💰 Estimated total cost (7 days): ${estimated_total:.2f}")
            print(f"  📅 Estimated monthly: ${estimated_total * (30/7):.2f}")
            print(f"  📅 Estimated daily: ${estimated_total / 7:.2f}")

        print(f"\n💡 Next Steps:")
        print(f"  • Full scan of all {len(enabled_subs)} subscriptions")
        print(f"  • Focus on pool-01-* subscriptions (appear more active)")
        print(f"  • Implement parallel processing for faster data collection")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_azure_subscription_sample())