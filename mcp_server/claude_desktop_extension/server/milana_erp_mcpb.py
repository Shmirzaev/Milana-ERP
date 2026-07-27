from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path


ERP_PROJECT_MCP_SRC = Path(r"C:\ERP\mcp_server\src")
ERP_API_BASE_URL = "https://erp.milanapremium.uz"


def _candidate_config_paths() -> list[Path]:
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    if localappdata:
        paths.append(Path(localappdata) / "Claude-3p" / "claude_desktop_config.json")
        paths.append(
            Path(localappdata)
            / "Packages"
            / "Claude_pzs8sxrjxfjjc"
            / "LocalCache"
            / "Roaming"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return paths


def _load_existing_erp_token() -> str | None:
    for path in _candidate_config_paths():
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        server = (config.get("mcpServers") or {}).get("milana-erp") or {}
        env = server.get("env") or {}
        token = env.get("ERP_MCP_BEARER_TOKEN")
        if token and "REPLACE" not in token and "PASTE" not in token:
            return str(token)
    return None


def main() -> None:
    os.environ.setdefault("ERP_API_BASE_URL", ERP_API_BASE_URL)
    os.environ.setdefault("ERP_MCP_REQUIRE_CONFIRMATION", "true")
    if not os.environ.get("ERP_MCP_BEARER_TOKEN"):
        token = _load_existing_erp_token()
        if token:
            os.environ["ERP_MCP_BEARER_TOKEN"] = token

    if str(ERP_PROJECT_MCP_SRC) not in sys.path:
        sys.path.insert(0, str(ERP_PROJECT_MCP_SRC))

    runpy.run_module("milana_erp_mcp.server", run_name="__main__")


if __name__ == "__main__":
    main()
