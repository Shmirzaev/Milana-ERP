"""Capture only the reviewed read-only snapshot from the active container."""
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'outputs/fabric-reconciliation'
out.mkdir(parents=True, exist_ok=True)
script = root / 'ops/fabric_reconciliation_snapshot.py'
result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',str(Path.home()/'.ssh/milana_erp_deploy_ed25519'),'admilana@172.16.10.4','docker exec -i milana-backend-green python -'], input=script.read_bytes(), capture_output=True, check=True)
data = json.loads(result.stdout)
(out/'production-snapshot.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:len(v) for k,v in data.items()}))
