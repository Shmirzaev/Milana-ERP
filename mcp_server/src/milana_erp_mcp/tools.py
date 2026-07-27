from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from .audit import audit_tool_call
from .client import ERPApiClient, ERPApiError
from .config import Settings, get_settings
from .schemas import ActiveProductionArgs, NotificationArgs, SearchArgs, TaskCreateArgs, TaskListArgs


@dataclass
class ToolExecution:
    response: dict[str, Any]
    status: str = "success"
    affected_entity: Any = None
    recipients: Any = None


async def _run_tool(
    tool_name: str,
    input_args: dict[str, Any],
    handler: Callable[[ERPApiClient, Settings, dict[str, Any]], Awaitable[ToolExecution]],
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
    require_gm: bool = True,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    api = client or ERPApiClient(active_settings)
    user: dict[str, Any] | None = None
    try:
        user = await api.get_me()
        if require_gm and not _is_gm_user(user):
            error = {
                "status_code": 403,
                "message": "Milana ERP MCP v1 is GM-only. Current user needs management.view or an admin role.",
            }
            audit_tool_call(
                tool_name=tool_name,
                input_args=input_args,
                result_status="permission_denied",
                authenticated_user=user,
                error=error,
            )
            return {"ok": False, "error": error}
        execution = await handler(api, active_settings, user)
        audit_tool_call(
            tool_name=tool_name,
            input_args=input_args,
            result_status=execution.status,
            authenticated_user=user,
            affected_entity=execution.affected_entity,
            recipients=execution.recipients,
        )
        return execution.response
    except ValidationError as exc:
        error = {"message": "Invalid tool arguments", "details": exc.errors(include_url=False)}
        audit_tool_call(
            tool_name=tool_name,
            input_args=input_args,
            result_status="validation_error",
            authenticated_user=user,
            error=error,
        )
        return {"ok": False, "error": error}
    except ERPApiError as exc:
        error = exc.to_public_dict()
        audit_tool_call(
            tool_name=tool_name,
            input_args=input_args,
            result_status="api_error",
            authenticated_user=user,
            error=error,
        )
        return {"ok": False, "error": error}
    except Exception:
        error = {"message": "MCP tool failed unexpectedly"}
        audit_tool_call(
            tool_name=tool_name,
            input_args=input_args,
            result_status="internal_error",
            authenticated_user=user,
            error=error,
        )
        return {"ok": False, "error": error}
    finally:
        if client is None:
            await api.aclose()


async def erp_me_tool(*, settings: Settings | None = None, client: ERPApiClient | None = None) -> dict[str, Any]:
    async def handler(_api: ERPApiClient, _settings: Settings, user: dict[str, Any]) -> ToolExecution:
        return ToolExecution({"ok": True, "data": user})

    return await _run_tool("erp_me", {}, handler, settings=settings, client=client, require_gm=False)


async def erp_gm_summary_tool(
    tz: str | None = None,
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {"tz": tz}

    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        params = {"tz": tz} if tz else None
        data = await api.get("/api/dashboard/management", params=params)
        return ToolExecution({"ok": True, "data": data, "source": "/api/dashboard/management"})

    return await _run_tool("erp_gm_summary", args, handler, settings=settings, client=client)


async def erp_search_tool(
    query: str,
    limit_per_type: int = 5,
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {"query": query, "limit_per_type": limit_per_type}

    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = SearchArgs(query=query, limit_per_type=limit_per_type)
        data = await api.get("/api/search", params={"q": parsed.query, "limit_per_type": parsed.limit_per_type})
        return ToolExecution({"ok": True, "data": data, "source": "/api/search"})

    return await _run_tool("erp_search", args, handler, settings=settings, client=client)


async def erp_active_production_tool(
    limit: int = 25,
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {"limit": limit}

    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = ActiveProductionArgs(limit=limit)
        data = await api.get("/api/dashboard/active-production")
        items = data[: parsed.limit] if isinstance(data, list) else data
        return ToolExecution({"ok": True, "data": items, "source": "/api/dashboard/active-production"})

    return await _run_tool("erp_active_production", args, handler, settings=settings, client=client)


async def erp_late_orders_tool(
    limit: int = 25,
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {"limit": limit}

    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = ActiveProductionArgs(limit=limit)
        data = await api.get("/api/dashboard/active-production")
        if not isinstance(data, list):
            return ToolExecution({"ok": True, "data": data, "source": "/api/dashboard/active-production"})
        now = datetime.now(timezone.utc)
        late_items = [item for item in data if _is_late_order(item, now)]
        return ToolExecution(
            {
                "ok": True,
                "data": {
                    "count": len(late_items),
                    "items": late_items[: parsed.limit],
                },
                "source": "/api/dashboard/active-production",
            }
        )

    return await _run_tool("erp_late_orders", args, handler, settings=settings, client=client)


async def erp_inventory_status_tool(
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        data = await api.get("/api/dashboard/inventory")
        return ToolExecution({"ok": True, "data": data, "source": "/api/dashboard/inventory"})

    return await _run_tool("erp_inventory_status", {}, handler, settings=settings, client=client)


async def erp_finance_summary_tool(
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        data = await api.get("/api/dashboard/finance")
        return ToolExecution({"ok": True, "data": data, "source": "/api/dashboard/finance"})

    return await _run_tool("erp_finance_summary", {}, handler, settings=settings, client=client)


async def erp_list_employee_tasks_tool(
    employee: str | None = None,
    department: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scope: str = "all",
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {
        "employee": employee,
        "department": department,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "scope": scope,
    }

    async def handler(api: ERPApiClient, _settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = TaskListArgs(
            employee=employee,
            department=department,
            status=status,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
        params: dict[str, Any] = {"scope": parsed.scope}
        if parsed.status:
            params["status"] = parsed.status
        data = await api.get("/api/tasks", params=params)
        rows = data if isinstance(data, list) else []
        supported_filters = ["scope", "status"]
        client_side_filters: list[str] = []

        if parsed.employee:
            employee_user_id = _parse_user_id(parsed.employee)
            if employee_user_id is None:
                raise ERPApiError(400, "employee filter currently expects a user id", path="/api/tasks")
            rows = [task for task in rows if task.get("assigned_to") == employee_user_id]
            client_side_filters.append("employee")

        if parsed.department:
            department_user_ids = await _department_user_ids(api, parsed.department)
            rows = [task for task in rows if task.get("assigned_to") in department_user_ids]
            client_side_filters.append("department")

        if parsed.date_from or parsed.date_to:
            rows = [
                task
                for task in rows
                if _task_in_due_date_window(task, parsed.date_from, parsed.date_to)
            ]
            client_side_filters.append("due_date")

        return ToolExecution(
            {
                "ok": True,
                "data": rows,
                "source": "/api/tasks",
                "filters": {
                    "api_supported": supported_filters,
                    "client_side": client_side_filters,
                },
            }
        )

    return await _run_tool("erp_list_employee_tasks", args, handler, settings=settings, client=client)


async def erp_send_notification_tool(
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
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {
        "target_type": target_type,
        "user_id": user_id,
        "department": department,
        "safe_group": safe_group,
        "title": title,
        "message": message,
        "link": link,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "confirm": confirm,
    }

    async def handler(api: ERPApiClient, active_settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = NotificationArgs(**args)
        preview = _notification_preview(parsed)
        if active_settings.require_confirmation and not parsed.confirm:
            return ToolExecution(
                {
                    "ok": True,
                    "requires_confirmation": True,
                    "preview": preview,
                    "confirmation_message": "Confirm sending this notification?",
                },
                status="preview",
                recipients=preview["target"],
            )
        payload = parsed.model_dump(exclude={"confirm"}, exclude_none=True, mode="json")
        data = await api.post(active_settings.notification_send_path, json_body=payload)
        return ToolExecution(
            {"ok": True, "data": data, "requires_confirmation": False},
            affected_entity={"type": "Notification", "ids": data.get("notification_ids") if isinstance(data, dict) else None},
            recipients=data.get("recipients") if isinstance(data, dict) else preview["target"],
        )

    return await _run_tool("erp_send_notification", args, handler, settings=settings, client=client)


async def erp_create_task_tool(
    title: str,
    assignee_user_id: int | None = None,
    department: str | None = None,
    description: str | None = None,
    priority: str = "medium",
    due_date: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    confirm: bool = False,
    *,
    settings: Settings | None = None,
    client: ERPApiClient | None = None,
) -> dict[str, Any]:
    args = {
        "title": title,
        "assignee_user_id": assignee_user_id,
        "department": department,
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "confirm": confirm,
    }

    async def handler(api: ERPApiClient, active_settings: Settings, _user: dict[str, Any]) -> ToolExecution:
        parsed = TaskCreateArgs(**args)
        preview = _task_preview(parsed)
        if active_settings.require_confirmation and not parsed.confirm:
            return ToolExecution(
                {
                    "ok": True,
                    "requires_confirmation": True,
                    "preview": preview,
                    "confirmation_message": "Confirm creating this task?",
                },
                status="preview",
                affected_entity={"type": "Task"},
                recipients=preview["assignee"],
            )

        created_tasks: list[dict[str, Any]] = []
        if parsed.assignee_user_id is not None:
            created_tasks.append(await _create_one_task(api, parsed, parsed.assignee_user_id))
        else:
            user_ids = await _department_user_ids(api, parsed.department or "")
            if len(user_ids) > active_settings.max_bulk_recipients:
                raise ERPApiError(
                    400,
                    f"Department has {len(user_ids)} task assignees, above ERP_MCP_MAX_BULK_RECIPIENTS={active_settings.max_bulk_recipients}",
                    path="/api/tasks",
                )
            for target_user_id in user_ids:
                created_tasks.append(await _create_one_task(api, parsed, target_user_id))

        return ToolExecution(
            {
                "ok": True,
                "data": {
                    "created_count": len(created_tasks),
                    "tasks": created_tasks,
                },
                "requires_confirmation": False,
            },
            affected_entity={"type": "Task", "ids": [task.get("id") for task in created_tasks]},
            recipients=[task.get("assigned_to") for task in created_tasks],
        )

    return await _run_tool("erp_create_task", args, handler, settings=settings, client=client)


def _notification_preview(parsed: NotificationArgs) -> dict[str, Any]:
    return {
        "target": {
            "type": parsed.target_type,
            "user_id": parsed.user_id,
            "department": parsed.department,
            "safe_group": parsed.safe_group,
        },
        "title": parsed.title,
        "message": parsed.message,
        "link": parsed.link,
        "linked_entity": {"entity_type": parsed.entity_type, "entity_id": parsed.entity_id}
        if parsed.entity_type or parsed.entity_id
        else None,
    }


def _is_gm_user(user: dict[str, Any]) -> bool:
    permissions = {str(permission) for permission in (user.get("permissions") or [])}
    role = str(user.get("role") or "").strip().lower()
    return "*" in permissions or "management.view" in permissions or role in {"management", "admin", "super admin"}


def _task_preview(parsed: TaskCreateArgs) -> dict[str, Any]:
    return {
        "assignee": {
            "user_id": parsed.assignee_user_id,
            "department": parsed.department,
        },
        "title": parsed.title,
        "description": parsed.description,
        "priority": parsed.priority,
        "due_date": parsed.due_date.isoformat() if parsed.due_date else None,
        "linked_entity": {"entity_type": parsed.entity_type, "entity_id": parsed.entity_id}
        if parsed.entity_type or parsed.entity_id
        else None,
    }


async def _create_one_task(api: ERPApiClient, parsed: TaskCreateArgs, user_id: int) -> dict[str, Any]:
    payload = {
        "title": parsed.title,
        "description": parsed.description,
        "assigned_to": user_id,
        "status": "pending",
        "priority": parsed.priority,
        "due_date": parsed.due_date.isoformat() if parsed.due_date else None,
        "entity_type": parsed.entity_type,
        "entity_id": parsed.entity_id,
    }
    clean_payload = {key: value for key, value in payload.items() if value is not None}
    data = await api.post("/api/tasks", json_body=clean_payload)
    return data if isinstance(data, dict) else {"raw": data}


async def _department_user_ids(api: ERPApiClient, department: str) -> set[int]:
    target = department.strip().lower()
    departments = await api.get("/api/departments")
    dept_id: int | None = None
    if isinstance(departments, list):
        for item in departments:
            if str(item.get("code", "")).lower() == target or str(item.get("name", "")).lower() == target:
                dept_id = int(item["id"])
                break
    if dept_id is None:
        raise ERPApiError(404, "Department not found", path="/api/departments")

    employees = await api.get("/api/employees")
    user_ids = {
        int(item["user_id"])
        for item in employees
        if isinstance(item, dict)
        and item.get("department_id") == dept_id
        and item.get("user_id") is not None
        and item.get("status", "active") == "active"
    }
    if not user_ids:
        raise ERPApiError(404, "No active ERP users found for department", path="/api/employees")
    return user_ids


def _parse_user_id(value: str) -> int | None:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else None


def _is_late_order(item: dict[str, Any], now: datetime) -> bool:
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or "").lower()
    if status in {"delivered", "closed", "cancelled", "canceled"}:
        return False
    deadline = _parse_datetime(item.get("deadline"))
    return bool(deadline and deadline < now)


def _task_in_due_date_window(
    task: dict[str, Any],
    date_from: datetime | None,
    date_to: datetime | None,
) -> bool:
    due_date = _parse_datetime(task.get("due_date"))
    if due_date is None:
        return False
    if date_from and due_date < _as_aware(date_from):
        return False
    if date_to and due_date > _as_aware(date_to):
        return False
    return True


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_aware(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_aware(parsed)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
