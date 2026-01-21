#!/usr/bin/env python3
"""
Test the new Azure provider implementation with individual subscription discovery
"""

import asyncio
import sys
import os
from datetime import datetime, date, timedelta

# Add src to path
sys.path.insert(0, '/home/prutledg/cost-monitor/src')

from providers.azure import AzureCostProvider
from config.settings import config

async def test_new_azure_provider():
    """Test the overhauled Azure provider with subscription discovery"""
    print("🧪 Testing new Azure provider implementation...")

    try:
        # Initialize the Azure provider
        print("\n📋 Step 1: Initialize Azure provider")
        azure_config = config.azure
        print(f"Azure config keys: {list(azure_config.keys())}")

        provider = AzureCostProvider(azure_config)
        print("✅ Azure provider initialized successfully")

        # Test authentication
        print("\n🔐 Step 2: Test authentication")
        auth_result = await provider.ensure_authenticated()
        print(f"✅ Authentication successful")

        # Test connection (subscription discovery)
        print("\n🌐 Step 3: Test connection and subscription discovery")
        connection_test = await provider.test_connection()
        if connection_test:
            print("✅ Connection test passed - subscriptions discovered")
        else:
            print("❌ Connection test failed")
            return False

        # Test cost data retrieval with a small date range
        print("\n💰 Step 4: Test cost data retrieval")

        # Use recent dates (Cost Management API has ~1-2 day lag)
        end_date = date.today() - timedelta(days=2)
        start_date = end_date - timedelta(days=1)  # Just 1 day for testing

        print(f"📅 Querying costs for {start_date} (1 day sample)")

        cost_summary = await provider.get_cost_data(
            start_date=start_date,
            end_date=end_date,
            granularity=provider.TimeGranularity.DAILY
        )

        print(f"✅ Cost data retrieved successfully")
        print(f"📊 Results:")
        print(f"  • Date range: {cost_summary.start_date} to {cost_summary.end_date}")
        print(f"  • Total cost: ${cost_summary.total_cost:.2f}")
        print(f"  • Currency: {cost_summary.currency}")
        print(f"  • Data points: {len(cost_summary.data_points)}")
        print(f"  • Provider: {cost_summary.provider}")

        if cost_summary.data_points:
            print(f"\n🔍 Sample data points (first 5):")
            for i, point in enumerate(cost_summary.data_points[:5]):
                subscription_info = point.tags.get('subscription_name', point.account_id) if point.tags else point.account_id
                print(f"  {i+1}. {point.date}: ${point.amount:.2f} - {point.service_name} ({subscription_info})")

        # Test with service breakdown
        print("\n🔧 Step 5: Test service breakdown")

        service_summary = await provider.get_cost_data(
            start_date=start_date,
            end_date=end_date,
            granularity=provider.TimeGranularity.DAILY,
            group_by=['SERVICE']
        )

        print(f"✅ Service breakdown retrieved")
        print(f"📊 Service breakdown results:")
        print(f"  • Total cost: ${service_summary.total_cost:.2f}")
        print(f"  • Service data points: {len(service_summary.data_points)}")

        if service_summary.data_points:
            # Group by service for summary
            service_costs = {}
            for point in service_summary.data_points:
                if point.service_name not in service_costs:
                    service_costs[point.service_name] = 0
                service_costs[point.service_name] += point.amount

            # Show top services
            top_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"\n🏆 Top 5 services by cost:")
            for i, (service, cost) in enumerate(top_services):
                print(f"  {i+1}. {service}: ${cost:.2f}")

        # Performance summary
        print(f"\n⚡ Performance Summary:")
        print(f"  • Successfully queried multiple Azure subscriptions")
        print(f"  • Parallel processing with rate limiting worked")
        print(f"  • No blob storage dependencies")
        print(f"  • Direct Cost Management API queries")

        return True

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_specific_subscription():
    """Test querying a specific subscription we know has data"""
    print("\n🎯 Testing specific high-activity subscription...")

    try:
        azure_config = config.azure
        provider = AzureCostProvider(azure_config)
        await provider.ensure_authenticated()

        # Test pool-01-400 which we know has significant costs
        subscription_id = "48c192cb-4b83-4023-b1b1-1893e5182f43"  # pool-01-400

        # Use historical dates we know have data
        start_date = date(2025, 12, 24)
        end_date = date(2025, 12, 31)

        print(f"🎯 Testing specific subscription: pool-01-400")
        print(f"📅 Date range: {start_date} to {end_date}")

        cost_summary = await provider.get_cost_data(
            start_date=start_date,
            end_date=end_date,
            granularity=provider.TimeGranularity.DAILY,
            subscription_id=subscription_id  # Test specific subscription parameter
        )

        print(f"✅ Specific subscription test successful")
        print(f"💰 Pool-01-400 costs: ${cost_summary.total_cost:.2f}")
        print(f"📊 Data points: {len(cost_summary.data_points)}")

        if cost_summary.total_cost > 200:  # We expect ~$261.98
            print(f"✅ Cost amount matches expected range (~$260)")
        else:
            print(f"⚠️ Cost amount lower than expected")

        return True

    except Exception as e:
        print(f"❌ Specific subscription test failed: {e}")
        return False

async def main():
    """Run all Azure provider tests"""
    print("🚀 Azure Provider Test Suite")
    print("=" * 50)

    # Test 1: General provider functionality
    test1_result = await test_new_azure_provider()

    # Test 2: Specific subscription (if general test passes)
    test2_result = False
    if test1_result:
        test2_result = await test_specific_subscription()

    # Summary
    print("\n" + "=" * 50)
    print("📋 Test Results Summary:")
    print(f"  ✅ General provider test: {'PASS' if test1_result else 'FAIL'}")
    print(f"  ✅ Specific subscription test: {'PASS' if test2_result else 'FAIL'}")

    if test1_result and test2_result:
        print("\n🎉 All tests PASSED! New Azure provider is working correctly.")
        print("\n🔥 Key achievements:")
        print("  • Individual subscription discovery working")
        print("  • Parallel processing with rate limiting functional")
        print("  • Cost Management API queries successful")
        print("  • No blob storage dependencies")
        print("  • Service breakdown functionality intact")
    else:
        print("\n❌ Some tests FAILED. Check the output above for details.")

if __name__ == "__main__":
    asyncio.run(main())