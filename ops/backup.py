"""Run on the backend host; database credentials never leave process memory."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, unquote

url = subprocess.check_output([
    "docker", "exec", "milana-backend-green", "python", "-c",
    "from app.core.config import settings; print(settings.DATABASE_URL)",
], text=True).strip()
parts = urlsplit(url)
assert parts.hostname == "172.16.10.3"
env = os.environ.copy()
env["PGPASSWORD"] = unquote(parts.password or "")
stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
path = Path(f"/opt/milana-erp/shared/backups/pre_delete_marked_purchases_{stamp}.dump")
assert not path.exists()
os.umask(0o077)
subprocess.run([
    "pg_dump", "-h", parts.hostname, "-p", str(parts.port or 5432),
    "-U", unquote(parts.username or ""), "-d", parts.path.lstrip("/"),
    "-Fc", "-f", str(path),
], env=env, check=True, capture_output=True)
listing = subprocess.check_output(["pg_restore", "--list", str(path)])
objects = sum(bool(line.strip()) and not line.startswith(b";") for line in listing.splitlines())
assert objects > 100 and path.stat().st_size > 1000000
assert path.stat().st_mode & 0o777 == 0o600
list_path = path.with_suffix(".list")
list_path.write_bytes(listing)
result = {"path":str(path),"bytes":path.stat().st_size,"mode":"0600","objects":objects,
          "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
          "list_sha256":hashlib.sha256(listing).hexdigest(),"list_bytes":len(listing)}
path.with_suffix(".json").write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
