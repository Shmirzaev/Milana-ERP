from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from .tools import (
    erp_active_production_tool,
    erp_create_task_tool,
    erp_finance_summary_tool,
    erp_gm_summary_tool,
    erp_inventory_status_tool,
    erp_late_orders_tool,
    erp_list_employee_tasks_tool,
    erp_me_tool,
    erp_search_tool,
    erp_send_notification_tool,
)

logging.basicConfig(level=logging.INFO)

mcp = FastMCP(
    "milana-erp",
    instructions=(
        "Safe Milana ERP GM assistant. Read tools call existing ERP API endpoints. "
        "Write tools are limited to confirmed notifications and task creation."
    ),
)


@mcp.tool(structured_output=True)
async def erp_me() -> dict[str, Any]:
    """Return the current authenticated ERP user, role, department, and permissions."""
    return await erp_me_tool()


@mcp.tool(structured_output=True)
async def erp_gm_summary(tz: str | None = None) -> dict[str, Any]:
    """Return the management dashboard summary for the authenticated GM user."""
    return await erp_gm_summary_tool(tz=tz)


@mcp.tool(structured_output=True)
async def erp_search(query: str, limit_per_type: int = 5) -> dict[str, Any]:
    """Search safe ERP entities through the existing global search endpoint."""
    return await erp_search_tool(query=query, limit_per_type=limit_per_type)


@mcp.tool(structured_output=True)
async def erp_active_production(limit: int = 25) -> dict[str, Any]:
    """Return active production status from the ERP dashboard endpoint."""
    return await erp_active_production_tool(limit=limit)


@mcp.tool(structured_output=True)
async def erp_late_orders(limit: int = 25) -> dict[str, Any]:
    """Return late active orders by filtering the active production dashboard data."""
    return await erp_late_orders_tool(limit=limit)


@mcp.tool(structured_output=True)
async def erp_inventory_status() -> dict[str, Any]:
    """Return the GM-facing inventory dashboard summary."""
    return await erp_inventory_status_tool()


@mcp.tool(structured_output=True)
async def erp_finance_summary() -> dict[str, Any]:
    """Return the finance dashboard summary if the ERP user has finance permission."""
    return await erp_finance_summary_tool()


@mcp.tool(structured_output=True)
async def erp_list_employee_tasks(
    employee: str | None = None,
    department: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scope: str = "all",
) -> dict[str, Any]:
    """List employee tasks through the existing ERP task API with safe filtering."""
    return await erp_list_employee_tasks_tool(
        employee=employee,
        department=department,
        status=status,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
    )


@mcp.tool(structured_output=True)
async def erp_send_notification(
    target_type: str,
    title: str,
    message: str | None = None,
    user_id: int | None = None,
    department: str | None = None,
    safe_group: str | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Preview or send a confirmed ERP notification to a controlled target."""
    return await erp_send_notification_tool(
        target_type=target_type,
        user_id=user_id,
        department=department,
        safe_group=safe_group,
        title=title,
        message=message,
        link=link,
        entity_type=entity_type,
        entity_id=entity_id,
        confirm=confirm,
    )


@mcp.tool(structured_output=True)
async def erp_create_task(
    title: str,
    assignee_user_id: int | None = None,
    department: str | None = None,
    description: str | None = None,
    priority: str = "medium",
    due_date: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Preview or create a confirmed ERP task through the existing task API."""
    return await erp_create_task_tool(
        title=title,
        assignee_user_id=assignee_user_id,
        department=department,
        description=description,
        priority=priority,
        due_date=due_date,
        entity_type=entity_type,
        entity_id=entity_id,
        confirm=confirm,
    )


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
