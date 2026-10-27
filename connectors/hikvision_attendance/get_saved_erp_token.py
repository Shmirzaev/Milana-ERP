"""Emit the current user's saved ERP connector token for setup_windows.ps1."""

from __future__ import annotations

import sys

try:
    import win32cred

    credential = win32cred.CredRead(
        "MilanaERP/attendance-integration-token",
        win32cred.CRED_TYPE_GENERIC,
    )
    secret = credential.get("CredentialBlob") or b""
    print(secret.decode("utf-16-le" if b"\x00" in secret else "utf-8"), end="")
except Exception:
    raise SystemExit(1)

