"""Freeze the reviewed 222.zip import and bind it to source PDF evidence."""
import hashlib
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'pack-222'
source=json.loads((OUT/'extracted.json').read_text(encoding='utf-8'))
classified=json.loads((OUT/'classify.json').read_text(encoding='utf-8'))
by_qr={r['qr_code']:r for r in classified['rows']}
assert len(source['rows'])==316 and not source['problems']
rows=[]
held=[]
for r in source['rows']:
    c=by_qr[r['qr_code']]
    assert not c['colliding_packages']
    if r['weight_kg'] is None and '--allow-blank-weight' not in sys.argv:
        held.append(r)
        continue
    reviewed_id=None
    if c['classification']!='new_importable':
        if c['identity']==['PJ1013','3846']:
            assert {m['id'] for m in c['catalog_matches']}=={83,7205}
            reviewed_id=83
        elif c['identity']==['PJ1171','5000']:
            assert {m['id'] for m in c['catalog_matches']}=={750,7826}
            reviewed_id=750
        else: raise ValueError(c)
    row=dict(qr_code=r['qr_code'],model_number=r['model_number'],article=r['article'],quantity=r['quantity'],weight_kg=r['weight_kg'],allowed_blank_weight=r['weight_kg'] is None,sizes=r['sizes'],target_kind='catalog',source_workbook='222.zip',source_workbook_sha256=source['source_zip_sha256'],source_reference=f"{r['source_file']}, page {r['source_page']}, label {r['source_sequence']}",source_photo=r['source_file'],source_photo_sha256=r['file_sha256'],review_status='approved',review_basis='User requested production warehouse import on 2026-09-11. Values extracted from supplied PDF and independently decoded QR; duplicate printouts counted once.')
    if reviewed_id:
        row['reviewed_catalog_model_id']=reviewed_id
        row['resolution_basis']='Original old_erp_migration.identity matches the printed variant; excludes hidden placeholder and duplicate with different original variant.'
    rows.append(row)
manifest=dict(version=2,expected_rows=len(rows),expected_quantity=sum(r['quantity'] for r in rows),expected_known_weight_kg=str(sum((Decimal(r['weight_kg']) for r in rows if r['weight_kg']),Decimal(0))),expected_null_weight_rows=sum(r['weight_kg'] is None for r in rows),expected_unique_identities=len({tuple(by_qr[r['qr_code']]['identity']) for r in rows}),rows=rows)
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'held.json').write_text(json.dumps(held,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(OUT/'bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
    z.write(OUT/'manifest.json','manifest.json')
    z.write(ROOT/'ops'/'import_completed_packs.py','import_completed_packs.py')
    for name in sorted({r['source_photo'] for r in rows}): z.write(OUT/'pdfs'/name,'photos/'+name)
print(json.dumps({k:v for k,v in manifest.items() if k!='rows'}))
print('manifest_sha256',hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest())
