#!/usr/bin/env python3
"""
Debug script to test the exact dashboard callback logic
"""

import requests
import json
from datetime import date
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DataWrapper:
    """Simple wrapper to provide attribute access to dictionary data for compatibility."""
    def __init__(self, data_dict):
        for key, value in data_dict.items():
            setattr(self, key, value)

def test_dashboard_data_processing():
    """Test the exact data processing logic from the dashboard callback"""
    print("🔍 Testing dashboard callback data processing...")

    # Step 1: Simulate API call
    api_url = "http://cost-data-service:8000/api/v1/costs/summary"
    params = {
        'start_date': '2026-01-19',
        'end_date': '2026-01-20',
        'providers': ['aws', 'azure', 'gcp']
    }

    try:
        print("📡 Making API call...")
        response = requests.get(api_url, params=params, timeout=30)
        response.raise_for_status()

        api_data = response.json()
        print(f"✅ API call successful, got {len(api_data)} fields")

        # Step 2: Create DataWrapper (what get_cost_data does)
        print("🔧 Creating DataWrapper...")
        real_cost_data = DataWrapper(api_data)
        print("✅ DataWrapper created")

        # Step 3: Test exact callback logic
        print("🔍 Testing callback data transformation...")

        # Check if real_cost_data has required attributes
        if hasattr(real_cost_data, 'combined_daily_costs'):
            print(f"✅ real_cost_data.combined_daily_costs exists: {len(real_cost_data.combined_daily_costs)} items")
        else:
            print("❌ real_cost_data.combined_daily_costs missing!")
            return False

        if hasattr(real_cost_data, 'provider_data'):
            print(f"✅ real_cost_data.provider_data exists: {len(real_cost_data.provider_data)} providers")
        else:
            print("❌ real_cost_data.provider_data missing!")
            return False

        # Step 4: Test the exact transformation logic from the callback
        transformed_daily_costs = []
        print("🔄 Transforming daily costs...")

        for i, daily_entry in enumerate(real_cost_data.combined_daily_costs):
            print(f"  Processing day {i+1}: {type(daily_entry)}")
            print(f"    Keys: {list(daily_entry.keys()) if isinstance(daily_entry, dict) else 'not a dict'}")

            transformed_entry = {
                'date': daily_entry['date'],
                'total_cost': daily_entry['total_cost'],
                'currency': daily_entry['currency'],
            }

            # Flatten provider breakdown
            if 'provider_breakdown' in daily_entry:
                provider_breakdown_data = daily_entry['provider_breakdown']
                transformed_entry['aws'] = provider_breakdown_data.get('aws', 0)
                transformed_entry['azure'] = provider_breakdown_data.get('azure', 0)
                transformed_entry['gcp'] = provider_breakdown_data.get('gcp', 0)
            else:
                transformed_entry['aws'] = 0
                transformed_entry['azure'] = 0
                transformed_entry['gcp'] = 0

            transformed_daily_costs.append(transformed_entry)
            print(f"    ✅ Transformed: {transformed_entry}")

        print(f"✅ Transformed {len(transformed_daily_costs)} daily cost entries")

        # Step 5: Test service breakdown processing
        print("🔄 Processing service breakdown...")
        service_breakdown = {}
        for provider_name, provider_data in real_cost_data.provider_data.items():
            print(f"  Processing provider: {provider_name} ({type(provider_data)})")
            if hasattr(provider_data, 'service_breakdown'):
                service_breakdown[provider_name] = provider_data.service_breakdown
                print(f"    ✅ Got {len(provider_data.service_breakdown)} services")
            elif isinstance(provider_data, dict) and 'service_breakdown' in provider_data:
                service_breakdown[provider_name] = provider_data['service_breakdown']
                print(f"    ✅ Got {len(provider_data['service_breakdown'])} services (dict access)")
            else:
                print(f"    ❌ No service_breakdown found for {provider_name}")

        # Step 6: Build final cost_data object (like callback does)
        print("🔄 Building final cost_data object...")
        cost_data = {
            'total_cost': real_cost_data.total_cost,
            'provider_breakdown': real_cost_data.provider_breakdown,
            'daily_costs': transformed_daily_costs,
            'service_breakdown': service_breakdown,
            'account_breakdown': {}
        }

        print("✅ Final cost_data structure:")
        for key, value in cost_data.items():
            if isinstance(value, (list, dict)):
                print(f"  {key}: {len(value)} items")
            else:
                print(f"  {key}: {value}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_dashboard_data_processing()
    if success:
        print("\n🎯 Dashboard data processing logic works correctly!")
    else:
        print("\n⚠️ Dashboard data processing has issues")