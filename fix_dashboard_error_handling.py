#!/usr/bin/env python3
"""
Fix for dashboard error handling to prevent attribute errors
"""

def create_empty_cost_data():
    """Create a proper empty cost data structure"""
    return {
        'total_cost': 0.0,
        'provider_breakdown': {},
        'daily_costs': [],
        'service_breakdown': {},
        'account_breakdown': {}
    }

def create_datawrapper_from_dict(data_dict):
    """Create a DataWrapper-like object that has the required attributes"""
    class EmptyDataWrapper:
        def __init__(self):
            self.total_cost = 0.0
            self.currency = 'USD'
            self.period_start = None
            self.period_end = None
            self.provider_breakdown = {}
            self.combined_daily_costs = []
            self.provider_data = {}

    if not data_dict or not isinstance(data_dict, dict):
        return EmptyDataWrapper()

    # Create a proper DataWrapper
    class DataWrapper:
        def __init__(self, data_dict):
            for key, value in data_dict.items():
                setattr(self, key, value)

    return DataWrapper(data_dict)

def test_error_handling_fix():
    """Test that the error handling fix works correctly"""
    print("🔧 Testing dashboard error handling fix...")

    # Test 1: Empty dict (current problem)
    print("\n1. Testing with empty dict (current problem):")
    empty_dict = {}
    try:
        # This will fail with current code
        daily_costs = empty_dict.combined_daily_costs  # AttributeError
        print("❌ This shouldn't work")
    except AttributeError as e:
        print(f"❌ Current error: {e}")

    # Test 2: Fixed empty cost data
    print("\n2. Testing with fixed empty cost data:")
    fixed_empty = create_empty_cost_data()
    print(f"✅ Fixed structure: {list(fixed_empty.keys())}")

    # Test 3: DataWrapper-like object for error cases
    print("\n3. Testing DataWrapper for error cases:")
    wrapper = create_datawrapper_from_dict({})
    try:
        print(f"✅ combined_daily_costs: {len(wrapper.combined_daily_costs)}")
        print(f"✅ provider_data: {len(wrapper.provider_data)}")
        print(f"✅ total_cost: {wrapper.total_cost}")
    except AttributeError as e:
        print(f"❌ Error: {e}")

    # Test 4: With real data
    print("\n4. Testing with real data:")
    real_data = {
        'total_cost': 100.0,
        'combined_daily_costs': [{'date': '2026-01-20', 'total_cost': 100.0}],
        'provider_data': {'aws': {'service_breakdown': {}}}
    }
    real_wrapper = create_datawrapper_from_dict(real_data)
    try:
        print(f"✅ combined_daily_costs: {len(real_wrapper.combined_daily_costs)}")
        print(f"✅ provider_data: {len(real_wrapper.provider_data)}")
        print(f"✅ total_cost: {real_wrapper.total_cost}")
    except AttributeError as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_error_handling_fix()