from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

log = logging.getLogger("milana_erp_mcp.audit")

SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "entry_hash",
    "file_data",
    "jwt",
    "password",
    "prev_hash",
    "refresh_token",
    "secret",
    "system_config",
    "token",
    "token_hash",
)


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            lower = key_str.lower()
            if lower.startswith("_") or any(part in lower for part in SENSITIVE_KEY_PARTS):
                continue
            sanitized[key_str] = sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_payload(item) for item in value]
    return value


def user_summary(user: Any) -> dict[str, Any] | None:
    if not isinstance(user, dict):
        return None
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "department": user.get("department"),
    }


def audit_tool_call(
    *,
    tool_name: str,
    input_args: dict[str, Any],
    result_status: str,
    authenticated_user: dict[str, Any] | None = None,
    affected_entity: Any = None,
    recipients: Any = None,
    error: Any = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "authenticated_user": user_summary(authenticated_user),
        "tool_name": tool_name,
        "input_arguments": sanitize_payload(input_args),
        "result_status": result_status,
        "affected_entity": sanitize_payload(affected_entity),
        "recipients": sanitize_payload(recipients),
        "error": sanitize_payload(error),
    }
    log.info("mcp_tool_call %s", json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str))
