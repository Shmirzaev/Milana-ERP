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
            rels = relations(z, 'xl/workbook.bin' if file.suffix=='.xlsb' else 'xl/workbook.xml')
            sheets = {}
            if file.suffix=='.xlsb':
                assert list(v for v in rels.values() if v.startswith('xl/worksheets/'))==['xl/worksheets/sheet1.bin']
                sheet_paths=[('Samo','xl/worksheets/sheet1.bin')]
            else:
                sheet_paths=[(s.attrib['name'],rels[s.attrib['{'+ns['r']+'}id']]) for s in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',ns)]
            for title,sheet_path in sheet_paths:
                sr = relations(z, sheet_path)
                rows = {}
                drawing_paths=[v for v in sr.values() if v.startswith('xl/drawings/') and v.endswith('.xml')]
                for dp in drawing_paths:
                    dr = relations(z, dp)
                    for anchor in ET.fromstring(z.read(dp)):
                        start = anchor.find('d:from/d:row', ns)
                        blip = anchor.find('.//a:blip', ns)
                        if start is None or blip is None:
                            continue
                        media = dr[blip.attrib['{'+ns['r']+'}embed']]
                        rows.setdefault(int(start.text)+1, []).append(z.read(media))
                sheets[title] = rows
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
