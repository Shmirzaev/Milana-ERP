"""Explicit SSH launcher. Private plans and evidence are ignored by Git."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/warehouse-cleanup"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i",
       str(Path.home()/".ssh/milana_erp_deploy_ed25519")]
RELEASE = "20261022_130603"
MANIFEST = "3bdc1454f873f51202738e2705d45ddb9855a492507340bb5a3f5f149484e33c"


def remote(source, command="docker exec -i milana-backend-green python -"):
    result = subprocess.run(SSH + ["admilana@172.16.10.4", command],
                            input=source.encode(), capture_output=True)
    if result.returncode:
        (OUT / "error.txt").write_bytes(result.stderr)
        raise RuntimeError("Remote operation failed; inspect outputs/warehouse-cleanup/error.txt")
    return json.loads(result.stdout)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    action = sys.argv[1]
    for host in ("172.16.10.4", "172.16.10.5"):
        result = subprocess.check_output(SSH + ["admilana@"+host,
            "readlink -f /opt/milana-erp/current; sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256"])
        lines = result.decode().splitlines()
        assert lines[0] == "/opt/milana-erp/releases/"+RELEASE and lines[1].split()[0] == MANIFEST
    operation = (ROOT/"ops/warehouse_cleanup_invertar.py").read_text(encoding="utf-8")
    source_hash = hashlib.sha256(operation.encode()).hexdigest()
    if action == "backup":
        code = (ROOT/"ops/backup_fabric_reconciliation.py").read_text()
        code = code.replace("milana-backend-blue", "milana-backend-green")
        code = code.replace("milana_erp_pre_fabric_reconcile_", "milana_erp_pre_warehouse_cleanup_invertar_")
        code = code.replace("20261005_070406", RELEASE)
        result = remote(code, "python3 -")
    else:
        expected = json.loads((OUT/"inspect.json").read_text())["fingerprint"] if action != "inspect" else None
        backup = json.loads((OUT/"backup.json").read_text()) if action != "inspect" else None
        if backup:
            code = '''import hashlib,json,pathlib,subprocess
expected=BACKUP
prefix=['docker','run','--rm','--user','0','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
path='/backup/'+pathlib.Path(expected['path']).name
listing=subprocess.check_output(prefix+['postgres:16-alpine','pg_restore','--list',path])
probe='import json,pathlib,hashlib;p=pathlib.Path('+repr(path)+');print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode & 0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))'
meta=json.loads(subprocess.check_output(prefix+['--entrypoint','python','ghcr.io/shmirzaev/milana-erp-backend:RELEASE','-c',probe]))
assert all(meta[key]==expected[key] for key in ('bytes','mode','sha256'))
assert hashlib.sha256(listing).hexdigest()==expected['restore_list_sha256']
print(json.dumps({'verified':True}))
'''.replace('BACKUP',repr(backup)).replace('RELEASE',RELEASE)
            assert remote(code, "python3 -")["verified"]
        if action == "apply":
            committed = subprocess.check_output(["git", "show", "HEAD:ops/warehouse_cleanup_invertar.py"], cwd=ROOT).decode()
            assert committed.replace("\r\n", "\n") == operation.replace("\r\n", "\n")
            rehearsal = json.loads((OUT/"rehearse.json").read_text())
            assert rehearsal["rollback_verified"] and rehearsal["fingerprint"] == expected
            assert rehearsal["operation_sha256"] == source_hash
        result = remote(operation + "\nprint(json.dumps(run(" + ",".join(map(repr,
                        [action, expected, backup])) + "),default=str))\n")
        result["operation_sha256"] = source_hash
    (OUT/(action+".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"plan", "fingerprints"}}))


if __name__ == "__main__":
    main()
