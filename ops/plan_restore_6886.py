"""Restore the exact existing batch using the owner's confirmed older source row."""
import json
from pathlib import Path
from plan_current_fabric import OUT, num

prior=Path('C:/ERP/.codex-work/fabric-reconcile-20260930/outputs/fabric-reconciliation/source-workbooks.json')
book=next(b for b in json.loads(prior.read_text(encoding='utf-8')) if b['file']=='DINAR 2026 (5).xlsx')
sheet=next(s for s in book['sheets'] if s['sheet']=='Лист1')
v=next(r['values'] for r in sheet['rows'] if r['row']==553)
assert str(v[5])=='6886' and num(v[4])==num('559.3') and num(v[3])==num(25)
s=json.loads((OUT/'production-snapshot.json').read_text())
matches=[b for b in s['batches'] if b['supplier_id']==2 and b['batch_no']=='6886']
assert len(matches)==1 and matches[0]['id']==1639 and num(matches[0]['quantity'])==0 and matches[0]['archived_at']
assert any(i['id']==matches[0]['item_id'] and i['is_active'] for i in s['items'])
source=dict(file=book['file'],sheet=sheet['sheet'],row=553,supplier_id=2,batch_no='6886',remaining_kg='559.3000',remaining_rolls='25',
    basis='Owner explicitly restores older List1 row 553 balance, overriding newer TEST zero for this batch only')
plan=dict(version=3,workbooks=[{k:book[k] for k in ('file','sha256')}],
    actions=[dict(ref='C6886',kind='update',id=1639,restore_reason='Owner confirmed DINAR List1 row 553: restore physical stock 559.3 kg and 25 rolls',
        values=dict(quantity='559.3000',piece_count=25,archived_at=None,archived_by=None,qc_status='pending',roll_weights_kg=[],roll_lengths_m=[]),sources=[source])],
    outcomes=[dict(ref='C6886',sources=[source],target_kg='559.3000',target_rolls='25')],
    new_items=[],reservation_releases=[],exceptions=[],supplemental=[],auxiliary=[],source_records=[source],
    preserved_ids=[b['id'] for b in s['batches'] if b['id']!=1639],
    omitted_positive_ids=[b['id'] for b in s['batches'] if b['id']!=1639 and num(b['quantity'])>0])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('Restore existing DINAR 6886: 559.3 kg / 25 rolls; retain history and identity.')
