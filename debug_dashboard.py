#!/usr/bin/env python3
"""
Debug script to test the dashboard API integration locally
"""

import requests
import json
from datetime import date, timedelta

class DataWrapper:
    """Simple wrapper to provide attribute access to dictionary data for compatibility."""
    def __init__(self, data_dict):
        if isinstance(data_dict, dict):
            for key, value in data_dict.items():
                setattr(self, key, value)
        else:
            print(f"WARNING: DataWrapper received non-dict data: {type(data_dict)}")

def test_api_call():
    """Test the exact API call the dashboard makes"""
    print("🔍 Testing dashboard API integration...")

    # API endpoint (same as dashboard uses)
    data_service_url = "http://cost-data-service:8000"  # This won't work locally
    api_url = f"{data_service_url}/api/v1/costs/summary"

    # Test parameters
    start_date = date(2026, 1, 19)
    end_date = date(2026, 1, 20)
    providers = ['aws', 'azure', 'gcp']

    params = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'providers': providers
    }

    print(f"📡 API URL: {api_url}")
    print(f"📊 Params: {params}")

    try:
        print("⚡ Making API request...")
        response = requests.get(api_url, params=params, timeout=30)
        print(f"✅ Response status: {response.status_code}")

        if response.status_code == 200:
            print("✅ API call successful!")

            # Parse JSON response
            api_data = response.json()
            print(f"📋 Response keys: {list(api_data.keys())}")
            print(f"📋 Total cost: ${api_data.get('total_cost', 'N/A')}")
            print(f"📋 Currency: {api_data.get('currency', 'N/A')}")
            print(f"📋 Provider breakdown: {api_data.get('provider_breakdown', {})}")

            # Check required fields
            required_fields = ['combined_daily_costs', 'provider_data']
            for field in required_fields:
                if field in api_data:
                    if field == 'combined_daily_costs':
                        print(f"✅ {field}: {len(api_data[field])} items")
                        if api_data[field]:
                            print(f"  First item: {api_data[field][0]}")
                    elif field == 'provider_data':
                        print(f"✅ {field}: {len(api_data[field])} providers")
                        for provider, data in api_data[field].items():
                            service_count = len(data.get('service_breakdown', {}))
                            print(f"  {provider}: {service_count} services, ${data.get('total_cost', 0):.2f}")
                else:
                    print(f"❌ Missing {field}")
                    return False

            # Test DataWrapper creation (what dashboard does)
            print("\n🔧 Testing DataWrapper creation...")
            try:
                wrapped_data = DataWrapper(api_data)
                print("✅ DataWrapper created successfully")

                # Test attribute access (what dashboard does)
                print("🔍 Testing attribute access...")

                # Test combined_daily_costs access
                if hasattr(wrapped_data, 'combined_daily_costs'):
                    print(f"✅ combined_daily_costs: {len(wrapped_data.combined_daily_costs)} items")
                    if wrapped_data.combined_daily_costs:
                        first_day = wrapped_data.combined_daily_costs[0]
                        print(f"  First day: {first_day}")
                        print(f"  First day type: {type(first_day)}")
                else:
                    print("❌ combined_daily_costs attribute missing")
                    return False

                # Test provider_data access
                if hasattr(wrapped_data, 'provider_data'):
                    print(f"✅ provider_data: {len(wrapped_data.provider_data)} providers")
                    for provider, provider_info in wrapped_data.provider_data.items():
                        print(f"  {provider}: {type(provider_info)}")
                        if hasattr(provider_info, 'service_breakdown'):
                            print(f"    service_breakdown: {len(provider_info.service_breakdown)} services")
                        elif isinstance(provider_info, dict) and 'service_breakdown' in provider_info:
                            print(f"    service_breakdown (dict): {len(provider_info['service_breakdown'])} services")
                else:
                    print("❌ provider_data attribute missing")
                    return False

                print("\n✅ All dashboard data access tests passed!")
                return True

            except Exception as e:
                print(f"❌ DataWrapper creation failed: {e}")
                import traceback
                traceback.print_exc()
                return False

        else:
            print(f"❌ API call failed with status {response.status_code}")
            print(f"Response text: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_with_mock_data():
    """Test with mock API data to isolate dashboard logic"""
    print("\n🧪 Testing with mock API data...")

    # Create mock data matching API response format
    mock_api_data = {
        "total_cost": 138118.5617,
        "currency": "USD",
        "period_start": "2026-01-19",
        "period_end": "2026-01-20",
        "provider_breakdown": {"aws": 138118.5617},
        "combined_daily_costs": [
            {
                "date": "2026-01-20",
                "total_cost": 116972.9736,
                "currency": "USD",
                "provider_breakdown": {"aws": 116972.9736}
            },
            {
                "date": "2026-01-19",
                "total_cost": 21145.5881,
                "currency": "USD",
                "provider_breakdown": {"aws": 21145.5881}
            }
        ],
        "provider_data": {
            "aws": {
                "total_cost": 138118.5617,
                "currency": "USD",
                "service_breakdown": {
                    "Atmail Public Cloud": 100000.0,
                    "Savings Plans for AWS Compute usage": 21888.0,
                    "EC2 - Other": 8152.6236,
                    "EC2": 3954.53
                }
            }
        }
    }

    print(f"📋 Mock data keys: {list(mock_api_data.keys())}")

    try:
        wrapped_data = DataWrapper(mock_api_data)
        print("✅ DataWrapper with mock data created successfully")

        # Test the exact operations the dashboard does
        print("🔍 Testing dashboard operations...")

        # Test daily costs processing
        if hasattr(wrapped_data, 'combined_daily_costs'):
            daily_costs = wrapped_data.combined_daily_costs
            print(f"✅ Got {len(daily_costs)} daily cost entries")

            for i, day_data in enumerate(daily_costs):
                print(f"  Day {i+1}: {day_data}")
                if isinstance(day_data, dict):
                    print(f"    Date: {day_data.get('date')}")
                    print(f"    Total: ${day_data.get('total_cost', 0):.2f}")
                    print(f"    Providers: {list(day_data.get('provider_breakdown', {}).keys())}")

        # Test provider data processing
        if hasattr(wrapped_data, 'provider_data'):
            provider_data = wrapped_data.provider_data
            print(f"✅ Got provider data for: {list(provider_data.keys())}")

            for provider, data in provider_data.items():
                print(f"  {provider}:")
                if isinstance(data, dict):
                    print(f"    Total cost: ${data.get('total_cost', 0):.2f}")
                    services = data.get('service_breakdown', {})
                    print(f"    Services: {len(services)}")
                    for service, cost in list(services.items())[:3]:  # Show first 3
                        print(f"      {service}: ${cost}")

        print("✅ Mock data test completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Mock data test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Dashboard Debug Test Harness")
    print("=" * 50)

    # Test 1: Try real API call (will fail locally but shows what should happen)
    success1 = test_api_call()

    # Test 2: Test with mock data to verify dashboard logic
    success2 = test_with_mock_data()

    print("\n📊 Test Results:")
    print(f"  API call test: {'✅ PASS' if success1 else '❌ FAIL (expected locally)'}")
    print(f"  Mock data test: {'✅ PASS' if success2 else '❌ FAIL'}")

    if success2:
        print("\n🎯 Dashboard logic is working correctly with proper data!")
        print("   Issue likely: API not reachable or returning different format")
    else:
        print("\n⚠️  Dashboard logic has issues that need fixing")