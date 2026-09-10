import base64
from pathlib import Path
import shlex
import subprocess
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
if "--apply" in sys.argv:
    source = "import sys\nsys.argv=['maintenance','--apply']\n" + source
prefix = "python3 -c " if "--host" in sys.argv else "docker exec -i milana-backend-green python -c "
command = prefix + shlex.quote(source)
result = subprocess.run([
    sys.executable, "C:/ERP/.codex-work/secure_credential_remote.py",
    "172.16.10.4", "--sudo", "--command-base64",
    base64.b64encode(command.encode()).decode(),
], capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
    Path(sys.argv[2]).write_bytes(result.stdout)
raise SystemExit(result.returncode)
