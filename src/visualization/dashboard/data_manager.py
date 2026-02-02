"""
Cost data management for the dashboard.

Handles API calls to the data service, caching, and data formatting
for dashboard consumption.
"""

import logging
import os
import time
from datetime import date
from typing import Any

import requests

from .utils import DataWrapper

logger = logging.getLogger(__name__)


class CostDataManager:
    """Manages cost data retrieval from the data service API with Redis caching."""

    def __init__(self, config=None):
        self.data_service_url = os.getenv("DATA_SERVICE_URL", "http://cost-data-service:8000")
        self._dashboard_cache = None
        self._last_fetch_times = {}  # Track last fetch times per cache key

        # Initialize Redis cache for dashboard-level caching
        try:
            from src.utils.cache import RedisCache

            self._dashboard_cache = RedisCache(
                default_ttl=60,  # Short TTL for dashboard cache (1 minute)
                prefix="cost-monitor:dashboard:",
            )
            logger.info("Dashboard Redis cache initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize dashboard Redis cache: {e}")
            self._dashboard_cache = None

        logger.info(
            f"CostDataManager initialized for API mode, using data service at: {self.data_service_url}"
        )

    async def initialize(self):
        """Initialize the data manager for API mode."""
        logger.info("Data manager initialized for API mode")
        return True

    def _get_cache_key(self, start_date: date, end_date: date, force_refresh: bool = False) -> str:
        """Generate cache key for the request."""
        return f"cost_data:{start_date}:{end_date}:{force_refresh}"

    async def get_cost_data(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> DataWrapper | None:
        """Get cost data from data service API with Redis caching."""
        cache_key = self._get_cache_key(start_date, end_date, force_refresh)
        current_time = time.time()

        # Check dashboard Redis cache first (unless force_refresh)
        if not force_refresh and self._dashboard_cache:
            try:
                cached_data = self._dashboard_cache.get(cache_key)
                if cached_data:
                    logger.info(f"Dashboard cache HIT for {start_date} to {end_date}")
                    return DataWrapper(cached_data)
            except Exception as e:
                logger.warning(f"Dashboard cache get failed: {e}")

        # Check if we've fetched this data very recently (prevent rapid duplicate calls)
        last_fetch = self._last_fetch_times.get(cache_key, 0)
        if current_time - last_fetch < 5:  # 5 second cooldown
            logger.warning(
                f"Rate limiting API call for {start_date} to {end_date} (last fetch {current_time - last_fetch:.1f}s ago)"
            )
            return None

        logger.info(
            f"Fetching cost data from API for {start_date} to {end_date} (force_refresh={force_refresh})"
        )
        self._last_fetch_times[cache_key] = current_time

        try:
            # Call data service API - now returns data in dashboard format
            url = f"{self.data_service_url}/api/v1/costs/summary"
            params = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "providers": ["aws", "azure", "gcp"],
                "force_refresh": str(force_refresh).lower(),  # Convert bool to string
            }

            # Calculate appropriate timeout based on date range
            date_range_days = (end_date - start_date).days + 1 if start_date and end_date else 1
            if date_range_days > 7:
                # Long operations need more time for account collection
                api_timeout = min(
                    600, 60 + (date_range_days * 5)
                )  # Max 10 minutes, ~5 seconds per day
                logger.info(
                    f"📊 Using extended timeout {api_timeout}s for {date_range_days}-day range"
                )
            else:
                api_timeout = 30  # Standard timeout for short ranges

            response = requests.get(url, params=params, timeout=api_timeout)
            response.raise_for_status()

            # API now returns data in the exact format dashboard expects
            api_data = response.json()

            # Cache the API response in Redis for dashboard-level caching
            if self._dashboard_cache:
                try:
                    self._dashboard_cache.set(cache_key, api_data)
                    logger.debug(f"Cached dashboard data for {start_date} to {end_date}")
                except Exception as e:
                    logger.warning(f"Failed to cache dashboard data: {e}")

            logger.info(f"Retrieved cost data from API, total: ${api_data['total_cost']:.2f}")
            return DataWrapper(api_data)

        except Exception as e:
            logger.error(f"Failed to get cost data from API: {e}")
            # Return a proper empty DataWrapper instead of None to prevent attribute errors
            empty_data = {
                "total_cost": 0.0,
                "currency": "USD",
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "provider_breakdown": {},
                "combined_daily_costs": [],
                "provider_data": {},
                "account_breakdown": {},
            }
            return DataWrapper(empty_data)

    async def get_service_breakdown(
        self, provider: str, start_date: date, end_date: date, top_n: int = 10
    ) -> dict[str, float]:
        """Get service cost breakdown for a specific provider from API."""
        try:
            url = f"{self.data_service_url}/api/v1/costs"
            params = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "providers": [provider],
            }

            # Calculate appropriate timeout based on date range
            date_range_days = (end_date - start_date).days + 1 if start_date and end_date else 1
            if date_range_days > 7:
                # Long operations need more time for data collection
                api_timeout = min(
                    600, 60 + (date_range_days * 5)
                )  # Max 10 minutes, ~5 seconds per day
                logger.info(
                    f"📊 Service breakdown using extended timeout {api_timeout}s for {date_range_days}-day range"
                )
            else:
                api_timeout = 30  # Standard timeout for short ranges

            response = requests.get(url, params=params, timeout=api_timeout)
            response.raise_for_status()

            detailed_data = response.json()
            service_costs: dict[str, float] = {}

            for item in detailed_data:
                if item.get("provider") == provider:
                    service = item.get("service_name", "Unknown")
                    cost = item.get("cost", 0)
                    service_costs[service] = service_costs.get(service, 0) + cost

            # Return top N services
            sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)[
                :top_n
            ]
            return dict(sorted_services)

        except Exception as e:
            logger.error(f"Failed to get service breakdown for {provider}: {e}")
            return {}

    async def get_account_breakdown_data(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> dict | None:
        """Get account breakdown data from API."""
        logger.info(f"Fetching account breakdown data for {start_date} to {end_date}")

        # Use the same data as regular cost data, process for account breakdown
        cost_data = await self.get_cost_data(start_date, end_date, force_refresh)
        if cost_data:
            return getattr(cost_data, "account_breakdown", {})
        return {}

    def get_auth_status(self) -> dict[str, Any]:
        """Get authentication status from the data service API."""
        try:
            url = f"{self.data_service_url}/api/v1/auth/status"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            auth_status: dict[str, Any] = response.json()
            logger.info("📡 AUTH STATUS: Retrieved authentication status from API")
            return auth_status

        except Exception as e:
            logger.error(f"📡 AUTH STATUS: Failed to get auth status from API: {e}")
            return {"providers": {}, "error": str(e)}
