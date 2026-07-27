# Milana ERP MCP Server

First-version MCP server for an AI GM Assistant. It lets Claude Desktop, ChatGPT, or another MCP-compatible client answer GM-level ERP questions by calling the existing Milana FastAPI backend.

The MCP server does not connect to the database. It calls authenticated ERP API endpoints and relies on the ERP backend for authentication, permissions, rate limits, audit behavior, and business rules.

## Architecture

```text
GM in Claude/ChatGPT
-> Milana ERP MCP Server
-> ERP Auth and Permissions
-> Existing FastAPI ERP API
-> ERP database/tasks/notifications
```

The first implementation is Python because the ERP backend is Python/FastAPI and the repo already uses Python tooling.

## Install

From the repository root:

```powershell
python -m pip install -e .\mcp_server
```

Or from `mcp_server/`:

```powershell
python -m pip install -e .
```

## Required Environment

```text
ERP_API_BASE_URL=http://localhost:8000
ERP_MCP_AUTH_MODE=bearer
ERP_MCP_BEARER_TOKEN=REPLACE_WITH_REAL_ERP_TOKEN
ERP_MCP_REQUIRE_CONFIRMATION=true
ERP_MCP_MAX_BULK_RECIPIENTS=25
```

Optional:

```text
ERP_MCP_HTTP_TIMEOUT_SECONDS=10
ERP_MCP_NOTIFICATION_SEND_PATH=/api/notifications/send
```

Use a real ERP bearer token for the GM or authenticated ERP user. Do not create a shared admin token for this integration.

## Run Locally

Start the ERP backend first, then run the stdio MCP server:

```powershell
$env:ERP_API_BASE_URL="http://localhost:8000"
$env:ERP_MCP_BEARER_TOKEN="REPLACE_WITH_REAL_ERP_TOKEN"
python -m milana_erp_mcp.server
```

The current transport is stdio for local MCP clients. The tool logic is separate from the transport so a streamable HTTP or HTTPS MCP deployment can reuse the same package later.

## Claude Desktop Example

For production, use the live ERP URL:

```json
{
  "mcpServers": {
    "milana-erp": {
      "command": "python",
      "args": ["-m", "milana_erp_mcp.server"],
      "env": {
        "ERP_API_BASE_URL": "https://erp.milanapremium.uz",
        "ERP_MCP_BEARER_TOKEN": "REPLACE_WITH_REAL_ERP_TOKEN",
        "ERP_MCP_REQUIRE_CONFIRMATION": "true"
      }
    }
  }
}
```

Local development example:

```json
{
  "mcpServers": {
    "milana-erp": {
      "command": "python",
      "args": ["-m", "milana_erp_mcp.server"],
      "env": {
        "ERP_API_BASE_URL": "http://localhost:8000",
        "ERP_MCP_BEARER_TOKEN": "REPLACE_WITH_REAL_ERP_TOKEN",
        "ERP_MCP_REQUIRE_CONFIRMATION": "true"
      }
    }
  }
}
```

If `milana_erp_mcp` is not importable from Claude Desktop, install the package with `python -m pip install -e .\mcp_server` using the same Python executable Claude Desktop will run.

## Claude Home / Desktop Extension

Claude Home chat may not load raw `claude_desktop_config.json` stdio servers in newer Claude Desktop builds. For that case, this repo includes a local Desktop Extension package source:

```text
mcp_server/claude_desktop_extension/
```

Build the installable package:

```powershell
npx --yes @anthropic-ai/mcpb validate .\mcp_server\claude_desktop_extension\manifest.json
npx --yes @anthropic-ai/mcpb pack .\mcp_server\claude_desktop_extension .\mcp_server\milana-erp.mcpb
```

Install `mcp_server\milana-erp.mcpb` from Claude Desktop Settings -> Extensions -> Install Extension. The extension does not bundle credentials; it reads the existing local ERP MCP bearer token from the Claude config on the same PC.

The local package ID used by Claude is:

```text
local.mcpb.milana-premium.milana-erp
```

## Tools

Read-only:

- `erp_me`: current ERP user, role, department, and permissions from `/api/auth/me`.
- `erp_gm_summary`: management dashboard from `/api/dashboard/management`.
- `erp_search`: global search from `/api/search`, with MCP-side field redaction.
- `erp_active_production`: active production dashboard from `/api/dashboard/active-production`.
- `erp_late_orders`: late active orders derived from active production dashboard deadlines.
- `erp_inventory_status`: inventory dashboard from `/api/dashboard/inventory`.
- `erp_finance_summary`: finance dashboard from `/api/dashboard/finance` if ERP permissions allow it.
- `erp_list_employee_tasks`: task list from `/api/tasks`; employee, department, and due-date filters are applied safely when the current API does not support them directly.

Write tools:

- `erp_send_notification`: preview first, then confirmed send through `/api/notifications/send`.
- `erp_create_task`: preview first, then confirmed task creation through `/api/tasks`.

Write tools require `confirm=true` when `ERP_MCP_REQUIRE_CONFIRMATION=true`. Without confirmation they return only:

```json
{
  "requires_confirmation": true,
  "preview": {},
  "confirmation_message": "Confirm ...?"
}
```

## Security Limits

The MCP server intentionally does not implement tools that edit, delete, approve, reject, modify payroll, change finance records, change inventory, change shipments, change production approvals, change user permissions, or mutate raw database records.

Other v1 limits:

- GM-only access is expected. Department-scoped access can be added later.
- MCP v1 blocks all tools except `erp_me` unless `/api/auth/me` shows `management.view`, `*`, or a Management/Admin/Super Admin role.
- No direct database access.
- No frontend automation.
- No hardcoded credentials.
- No global admin bypass token.
- Notification `safe_group` is limited to `management` and `admins`. Sending to everyone is not supported in v1.
- Bulk notification and department task actions are capped by `ERP_MCP_MAX_BULK_RECIPIENTS`.
- Finance data is exposed only through the existing GM-facing dashboard endpoint and existing ERP permissions.
- MCP audit logs redact token, password, secret, hash, API key, file data, and hidden internal keys before logging.

## Audit

Every MCP tool call is logged to the `milana_erp_mcp.audit` logger with:

- authenticated ERP user from `/api/auth/me`
- tool name
- sanitized input arguments
- result status
- timestamp
- affected entity or recipients when present

Confirmed notification sends and task creations also go through ERP backend endpoints. Task creation uses the existing task audit behavior. Notification send uses the ERP audit logger in `backend/app/api/routes/notifications.py`.

## Tests

Run the MCP tests without a live ERP backend:

```powershell
cd mcp_server
python -m pytest
```

The tests mock the ERP API and cover:

- `erp_me`
- `erp_search`
- `erp_gm_summary`
- notification preview without confirmation
- confirmed notification send through a mocked endpoint
- task preview without confirmation
- clean permission/API error handling
