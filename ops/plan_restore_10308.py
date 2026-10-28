"""Restore the source-correct SAFF 10308 receipt to the owner's confirmed balance."""
import json
from plan_current_fabric import OUT, num

s=json.loads((OUT/'production-snapshot.json').read_text())
matches=[b for b in s['batches'] if b['supplier_id']==3 and b['batch_no']=='10308']
assert {b['id'] for b in matches}=={1527,1729}
batch=next(b for b in matches if b['id']==1729)
assert batch['item_id']==82 and num(batch['quantity'])==0 and batch['archived_at']
assert any(i['id']==82 and i['name']=='30/1 COMPACT SUPREM' and i['is_active'] for i in s['items'])
assert all(num(b['quantity'])==0 for b in matches)
source=dict(supplier_id=3,batch_no='10308',remaining_kg='300.0000',remaining_rolls='10',
    basis='Owner confirmed 300 kg and 10 rolls on 2026-10-05. Restore source-correct COMPACT SUPREM receipt; preserve older archived PENYE receipt.')
plan=dict(version=3,workbooks=[],
    actions=[dict(ref='C10308',kind='update',id=1729,restore_reason='Owner confirmed physical stock: restore SAFF 10308 COMPACT SUPREM with 300 kg and 10 rolls',
        values=dict(quantity='300.0000',piece_count=10,archived_at=None,archived_by=None,qc_status='pending',roll_weights_kg=[],roll_lengths_m=[]),sources=[source])],
    outcomes=[dict(ref='C10308',sources=[source],target_kg='300.0000',target_rolls='10')],
    new_items=[],reservation_releases=[],exceptions=[],supplemental=[],auxiliary=[],source_records=[source],
    preserved_ids=[b['id'] for b in s['batches'] if b['id']!=1729],
    omitted_positive_ids=[b['id'] for b in s['batches'] if b['id']!=1729 and num(b['quantity'])>0])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('Restore SAFF 10308, existing COMPACT SUPREM batch 1729: 300 kg / 10 rolls.')
