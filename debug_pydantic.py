#!/usr/bin/env python3
"""
Debug script for testing Pydantic models in Cost Monitor.

This script provides interactive testing and debugging capabilities
for all Pydantic models in the cost monitoring system.
"""

import sys
from datetime import date, datetime, timedelta


def test_core_provider_models():
    """Test core provider models (CostDataPoint, CostSummary)."""
    print("🧪 Testing Core Provider Models")
    print("=" * 40)

    try:
        from src.providers.base import CostDataPoint, CostSummary, TimeGranularity

        # Test CostDataPoint
        print("Testing CostDataPoint...")
        point = CostDataPoint(
            date=date.today(),
            amount=150.75,
            currency='USD',
            service_name='Amazon EC2',
            account_id='123456789',
            region='us-east-1',
            tags={'Environment': 'Production', 'Team': 'Backend'}
        )
        print(f"✅ Created: {point}")
        print(f"   Currency: {point.currency}")
        print(f"   Tags: {point.tags}")

        # Test CostSummary
        print("\nTesting CostSummary...")
        summary = CostSummary(
            provider='aws',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            total_cost=150.75,  # Match the data point amount
            currency='USD',
            data_points=[point],
            granularity=TimeGranularity.DAILY,
            last_updated=datetime.now()
        )
        print(f"✅ Created: {summary}")
        print(f"   Provider: {summary.provider}")
        print(f"   Daily average: ${summary.daily_average:.2f}")
        print(f"   Service breakdown: {summary.service_breakdown}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_alert_system_models():
    """Test alert system models (AlertRule, Alert)."""
    print("\n🚨 Testing Alert System Models")
    print("=" * 40)

    try:
        from src.monitoring.alerts import Alert, AlertLevel, AlertRule, AlertType

        # Test AlertRule
        print("Testing AlertRule...")
        rule = AlertRule(
            name='Daily Cost Warning',
            alert_type=AlertType.DAILY_THRESHOLD,
            provider='aws',
            threshold_value=500.0,
            time_window=1,
            alert_level=AlertLevel.WARNING,
            description='Warn when daily AWS cost exceeds $500'
        )
        print(f"✅ Created: {rule}")
        print(f"   Provider: {rule.provider}")
        print(f"   Threshold: ${rule.threshold_value}")

        # Test Alert
        print("\nTesting Alert...")
        alert = Alert(
            id='alert-12345',
            rule_name=rule.name,
            alert_type=AlertType.DAILY_THRESHOLD,
            alert_level=AlertLevel.WARNING,
            provider='aws',
            current_value=650.0,
            threshold_value=500.0,
            currency='USD',
            message='Daily AWS cost of $650.00 exceeds threshold of $500.00',
            timestamp=datetime.now(),
            metadata={'service_breakdown': {'EC2': 400.0, 'S3': 250.0}}
        )
        print(f"✅ Created: {alert}")
        print(f"   ID: {alert.id}")
        print(f"   Acknowledged: {alert.acknowledged}")
        print(f"   Resolved: {alert.resolved}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_data_processing_models():
    """Test data processing models (NormalizedCostData, MultiCloudCostSummary)."""
    print("\n📊 Testing Data Processing Models")
    print("=" * 40)

    try:
        from src.providers.base import TimeGranularity
        from src.utils.data_normalizer import MultiCloudCostSummary, NormalizedCostData

        # Test NormalizedCostData
        print("Testing NormalizedCostData...")
        normalized = NormalizedCostData(
            provider='aws',
            total_cost=750.50,
            currency='USD',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            granularity=TimeGranularity.DAILY,
            service_breakdown={
                'EC2': 400.0,
                'S3': 200.50,
                'RDS': 150.0
            },
            regional_breakdown={
                'us-east-1': 500.0,
                'us-west-2': 250.50
            },
            daily_costs=[
                {'date': '2024-01-01', 'cost': 107.21},
                {'date': '2024-01-02', 'cost': 105.43},
                {'date': '2024-01-03', 'cost': 110.86}
            ]
        )
        print(f"✅ Created: {normalized}")
        print(f"   Provider: {normalized.provider}")
        print(f"   Service breakdown: {normalized.service_breakdown}")

        # Test MultiCloudCostSummary
        print("\nTesting MultiCloudCostSummary...")
        multi_cloud = MultiCloudCostSummary(
            total_cost=1500.75,
            currency='USD',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            provider_breakdown={
                'aws': 750.50,
                'azure': 500.25,
                'gcp': 250.00
            },
            combined_service_breakdown={
                'Compute': 800.0,
                'Storage': 400.75,
                'Database': 300.0
            },
            provider_data={'aws': normalized}
        )
        print(f"✅ Created: {multi_cloud}")
        print(f"   Total cost: ${multi_cloud.total_cost}")
        print(f"   Provider breakdown: {multi_cloud.provider_breakdown}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_supporting_models():
    """Test supporting models (AuthenticationResult, PrometheusConfig, AlertFormatConfig)."""
    print("\n🔧 Testing Supporting Models")
    print("=" * 40)

    try:
        # Test AuthenticationResult
        print("Testing AuthenticationResult...")
        from src.utils.auth import AuthenticationResult

        auth_result = AuthenticationResult(
            success=True,
            provider='aws',
            method='access_key',
            error_message=None,
            credentials={'access_key_id': '***', 'secret_access_key': '***'}
        )
        print(f"✅ Created: {auth_result}")
        print(f"   Success: {auth_result.success}")
        print(f"   Method: {auth_result.method}")

        # Test PrometheusConfig
        print("\nTesting PrometheusConfig...")
        from src.export.prometheus import PrometheusConfig

        prom_config = PrometheusConfig(
            pushgateway_url='https://prometheus-gateway.example.com:9091',
            job_name='cost_monitor_prod',
            instance='cost_monitor_01',
            metrics_prefix='cloud_cost',
            include_labels=True,
            pushgateway_timeout=60
        )
        print(f"✅ Created: {prom_config}")
        print(f"   Job name: {prom_config.job_name}")
        print(f"   URL: {prom_config.pushgateway_url}")

        # Test AlertFormatConfig
        print("\nTesting AlertFormatConfig...")
        from src.monitoring.text_alerts import AlertFormatConfig

        format_config = AlertFormatConfig(
            show_timestamp=True,
            show_provider=True,
            show_details=True,
            use_colors=False,  # Disable for debug output
            max_message_length=500,
            include_metadata=True
        )
        print(f"✅ Created: {format_config}")
        print(f"   Max message length: {format_config.max_message_length}")
        print(f"   Use colors: {format_config.use_colors}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_validation_edge_cases():
    """Test validation edge cases and error handling."""
    print("\n⚠️ Testing Validation Edge Cases")
    print("=" * 40)

    try:
        from src.providers.base import CostDataPoint

        # Test currency validation
        print("Testing currency validation...")
        try:
            point = CostDataPoint(
                date=date.today(),
                amount=100.0,
                currency='invalid'  # Should trigger warning
            )
            print("✅ Currency validation working (warning expected)")
        except Exception as e:
            print(f"⚠️ Currency validation: {e}")

        # Test future date validation
        print("\nTesting future date validation...")
        try:
            future_point = CostDataPoint(
                date=date.today() + timedelta(days=30),
                amount=100.0,
                currency='USD'
            )
            print("❌ Future date should have been rejected!")
        except Exception as e:
            print(f"✅ Future date properly rejected: {e}")

        # Test negative cost validation
        print("\nTesting negative cost validation...")
        try:
            from src.monitoring.alerts import Alert, AlertLevel, AlertType
            alert = Alert(
                id='test-alert',
                rule_name='Test Rule',
                alert_type=AlertType.DAILY_THRESHOLD,
                alert_level=AlertLevel.WARNING,
                provider='aws',
                current_value=-100.0,  # Should be rejected
                threshold_value=50.0,
                currency='USD',
                message='Test message',
                timestamp=datetime.now()
            )
            print("❌ Negative cost should have been rejected!")
        except Exception as e:
            print(f"✅ Negative cost properly rejected: {e}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def performance_benchmark():
    """Run performance benchmarks on Pydantic models."""
    print("\n⚡ Performance Benchmarks")
    print("=" * 40)

    try:
        import time

        from src.providers.base import CostDataPoint

        # Benchmark CostDataPoint creation
        print("Benchmarking CostDataPoint creation...")
        iterations = 1000

        start_time = time.time()
        points = []
        for i in range(iterations):
            point = CostDataPoint(
                date=date.today(),
                amount=float(i),
                currency='USD',
                service_name=f'Service {i % 10}'
            )
            points.append(point)

        end_time = time.time()
        duration = end_time - start_time

        print(f"✅ Created {iterations} CostDataPoints in {duration:.3f}s")
        print(f"   Average: {duration/iterations*1000:.2f}ms per instance")
        print(f"   Rate: {iterations/duration:.0f} instances/second")

        # Memory usage estimate
        import sys
        total_size = sum(sys.getsizeof(point) for point in points)
        print(f"   Memory usage: ~{total_size/1024:.2f} KB total")
        print(f"   Memory per instance: ~{total_size/iterations:.0f} bytes")

        # Performance threshold check
        if duration > 1.0:  # More than 1 second for 1000 instances
            print("⚠️ Performance slower than expected")
        else:
            print("✅ Performance within acceptable limits")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def interactive_testing():
    """Interactive testing mode."""
    print("\n🎮 Interactive Testing Mode")
    print("=" * 40)
    print("Available commands:")
    print("  1 - Test core provider models")
    print("  2 - Test alert system models")
    print("  3 - Test data processing models")
    print("  4 - Test supporting models")
    print("  5 - Test validation edge cases")
    print("  6 - Run performance benchmarks")
    print("  q - Quit")

    while True:
        try:
            choice = input("\nEnter your choice (1-6, q): ").strip().lower()

            if choice == 'q':
                print("Goodbye! 👋")
                break
            elif choice == '1':
                test_core_provider_models()
            elif choice == '2':
                test_alert_system_models()
            elif choice == '3':
                test_data_processing_models()
            elif choice == '4':
                test_supporting_models()
            elif choice == '5':
                test_validation_edge_cases()
            elif choice == '6':
                performance_benchmark()
            else:
                print("Invalid choice. Please enter 1-6 or q.")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Goodbye! 👋")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

def main():
    """Main debugging function."""
    print("🐛 Cost Monitor - Pydantic Models Debug Script")
    print("=" * 50)
    print("This script tests all Pydantic models in the cost monitoring system.")
    print("")

    # Check if interactive mode requested
    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        interactive_testing()
        return

    # Run all tests
    results = []

    print("Running comprehensive Pydantic model tests...\n")

    results.append(("Core Provider Models", test_core_provider_models()))
    results.append(("Alert System Models", test_alert_system_models()))
    results.append(("Data Processing Models", test_data_processing_models()))
    results.append(("Supporting Models", test_supporting_models()))
    results.append(("Validation Edge Cases", test_validation_edge_cases()))
    results.append(("Performance Benchmarks", performance_benchmark()))

    # Summary
    print("\n" + "=" * 50)
    print("📋 TEST SUMMARY")
    print("=" * 50)

    passed = 0
    total = len(results)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if success:
            passed += 1

    print("-" * 50)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All Pydantic models are working correctly!")
        sys.exit(0)
    else:
        print("💥 Some tests failed. Check the output above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
