"""Explicit operator launcher. --prepare is local; --backup and --apply write."""
import argparse
import base64
import hashlib
import json
import posixpath
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/fabric-reconciliation'
SOURCE = Path('C:/Users/User/Downloads/Telegram Desktop')
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-i',
       str(Path.home()/'.ssh/milana_erp_deploy_ed25519'), 'admilana@172.16.10.4']


def remote(code, command):
    result = subprocess.run(SSH+[command], input=code.encode(), capture_output=True)
    if result.returncode:
        # Application traceback contains no connection string; save locally for diagnosis.
        (OUT/'operation-error.txt').write_bytes(result.stderr)
        raise RuntimeError('Remote operation failed; see local operation-error.txt')
    return json.loads(result.stdout)


def collect_images(plan):
    images = {}
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'd': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    def relations(z, owner):
        relpath = posixpath.dirname(owner)+'/_rels/'+posixpath.basename(owner)+'.rels'
        if relpath not in z.namelist():
            return {}
        return {r.attrib['Id']: (r.attrib['Target'].lstrip('/') if r.attrib['Target'].startswith('/')
                else posixpath.normpath(posixpath.join(posixpath.dirname(owner), r.attrib['Target'])))
                for r in ET.fromstring(z.read(relpath))}
    for book in plan['workbooks']:
        file = SOURCE/book['file']
        if hashlib.sha256(file.read_bytes()).hexdigest() != book['sha256']:
            raise ValueError('Source workbook changed')
        with zipfile.ZipFile(file) as z:
            rels = relations(z, 'xl/workbook.xml')
            sheets = {}
            for sheet in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet', ns):
                sheet_path = rels[sheet.attrib['{'+ns['r']+'}id']]
                sr = relations(z, sheet_path)
                rows = {}
                for drawing in ET.fromstring(z.read(sheet_path)).findall('m:drawing', ns):
                    dp = sr[drawing.attrib['{'+ns['r']+'}id']]
                    dr = relations(z, dp)
                    for anchor in ET.fromstring(z.read(dp)):
                        start = anchor.find('d:from/d:row', ns)
                        blip = anchor.find('.//a:blip', ns)
                        if start is None or blip is None:
                            continue
                        media = dr[blip.attrib['{'+ns['r']+'}embed']]
                        rows.setdefault(int(start.text)+1, []).append(z.read(media))
                sheets[sheet.attrib['name']] = rows
            for i, p in enumerate(plan['plans']):
                if p['status'] != 'prepared' or p['action'] != 'receive':
                    continue
                r = p['sources'][0]
                if r['file'] != book['file']:
                    continue
                anchor_row = {6:5,66:65,78:77,82:81}.get(r['row'],r['row']) if r['sheet']=='Лист5' else r['row']
                matched = sheets.get(r['sheet'], {}).get(anchor_row, [])
                if len(matched) == 1:
                    raw_image = matched[0]
                    images[str(i)] = {'sha256': hashlib.sha256(raw_image).hexdigest(),
                                     'base64': base64.b64encode(raw_image).decode(),
                                     'file': r['file'], 'sheet': r['sheet'], 'row': r['row']}
    return images


def prepare():
    plan = json.loads((OUT/'reconciliation-plan.json').read_text(encoding='utf-8'))
    raw = (OUT/'production-snapshot.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != plan['snapshot_sha256']:
        raise ValueError('Snapshot fingerprint changed')
    images = collect_images(plan)
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    payload = {'plan': plan, 'plan_sha256': plan_hash, 'snapshot': json.loads(raw), 'images': images}
    (OUT/'application-payload.json').write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')
    print(json.dumps({'prepared': 167, 'new_receipt_images': len(images), 'plan_sha256': plan_hash}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'backup', 'apply'])
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'backup':
        result = remote((ROOT/'ops/backup_fabric_reconciliation.py').read_text(), 'python3 -')
        (OUT/'backup-evidence.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    else:
        payload = json.loads((OUT/'application-payload.json').read_text())
        payload['backup'] = json.loads((OUT/'backup-evidence.json').read_text())
        code = 'import json,base64,types,sys\n'
        for name in ('fabric_reconciliation_snapshot', 'apply_fabric_reconciliation'):
            source = (ROOT/'ops'/f'{name}.py').read_text(encoding='utf-8')
            code += f'm=types.ModuleType({name!r}); sys.modules[{name!r}]=m; exec({source!r},m.__dict__)\n'
        code += 'from app.db.session import engine\n'
        code += 'from fabric_reconciliation_snapshot import capture\nfrom apply_fabric_reconciliation import apply\n'
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        code += f'payload=json.loads(base64.b64decode({encoded!r}))\n'
        code += 'print(json.dumps(apply(engine,capture,payload)))\n'
        result = remote(code, 'docker exec -i milana-backend-green python -')
        filename = 'application-replay.json' if result.get('already_applied') else 'application-result.json'
        (OUT/filename).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('changes', 'backup')}))


if __name__ == '__main__':
    main()
