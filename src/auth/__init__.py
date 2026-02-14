"""OpenShift group-based authorization for cost-monitor."""

from src.auth.openshift_groups import check_user_allowed

__all__ = ["check_user_allowed"]
