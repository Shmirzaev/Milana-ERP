from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx


DEFAULT_BASE_URL = "https://erp.milanapremium.uz"
DEFAULT_ENV_PATH = Path(".codex-work/erp-monitor.env")
DEFAULT_TIMEZONE = "Asia/Tashkent"


class MonitorConfigError(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MonitorConfigError(f"{name} is required")
    return value


class ERPClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout_seconds, follow_redirects=False)
        self.token: str | None = os.environ.get("ERP_MONITOR_BEARER_TOKEN", "").strip() or None

    def close(self) -> None:
        self.client.close()

    def login(self, email: str, password: str) -> None:
        if self.token:
            return
        response = self.client.post(
            "/api/auth/token",
            data={"username": email, "password": password},
            headers={"Accept": "application/json", "User-Agent": "milana-erp-daily-monitor/1.0"},
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise MonitorConfigError("ERP did not return an access token")
        self.token = str(token)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise MonitorConfigError("ERP client is not authenticated")
        response = self.client.get(
            path,
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "milana-erp-daily-monitor/1.0",
            },
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


def safe_get(client: ERPClient, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "data": client.get(path, params=params), "path": path}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"HTTP {exc.response.status_code}", "path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


def parse_dt(value: Any, tz: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def fmt_number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def fmt_metric(label: str, value: Any) -> str:
    return f"- {label}: {fmt_number(value)}"


def changed_field_names(row: dict[str, Any], limit: int = 5) -> str:
    fields = []
    for change in row.get("changed_fields") or []:
        field = change.get("field")
        if field:
            fields.append(str(field).replace("_", " "))
    if not fields:
        return ""
    suffix = "" if len(fields) <= limit else f", plus {len(fields) - limit} more"
    return f" ({', '.join(fields[:limit])}{suffix})"


def top_counter_lines(counter: Counter, empty_label: str, limit: int = 8) -> list[str]:
    if not counter:
        return [f"- {empty_label}"]
    return [f"- {name}: {count}" for name, count in counter.most_common(limit)]


def build_suggestions(rows: list[dict[str, Any]], dashboards: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    action_counts = Counter(str(row.get("action") or "unknown") for row in rows)
    entity_counts = Counter(str(row.get("entity_type") or "unknown") for row in rows)
    repeated_entities = Counter(
        (str(row.get("entity_type") or "unknown"), row.get("entity_id"))
        for row in rows
        if row.get("entity_id") is not None
    )
    management = dashboards.get("management", {}).get("data") if dashboards.get("management", {}).get("ok") else {}
    production = dashboards.get("production", {}).get("data") if dashboards.get("production", {}).get("ok") else {}

    if not rows:
        suggestions.append(
            "No audited user activity appeared in the window. If people were working, check that key workflows call the audit logger."
        )
    if int((management or {}).get("late_orders") or 0) > 0:
        suggestions.append(
            "There are late orders. A small daily late-order triage view with owner, blocker, and next action would make follow-up easier."
        )
    if float((management or {}).get("todays_defects") or 0) > 0:
        suggestions.append(
            "Defects were recorded today. Add a quick defect reason picker near sewing/printing scans so managers can see causes without asking users later."
        )
    if int((production or {}).get("active_work_orders") or 0) > 0 and not rows:
        suggestions.append(
            "Production has active work orders but no matching audit changes. Consider logging status transitions and scan totals more consistently."
        )
    hash_check = dashboards.get("hash_chain", {}).get("data") if dashboards.get("hash_chain", {}).get("ok") else {}
    if isinstance(hash_check, dict) and hash_check.get("ok") is False:
        suggestions.append(
            "The audit hash-chain verification is not passing. Review the first mismatch before relying on the audit trail for compliance checks."
        )
    if action_counts.get("delete", 0) > 0:
        suggestions.append(
            "Deletes happened in the window. For safer operations, prefer cancel/archive flows with a required reason instead of hard deletion."
        )
    if action_counts.get("update", 0) >= 10:
        suggestions.append(
            "Many updates were made. Review the busiest forms for better defaults, bulk actions, or fewer required back-and-forth edits."
        )

    busiest = [(key, count) for key, count in repeated_entities.most_common(3) if count >= 4]
    for (entity_type, entity_id), count in busiest:
        suggestions.append(
            f"{entity_type} #{entity_id} changed {count} times. If this is normal, a guided workflow or change summary panel may reduce user confusion."
        )

    if entity_counts.get("Task", 0) >= 5:
        suggestions.append(
            "Tasks changed frequently. Add a compact task board filtered by department and overdue status so managers can scan work faster."
        )
    if entity_counts.get("StockMovement", 0) + entity_counts.get("StockBatch", 0) >= 5:
        suggestions.append(
            "Inventory activity was high. A scan-first storage screen with recent batches and common actions would reduce clicks for warehouse users."
        )
    if not suggestions:
        suggestions.append(
            "Activity looks steady. The next useful improvement is a daily manager dashboard card showing new, blocked, late, and completed work by department."
        )
    return suggestions[:8]


def render_report(
    *,
    base_url: str,
    tz: ZoneInfo,
    start_local: datetime,
    end_local: datetime,
    me: dict[str, Any],
    audit_response: dict[str, Any],
    dashboards: dict[str, Any],
) -> str:
    rows = audit_response.get("rows") if isinstance(audit_response, dict) else audit_response
    if not isinstance(rows, list):
        rows = []
    total = audit_response.get("total", len(rows)) if isinstance(audit_response, dict) else len(rows)

    user_counts = Counter(str(row.get("user_name") or "System") for row in rows)
    action_counts = Counter(str(row.get("action_label") or row.get("action") or "unknown") for row in rows)
    entity_counts = Counter(str(row.get("entity_label") or row.get("entity_type") or "unknown") for row in rows)

    management = dashboards.get("management", {}).get("data") if dashboards.get("management", {}).get("ok") else {}
    production = dashboards.get("production", {}).get("data") if dashboards.get("production", {}).get("ok") else {}
    inventory = dashboards.get("inventory", {}).get("data") if dashboards.get("inventory", {}).get("ok") else {}
    finance = dashboards.get("finance", {}).get("data") if dashboards.get("finance", {}).get("ok") else {}
    hash_check = dashboards.get("hash_chain", {}).get("data") if dashboards.get("hash_chain", {}).get("ok") else {}

    lines: list[str] = []
    lines.append("# Milana ERP Daily Activity Report")
    lines.append("")
    lines.append(f"Window: {start_local:%Y-%m-%d %H:%M} to {end_local:%Y-%m-%d %H:%M} ({tz.key})")
    lines.append(f"Source: {base_url}")
    lines.append(f"Monitor account: {me.get('name', 'AI Monitor')} ({me.get('email', 'unknown email')})")
    lines.append("")
    lines.append("## Executive Snapshot")
    lines.append(fmt_metric("Audit events", total))
    if management:
        lines.append(fmt_metric("Active orders", management.get("active_orders")))
        lines.append(fmt_metric("Late orders", management.get("late_orders")))
        lines.append(fmt_metric("Today's defects", management.get("todays_defects")))
        lines.append(fmt_metric("Today's waste", management.get("todays_waste")))
        lines.append(fmt_metric("Branded stock value", management.get("branded_stock_value")))
    if production:
        lines.append(fmt_metric("Cutting output", production.get("cutting_output")))
        lines.append(fmt_metric("Printing output", production.get("printing_output")))
        lines.append(fmt_metric("Sewing output", production.get("sewing_output")))
        lines.append(fmt_metric("Packaging output", production.get("packaging_output")))
        lines.append(fmt_metric("Active work orders", production.get("active_work_orders")))
    if inventory:
        lines.append(fmt_metric("Finished goods total", inventory.get("finished_goods_total")))
    if finance:
        for key in ("cash_balance", "receivables", "payables", "revenue", "expenses"):
            if key in finance:
                lines.append(fmt_metric(key.replace("_", " ").title(), finance.get(key)))
    if isinstance(hash_check, dict) and "ok" in hash_check:
        lines.append(fmt_metric("Audit hash chain OK", hash_check.get("ok")))
        first_mismatch = hash_check.get("first_mismatch")
        if isinstance(first_mismatch, dict):
            mismatch_label = f"#{first_mismatch.get('id')} ({first_mismatch.get('reason')})"
            lines.append(fmt_metric("Audit hash first mismatch", mismatch_label))
    lines.append("")

    lines.append("## Activity By User")
    lines.extend(top_counter_lines(user_counts, "No user activity found"))
    lines.append("")
    lines.append("## Busiest Actions")
    lines.extend(top_counter_lines(action_counts, "No actions found"))
    lines.append("")
    lines.append("## Busiest Areas")
    lines.extend(top_counter_lines(entity_counts, "No areas found"))
    lines.append("")
    lines.append("## Latest Notable Work")
    if rows:
        for row in rows[:20]:
            created_at = parse_dt(row.get("created_at"), tz)
            prefix = f"{created_at:%H:%M}" if created_at else "--:--"
            summary = str(row.get("summary") or "Activity recorded.").strip()
            lines.append(f"- {prefix} - {summary}{changed_field_names(row)}")
    else:
        lines.append("- No audit entries were recorded in this window.")
    lines.append("")
    lines.append("## Suggested Improvements")
    for suggestion in build_suggestions(rows, dashboards):
        lines.append(f"- {suggestion}")

    unavailable = [name for name, payload in dashboards.items() if not payload.get("ok")]
    if unavailable:
        lines.append("")
        lines.append("## Data Gaps")
        for name in unavailable:
            lines.append(f"- {name}: {dashboards[name].get('error', 'unavailable')}")
    return "\n".join(lines).strip() + "\n"


def collect_report(args: argparse.Namespace) -> str:
    load_env_file(Path(args.env_file))
    tz = ZoneInfo(args.timezone or os.environ.get("ERP_MONITOR_TZ", DEFAULT_TIMEZONE))
    base_url = (args.base_url or os.environ.get("ERP_MONITOR_BASE_URL") or DEFAULT_BASE_URL).strip()
    email = os.environ.get("ERP_MONITOR_EMAIL", "").strip()
    password = os.environ.get("ERP_MONITOR_PASSWORD", "").strip()
    bearer = os.environ.get("ERP_MONITOR_BEARER_TOKEN", "").strip()
    if not bearer and (not email or not password):
        raise MonitorConfigError("Set ERP_MONITOR_EMAIL and ERP_MONITOR_PASSWORD, or ERP_MONITOR_BEARER_TOKEN")

    end_local = datetime.now(tz)
    start_local = end_local - timedelta(hours=args.hours)
    client = ERPClient(base_url=base_url, timeout_seconds=args.timeout)
    try:
        if not bearer:
            client.login(email, password)
        me = client.get("/api/auth/me")
        audit_response = client.get(
            "/api/audit-logs",
            params={
                "include_total": "true",
                "page": 1,
                "page_size": args.audit_limit,
                "date_from": start_local.isoformat(),
                "date_to": end_local.isoformat(),
            },
        )
        dashboards = {
            "management": safe_get(client, "/api/dashboard/management", {"tz": tz.key}),
            "active_production": safe_get(client, "/api/dashboard/active-production"),
            "production": safe_get(
                client,
                "/api/dashboard/production",
                {"start": start_local.isoformat(), "end": end_local.isoformat()},
            ),
            "inventory": safe_get(client, "/api/dashboard/inventory"),
            "finance": safe_get(client, "/api/dashboard/finance"),
            "waste": safe_get(client, "/api/dashboard/waste"),
            "hash_chain": safe_get(client, "/api/audit-logs/hash-chain/verify", {"limit": 1000}),
        }
        return render_report(
            base_url=base_url,
            tz=tz,
            start_local=start_local,
            end_local=end_local,
            me=me if isinstance(me, dict) else {},
            audit_response=audit_response if isinstance(audit_response, dict) else {"rows": audit_response},
            dashboards=dashboards,
        )
    finally:
        client.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a daily Milana ERP audit and dashboard report.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="Ignored local env file with ERP monitor credentials.")
    parser.add_argument("--base-url", default="", help=f"ERP base URL. Defaults to {DEFAULT_BASE_URL}.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for the report window.")
    parser.add_argument("--hours", type=int, default=24, help="Look-back window in hours.")
    parser.add_argument("--audit-limit", type=int, default=200, help="Maximum audit rows to include from the window.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument("--output", default="", help="Optional file path to write the Markdown report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = collect_report(args)
    except MonitorConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPStatusError as exc:
        print(f"ERP API error: HTTP {exc.response.status_code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
