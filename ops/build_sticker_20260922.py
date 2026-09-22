"""Freeze this reviewed PDF batch; hold incomplete or unmatched identities."""
import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'sticker-20260922'
source = json.loads((OUT / 'extracted.json').read_text(encoding='utf-8'))
classified = json.loads((OUT / 'classify.json').read_text(encoding='utf-8'))
by_qr = {row['qr_code']: row for row in classified['rows']}
assert len(source['rows']) == 994 and not source['problems']
reviewed = {('PJ1000','3415'):78, ('PJ1000','4771'):511,
            ('PJ1118','2922'):3669, ('BJ5007','2235'):1597}
rows, held = [], []
for raw in source['rows']:
    classification = by_qr[raw['qr_code']]
    assert not classification['colliding_packages']
    identity = tuple(classification['identity'])
    reason = None
    if classification['classification'] == 'catalog_identity_missing':
        reason = 'Missing catalog model/variant; no model creation authorized'
    elif raw['weight_kg'] is None:
        reason = 'Weight absent from sticker; awaiting blank-weight instruction'
    if reason:
        held.append(dict(raw, reason=reason))
        continue
    assert classification['classification'] == 'new_importable' or identity in reviewed
    row = dict(qr_code=raw['qr_code'], model_number=raw['model_number'],
               article=raw['article'], quantity=raw['quantity'],
               weight_kg=raw['weight_kg'], allowed_blank_weight=False,
               sizes=raw['sizes'], color=raw.get('color',''),
               product=raw.get('product',''), fabric=raw.get('fabric',''),
               client=raw.get('client',''), target_kind='catalog',
               source_workbook='sticker.zip', source_workbook_sha256=source['source_zip_sha256'],
               source_reference=f"{raw['source_file']}, page {raw['source_page']}, label {raw['source_sequence']}",
               source_photo=raw['source_file'], source_photo_sha256=raw['file_sha256'],
               review_status='approved',
               review_basis='User requested warehouse import on 2026-09-22. PDF text and decoded QR agree; repeated identical labels counted once.')
    if identity in reviewed:
        row['reviewed_catalog_model_id'] = reviewed[identity]
        row['resolution_basis'] = 'Original old_erp_migration.identity matches printed variant; hidden placeholders and records with different original variants excluded.'
    rows.append(row)
manifest = dict(version=2, expected_rows=len(rows),
                expected_quantity=sum(r['quantity'] for r in rows),
                expected_known_weight_kg=str(sum((Decimal(r['weight_kg']) for r in rows),Decimal(0))),
                expected_null_weight_rows=0,
                expected_unique_identities=len({tuple(by_qr[r['qr_code']]['identity']) for r in rows}),rows=rows)
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'held.json').write_text(json.dumps(held,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with zipfile.ZipFile(OUT/'bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
    archive.write(OUT/'manifest.json','manifest.json')
    archive.write(ROOT/'ops'/'import_completed_packs.py','import_completed_packs.py')
    for name in sorted({r['source_photo'] for r in rows}):
        archive.write(OUT/'pdfs'/name,'photos/'+name)
print(json.dumps({k:v for k,v in manifest.items() if k!='rows'}))
print('held',len(held),'manifest_sha256',hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest())
