#!/usr/bin/env python3
"""Health check script for both data service and dashboard"""

import argparse
import os
import sys
from typing import Any

import requests


def check_data_service() -> dict[str, Any]:
    """Health check for data service"""
    try:
        # Check API health endpoint
        response = requests.get("http://localhost:8000/api/health/ready", timeout=5)
        if response.status_code != 200:
            return {"status": "unhealthy", "reason": f"API returned {response.status_code}"}

        # Check database connectivity
        db_response = requests.get("http://localhost:8000/api/health/db", timeout=5)
        if db_response.status_code != 200:
            return {"status": "unhealthy", "reason": "Database connectivity failed"}

        # Check Redis connectivity
        redis_response = requests.get("http://localhost:8000/api/health/redis", timeout=5)
        if redis_response.status_code != 200:
            return {"status": "unhealthy", "reason": "Redis connectivity failed"}

        return {"status": "healthy", "reason": "All checks passed"}

    except requests.exceptions.RequestException as e:
        return {"status": "unhealthy", "reason": f"Request failed: {e}"}
    except Exception as e:
        return {"status": "unhealthy", "reason": f"Unexpected error: {e}"}


def check_dashboard() -> dict[str, Any]:
    """Health check for dashboard service"""
    try:
        # Check if Dash app is responding
        response = requests.get("http://localhost:8050/_dash-layout", timeout=5)
        if response.status_code not in [200, 404]:  # 404 is OK for layout endpoint
            return {"status": "unhealthy", "reason": f"Dashboard returned {response.status_code}"}

        # Check data service connectivity
        data_service_url = os.getenv("DATA_SERVICE_URL", "http://cost-data-service:8000")
        try:
            data_response = requests.get(f"{data_service_url}/api/health/ready", timeout=3)
            if data_response.status_code != 200:
                return {"status": "degraded", "reason": "Data service unreachable"}
        except Exception:
            return {"status": "degraded", "reason": "Cannot reach data service"}

        return {"status": "healthy", "reason": "Dashboard operational"}

    except requests.exceptions.RequestException as e:
        return {"status": "unhealthy", "reason": f"Request failed: {e}"}
    except Exception as e:
        return {"status": "unhealthy", "reason": f"Unexpected error: {e}"}


def main():
    parser = argparse.ArgumentParser(description="Health check for cost monitor services")
    parser.add_argument(
        "--service", required=True, choices=["data-service", "dashboard"], help="Service to check"
    )

    args = parser.parse_args()

    if args.service == "data-service":
        result = check_data_service()
    elif args.service == "dashboard":
        result = check_dashboard()
    else:
        print(f"Unknown service: {args.service}")
        sys.exit(1)

    print(f"Health check result: {result}")

    if result["status"] == "healthy":
        sys.exit(0)
    elif result["status"] == "degraded":
        print(f"Service degraded: {result['reason']}")
        sys.exit(0)  # Still return OK for degraded state
    else:
        print(f"Service unhealthy: {result['reason']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
