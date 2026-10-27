"""Restore DINAR 4582 to the physical balance explicitly confirmed by the owner."""
import json
from plan_current_fabric import OUT, num

s=json.loads((OUT/'production-snapshot.json').read_text())
matches=[b for b in s['batches'] if b['supplier_id']==2 and b['batch_no']=='4582']
assert len(matches)==1 and matches[0]['id']==1461 and num(matches[0]['quantity'])==0 and matches[0]['archived_at']
assert any(i['id']==matches[0]['item_id'] and i['is_active'] for i in s['items'])
source=dict(supplier_id=2,batch_no='4582',remaining_kg='300.0000',remaining_rolls='10',
    basis='Owner explicitly confirmed 300 kg and 10 rolls on 2026-10-05, overriding source workbook zero balance for this batch only')
plan=dict(version=3,workbooks=[],
    actions=[dict(ref='C4582',kind='update',id=1461,restore_reason='Owner confirmed physical stock: restore DINAR 4582 with 300 kg and 10 rolls',
        values=dict(quantity='300.0000',piece_count=10,archived_at=None,archived_by=None,qc_status='pending',roll_weights_kg=[],roll_lengths_m=[]),sources=[source])],
    outcomes=[dict(ref='C4582',sources=[source],target_kg='300.0000',target_rolls='10')],
    new_items=[],reservation_releases=[],exceptions=[],supplemental=[],auxiliary=[],source_records=[source],
    preserved_ids=[b['id'] for b in s['batches'] if b['id']!=1461],
    omitted_positive_ids=[b['id'] for b in s['batches'] if b['id']!=1461 and num(b['quantity'])>0])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('Restore existing DINAR 4582: 300 kg / 10 rolls; preserve history and identity.')
