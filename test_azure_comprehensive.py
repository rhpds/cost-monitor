#!/usr/bin/env python3
"""Test Azure comprehensive scope implementation"""
import sys
import os
sys.path.append('/app' if os.path.exists('/app') else '.')

import asyncio
from datetime import datetime, timedelta
from src.providers.azure import AzureCostProvider
from src.config.settings import get_config

async def test_azure():
    config = get_config()
    print('=== Azure Configuration ===')
    print('Azure enabled:', config.azure.get('enabled', False))
    print('Management groups:', config.azure.get('management_groups', []))
    print('Subscription ID:', config.azure.get('subscription_id', 'Not set'))
    print('Use management groups:', config.azure.get('use_management_groups', True))
    print()

    provider = AzureCostProvider(config.azure)
    print('=== Testing Azure Data Collection ===')
    print('Testing comprehensive scope (all management groups + individual subscriptions)...')

    try:
        # Test with just 1 day to verify we get realistic daily costs
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)

        print(f'Querying Azure costs from {start_date.date()} to {end_date.date()}')
        data = await provider.get_cost_data(start_date, end_date)

        print(f'Azure data points collected: {len(data.data_points)}')

        if data.data_points:
            total_cost = sum(dp.amount for dp in data.data_points)
            print(f'Total Azure cost for 1 day: ${total_cost:.2f}')

            # Expected: ~$2800/day according to user feedback
            if total_cost > 1000:  # Reasonable daily cost
                print('✅ Azure costs look realistic!')
            else:
                print(f'⚠️  Azure costs still seem low (expected ~$2800/day)')

            print('\nSample data points:')
            for i, dp in enumerate(data.data_points[:5]):
                service_name = getattr(dp, 'service_name', 'Unknown')
                region = getattr(dp, 'region', 'N/A')
                print(f'  {service_name} ({region}): ${dp.amount:.2f} ({dp.date})')

            # Show breakdown by service
            service_costs = {}
            for dp in data.data_points:
                service_name = getattr(dp, 'service_name', 'Unknown')
                service_costs[service_name] = service_costs.get(service_name, 0) + dp.amount

            print('\nCost breakdown by service:')
            for service, cost in sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f'  {service}: ${cost:.2f}')
        else:
            print('❌ No Azure data points collected')

    except Exception as e:
        print(f'Error testing Azure: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_azure())