"""HTTP client utilities for dashboard service"""

from typing import Any

import requests


class HTTPClient:
    """Simple HTTP client wrapper"""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.timeout = timeout

    def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """Make GET request"""
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def health_check(self) -> bool:
        """Check service health"""
        try:
            response = self.session.get(f"{self.base_url}/api/health/ready", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
