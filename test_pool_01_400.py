#!/usr/bin/env python3
"""Test script to check pool-01-400 subscription cost data"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, '/home/prutledg/cost-monitor/src')

from providers.azure import AzureProvider
from config.settings import config

async def test_pool_01_400():
    subscription_id = "48c192cb-4b83-4023-b1b1-1893e5182f43"  # pool-01-400

    print(f"Testing subscription: {subscription_id} (pool-01-400)")

    try:
        provider = AzureProvider(config.azure)

        # Test last 7 days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=7)

        print(f"Querying costs from {start_date} to {end_date}")

        costs = await provider.get_cost_data(
            start_date=start_date,
            end_date=end_date,
            subscription_id=subscription_id  # Override to use specific subscription
        )

        print(f"\nResults:")
        print(f"Total cost entries: {len(costs)}")

        if costs:
            total_cost = sum(cost['cost'] for cost in costs)
            print(f"Total costs: ${total_cost:.2f}")
            print(f"Date range in data: {min(cost['date'] for cost in costs)} to {max(cost['date'] for cost in costs)}")
            print(f"\nSample entries (first 3):")
            for i, cost in enumerate(costs[:3]):
                print(f"  {i+1}. {cost['date']}: ${cost['cost']:.2f} ({cost.get('service', 'Unknown service')})")
        else:
            print("No cost data found")

    except Exception as e:
        print(f"Error testing subscription: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_pool_01_400())