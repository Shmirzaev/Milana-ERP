"""Apply the owner's explicit List1 balance override to existing DINAR 5132."""
import json
from pathlib import Path
from plan_current_fabric import OUT, num

prior=Path('C:/ERP/.codex-work/fabric-reconcile-20261002/outputs/fabric-reconciliation/source-workbooks.json')
book=next(b for b in json.loads(prior.read_text(encoding='utf-8')) if b['file']=='DINAR 2026 (5) (6).xlsx')
sheet=next(s for s in book['sheets'] if s['sheet']=='Лист1')
v=next(r['values'] for r in sheet['rows'] if r['row']==310)
assert str(v[5])=='5132' and num(v[13])==num('243.5') and num(v[12])==num(10)
snapshot=json.loads((OUT/'production-snapshot.json').read_text())
matches=[b for b in snapshot['batches'] if b['supplier_id']==2 and b['batch_no']=='5132']
assert len(matches)==1 and matches[0]['id']==817 and matches[0]['archived_at'] is None
source=dict(file=book['file'],sheet=sheet['sheet'],row=310,supplier_id=2,batch_no='5132',
    remaining_kg='243.5000',remaining_rolls='10',basis='Owner explicitly overrides TEST with List1 row 310 for this batch only')
plan=dict(version=3,workbooks=[{k:book[k] for k in ('file','sha256')}],
    actions=[dict(ref='C5132',kind='update',id=817,values=dict(quantity='243.5000',piece_count=10),sources=[source])],
    outcomes=[dict(ref='C5132',sources=[source],target_kg='243.5000',target_rolls='10')],
    new_items=[],reservation_releases=[],exceptions=[],supplemental=[],auxiliary=[],source_records=[source],
    preserved_ids=[b['id'] for b in snapshot['batches'] if b['id']!=817],
    omitted_positive_ids=[b['id'] for b in snapshot['batches'] if b['id']!=817 and num(b['quantity'])>0])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('DINAR 5132: existing batch 817 -> 243.5 kg, 10 rolls. All other fields preserved.')
