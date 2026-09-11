"""Execute guarded pack import phases using existing secure deployment transport."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'pack-222'
REMOTE='/tmp/pack-222-20260911'
spec=importlib.util.spec_from_file_location('transport',r'C:\ERP\.codex-work\performance-release-20260829\deploy_release.py')
h=importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
GUARD='''set -eu
test "$(readlink -f /opt/milana-erp/current)" = /opt/milana-erp/releases/20260910_130124
test "$(sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256 | cut -d' ' -f1)" = d0389087f2bd7e0153b2553e32b383f9d374ab84a5edeb8b355e4b24edd085dd
'''

phase=sys.argv[1]
c=h.connect('172.16.10.4')
try:
    if phase=='classify':
        h.upload(c,OUT/'extracted.json',REMOTE+'-candidates.json')
        h.upload(c,ROOT/'ops'/'classify_completed_pack_candidates.py',REMOTE+'-classifier.py')
        command=f'''mkdir -p {REMOTE}
docker cp {REMOTE}-candidates.json milana-backend-green:{REMOTE}-candidates.json
docker cp {REMOTE}-classifier.py milana-backend-green:{REMOTE}-classifier.py
docker exec -e PYTHONPATH=/app:/app/backend milana-backend-green python {REMOTE}-classifier.py {REMOTE}-candidates.json --expected-database-host 172.16.10.3 --expected-database-name erp
'''
    elif phase=='inspect':
        h.upload(c,OUT/'inspect_models.py',REMOTE+'-inspect.py')
        command=f'docker cp {REMOTE}-inspect.py milana-backend-green:{REMOTE}-inspect.py\ndocker exec -e PYTHONPATH=/app:/app/backend milana-backend-green python {REMOTE}-inspect.py'
    elif phase=='status':
        command='python3 /opt/milana-erp/shared/deploy/slotctl.py status'
    elif phase=='backup':
        h.upload(c,Path(r'C:\ERP\.codex-work\model-permission-deploy-20260820_110156\create_backup.py'),REMOTE+'-backup.py')
        command=f'python3 {REMOTE}-backup.py 20260911_050000'
    elif phase=='upload':
        import hashlib
        bundle=OUT/'bundle.zip'
        h.upload(c,bundle,REMOTE+'-bundle.zip')
        command=f'''test "$(sha256sum {REMOTE}-bundle.zip | cut -d' ' -f1)" = {hashlib.sha256(bundle.read_bytes()).hexdigest()}
python3 -m zipfile -e {REMOTE}-bundle.zip {REMOTE}
docker cp {REMOTE} milana-backend-green:/tmp/
'''
    elif phase in ('dry-run','apply','verify'):
        import hashlib
        manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
        sha=hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()
        command=f'docker exec -e PYTHONPATH=/app:/app/backend milana-backend-green python {REMOTE}/import_completed_packs.py {REMOTE}/manifest.json --photo-root {REMOTE}/photos --expected-manifest-sha256 {sha} --expected-database-host 172.16.10.3 --expected-database-name erp --environment production --mode {phase}'
        if phase=='apply': command+=f' --confirm APPLY-{len(manifest["rows"])}-COMPLETED-PACKS-TO-PRODUCTION'
    else: raise ValueError(phase)
    result=h.run(c,phase,GUARD+command,sudo=True,show_output=False,timeout=600)
    (OUT/(phase+'.json')).write_text(result,encoding='utf-8')
    data=json.loads(result) if result else {}
    print(json.dumps({k:v for k,v in data.items() if k!='rows' or not isinstance(v,list)},ensure_ascii=False))
finally: c.close()
