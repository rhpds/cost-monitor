"""
Dashboard utility classes for performance optimization and data handling.

Contains helper classes for caching, performance monitoring, and data transformation.
"""

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class DataWrapper:
    """Simple wrapper to provide attribute access to dictionary data for compatibility."""

    def __init__(self, data_dict):
        for key, value in data_dict.items():
            setattr(self, key, value)


class DateRangeDebouncer:
    """Simple debouncer for date range changes to improve performance."""

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.last_change_time = 0.0

    def should_process(self) -> bool:
        """Check if enough time has passed since last change."""
        current_time = time.time()
        if current_time - self.last_change_time >= self.delay:
            self.last_change_time = current_time
            return True
        return False


class ChartMemoizer:
    """Simple chart memoization helper for performance optimization."""

    def __init__(self, max_cache_size: int = 50):
        self.cache: dict[str, Any] = {}
        self.access_times: dict[str, float] = {}
        self.max_size = max_cache_size

    def get_cache_key(self, data, params) -> str:
        """Generate cache key from data and parameters."""
        key_data = {
            "data_hash": (
                hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
                if data
                else "empty"
            ),
            "params": params,
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

    def get(self, cache_key):
        """Get cached figure if it exists."""
        if cache_key in self.cache:
            self.access_times[cache_key] = time.time()
            return self.cache[cache_key]
        return None

    def set(self, cache_key, figure):
        """Set cached figure, evicting oldest if necessary."""
        if len(self.cache) >= self.max_size:
            # Remove oldest cache entry
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]

        self.cache[cache_key] = figure
        self.access_times[cache_key] = time.time()


class PerformanceMonitor:
    """Simple performance monitoring for dashboard operations."""

    def __init__(self):
        self.metrics = {}
        self.operation_times = {}

    def start_operation(self, operation_name: str):
        """Start timing an operation."""
        self.operation_times[operation_name] = time.time()

    def end_operation(self, operation_name: str, breakdown: dict[str, float] | None = None):
        """End timing an operation and log the result with optional breakdown."""
        if operation_name in self.operation_times:
            duration = time.time() - self.operation_times[operation_name]

            if operation_name not in self.metrics:
                self.metrics[operation_name] = []

            self.metrics[operation_name].append(duration)

            # Keep only last 10 measurements per operation
            if len(self.metrics[operation_name]) > 10:
                self.metrics[operation_name] = self.metrics[operation_name][-10:]

            avg_time = sum(self.metrics[operation_name]) / len(self.metrics[operation_name])

            # Log performance info
            logger.info(
                f"⚡ Performance: {operation_name} took {duration:.3f}s (avg: {avg_time:.3f}s)"
            )

            # Warn if operation is slow with breakdown details
            if duration > 2.0:
                breakdown_str = ""
                if breakdown:
                    breakdown_parts = [f"{k}:{v:.3f}s" for k, v in breakdown.items()]
                    breakdown_str = f" [Breakdown: {', '.join(breakdown_parts)}]"
                logger.warning(
                    f"🐌 Slow operation detected: {operation_name} took {duration:.3f}s{breakdown_str}"
                )

            del self.operation_times[operation_name]

    def get_stats(self):
        """Get current performance statistics."""
        stats = {}
        for operation, times in self.metrics.items():
            stats[operation] = {
                "count": len(times),
                "avg_time": sum(times) / len(times),
                "last_time": times[-1] if times else 0,
                "max_time": max(times) if times else 0,
            }
        return stats
