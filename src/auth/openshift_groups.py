"""OpenShift group resolution and authorization.

Queries the OpenShift API for group membership and enforces access control.
Replicates the pattern from parsec's src/routes/query.py.
"""

import logging
import os
import ssl
import time

import httpx

logger = logging.getLogger(__name__)

_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
_K8S_API = "https://kubernetes.default.svc"

_groups_cache: list[dict] = []
_groups_cache_time: float = 0
_GROUPS_CACHE_TTL = 60  # seconds

# Auth configuration — set via environment or config.yaml
_allowed_groups: str = os.environ.get(
    "AUTH_ALLOWED_GROUPS", "rhpds-admins,cost-monitor-local-users"
)
_allowed_users: str = os.environ.get("AUTH_ALLOWED_USERS", "")


def configure(allowed_groups: str, allowed_users: str) -> None:
    """Set allowed groups/users from config at startup."""
    global _allowed_groups, _allowed_users
    _allowed_groups = allowed_groups
    _allowed_users = allowed_users


async def _fetch_openshift_groups() -> list[dict]:
    """Fetch all OpenShift groups from the API, cached for 60s."""
    global _groups_cache, _groups_cache_time
    if _groups_cache and time.time() - _groups_cache_time < _GROUPS_CACHE_TTL:
        return _groups_cache

    if not os.path.exists(_SA_TOKEN_PATH):
        logger.debug("Not running in OpenShift — skipping group lookup")
        return []

    try:
        with open(_SA_TOKEN_PATH) as f:
            token = f.read().strip()

        ssl_ctx = ssl.create_default_context(cafile=_SA_CA_PATH)
        async with httpx.AsyncClient(verify=ssl_ctx) as client:
            resp = await client.get(
                f"{_K8S_API}/apis/user.openshift.io/v1/groups",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            _groups_cache = data.get("items", [])
            _groups_cache_time = time.time()
            logger.debug("Fetched %d OpenShift groups", len(_groups_cache))
            return _groups_cache
    except Exception:
        logger.warning("Failed to fetch OpenShift groups", exc_info=True)
        return _groups_cache  # return stale cache on error


async def _get_user_groups(user: str) -> set[str]:
    """Get the OpenShift groups a user belongs to."""
    groups = await _fetch_openshift_groups()
    return {g["metadata"]["name"].lower() for g in groups if user in g.get("users", [])}


async def check_user_allowed(user: str | None) -> tuple[bool, str]:
    """Check if user is authorized via group membership or email whitelist.

    Returns (allowed, reason) tuple.
    """
    # Check group membership first
    if _allowed_groups and user:
        allowed_groups = {g.strip().lower() for g in _allowed_groups.split(",") if g.strip()}
        if allowed_groups:
            user_groups = await _get_user_groups(user)
            if user_groups & allowed_groups:
                return True, "group"

            # Groups configured but user not in any — check email fallback
            if _allowed_users:
                allowed = {u.strip().lower() for u in _allowed_users.split(",") if u.strip()}
                if allowed and user.lower() in allowed:
                    return True, "email"

            # Neither matched
            user_groups_str = ", ".join(sorted(user_groups)) if user_groups else "(none)"
            logger.warning("Access denied for user '%s' — not in allowed groups or users", user)
            logger.warning("  Allowed groups: %s", ", ".join(sorted(allowed_groups)))
            logger.warning("  User groups: %s", user_groups_str)
            return False, "not_in_group"

    if not user and _allowed_groups:
        logger.warning("Access denied: no user identity in request headers")
        return False, "no_identity"

    # No group restriction — fall back to email-only check
    if not _allowed_users:
        return True, "no_restriction"
    allowed = {u.strip().lower() for u in _allowed_users.split(",") if u.strip()}
    if not allowed:
        return True, "no_restriction"
    if not user:
        logger.warning("Access denied: no user identity in request headers")
        return False, "no_identity"
    if user.lower() in allowed:
        return True, "email"
    logger.warning("Access denied for user '%s' — not in allowed_users list", user)
    return False, "not_in_list"
