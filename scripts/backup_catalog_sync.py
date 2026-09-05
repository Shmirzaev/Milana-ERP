"""Create and verify a PostgreSQL backup without logging connection secrets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse, unquote
from datetime import datetime, timezone

root = Path.home() / "catalog-sync-backups"
root.mkdir(mode=0o700, exist_ok=True)
raw = subprocess.check_output([
    "docker", "exec", "milana-backend-blue", "python", "-c",
    "from app.core.config import settings; print(settings.DATABASE_URL)",
], text=True).strip()
url = urlparse(raw.replace("postgresql+psycopg2://", "postgresql://"))
assert url.hostname == "172.16.10.3" and url.path == "/erp"
env = {**os.environ, "PGPASSWORD": unquote(url.password or "")}
path = root / ("pre_catalog_qolip_photos_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".dump")
with path.open("xb") as out:
    os.chmod(path, 0o600)
    subprocess.run(["pg_dump", "-h", url.hostname, "-p", str(url.port or 5432), "-U", unquote(url.username), "-d", "erp", "-Fc"], env=env, stdout=out, check=True)
listing = subprocess.check_output(["pg_restore", "--list", str(path)])
objects = sum(bool(line.strip()) and not line.startswith(b";") for line in listing.splitlines())
assert path.stat().st_size > 1_000_000 and objects > 100
listpath = path.with_suffix(".list")
listpath.write_bytes(listing)
os.chmod(listpath, 0o600)
print(json.dumps({"path":str(path), "bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"restore_objects":objects,"list_sha256":hashlib.sha256(listing).hexdigest()}))
