"""The reserved, dashboard-only role shared by authentication and provisioning."""

CEO_ROLE_NAME = "CEO"
CEO_DASHBOARD_ONLY_DETAIL = "CEO access is limited to the dashboard"


def is_ceo(user) -> bool:
    return getattr(getattr(user, "role", None), "name", None) == CEO_ROLE_NAME
