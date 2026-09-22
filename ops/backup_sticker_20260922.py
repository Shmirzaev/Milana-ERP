from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ENV_FILE = Path("/opt/milana-erp/shared/backend.env")
BACKUP_DIR = Path("/opt/milana-erp/shared/backups")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_url() -> str:
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "DATABASE_URL":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    raise RuntimeError("DATABASE_URL is missing")


if len(sys.argv) != 2 or not re.fullmatch(r"\d{8}_\d{6}", sys.argv[1]):
    raise SystemExit("usage: create_backup.py <release_id>")
release_id = sys.argv[1]
parsed = urlsplit(database_url())
if not parsed.hostname or not parsed.path.lstrip("/") or not parsed.username:
    raise RuntimeError("DATABASE_URL is incomplete")

backup = BACKUP_DIR / f"milana_erp_pre_{release_id}.dump"
pending = backup.with_suffix(".dump.tmp")
restore_list = BACKUP_DIR / f"milana_erp_pre_{release_id}.restore.list"


def emit_evidence(listed: str) -> None:
    object_count = sum(
        1 for line in listed.splitlines() if line.strip() and not line.startswith(";")
    )
    if object_count <= 100:
        raise RuntimeError(f"Backup restore list unexpectedly small: {object_count}")
    print(
        json.dumps(
            {
                "backup": str(backup),
                "backup_bytes": backup.stat().st_size,
                "backup_sha256": sha256(backup),
                "restore_list": str(restore_list),
                "restore_list_sha256": sha256(restore_list),
                "restore_objects": object_count,
            },
            sort_keys=True,
        )
    )


if backup.exists():
    if pending.exists() or not restore_list.exists():
        raise RuntimeError("Existing backup is incomplete")
    existing_list = subprocess.run(
        ["/usr/bin/pg_restore", "--list", str(backup)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if existing_list != restore_list.read_text(encoding="utf-8"):
        raise RuntimeError("Existing backup restore list does not match")
    emit_evidence(existing_list)
    raise SystemExit(0)

for path in (pending, restore_list):
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")

child_env = os.environ.copy()
child_env.update(
    {
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGDATABASE": unquote(parsed.path.lstrip("/")),
        "PGUSER": unquote(parsed.username),
        "PGPASSWORD": unquote(parsed.password or ""),
    }
)
subprocess.run(
    ["/usr/bin/pg_dump", "--no-password", "--format=custom", f"--file={pending}"],
    check=True,
    env=child_env,
)
if not pending.is_file() or pending.stat().st_size <= 0:
    raise RuntimeError("pg_dump did not create a non-empty backup")
pending.replace(backup)
backup.chmod(0o600)

listed = subprocess.run(
    ["/usr/bin/pg_restore", "--list", str(backup)],
    check=True,
    capture_output=True,
    text=True,
).stdout
restore_list.write_text(listed, encoding="utf-8")
restore_list.chmod(0o600)
emit_evidence(listed)
