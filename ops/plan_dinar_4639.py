"""Apply the owner's explicit 300 kg / 10 roll balance for DINAR 4639."""
import json
from plan_current_fabric import OUT, num

snapshot=json.loads((OUT/'production-snapshot.json').read_text())
matches=[b for b in snapshot['batches'] if b['supplier_id']==2 and b['batch_no']=='4639']
assert len(matches)==1 and matches[0]['id']==377
assert num(matches[0]['quantity'])==0 and matches[0]['archived_at'] is None
source=dict(supplier_id=2,batch_no='4639',remaining_kg='300.0000',remaining_rolls='10',
    basis='Owner explicitly confirmed add 300 kg and 10 rolls on 2026-10-05, overriding workbook zero balance for batch 4639 only')
plan=dict(version=3,workbooks=[],
    actions=[dict(ref='C4639',kind='update',id=377,values=dict(quantity='300.0000',piece_count=10),sources=[source])],
    outcomes=[dict(ref='C4639',sources=[source],target_kg='300.0000',target_rolls='10')],
    new_items=[],reservation_releases=[],exceptions=[],supplemental=[],auxiliary=[],source_records=[source],
    preserved_ids=[b['id'] for b in snapshot['batches'] if b['id']!=377],
    omitted_positive_ids=[b['id'] for b in snapshot['batches'] if b['id']!=377 and num(b['quantity'])>0])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('Existing DINAR 4639: 0 kg / 4 rolls -> 300 kg / 10 rolls. Other fields unchanged.')
