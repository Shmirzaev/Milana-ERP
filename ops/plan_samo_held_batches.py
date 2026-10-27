"""Resolve exactly five held SAMO rows using the owner's confirmed fabric."""
import json
from decimal import Decimal
from pathlib import Path
from plan_current_fabric import OUT, build, key

prior = Path('C:/ERP/.codex-work/fabric-reconcile-20261002/outputs/fabric-reconciliation')
original = json.loads((prior/'current-plan.json').read_text(encoding='utf-8'))
evidence = json.loads((prior/'source-workbooks.json').read_text(encoding='utf-8'))
snapshot = json.loads((OUT/'production-snapshot.json').read_text())
batch_numbers = {'15785_1', '15798', '18336', '16939', '21089'}
fabric = '30/1 COMPACT PENYA SUPREM'
# The established SAMO alias maps PENYA to the existing PENYE catalog spelling.
items = [i for i in snapshot['items'] if i['is_active'] and i['id'] == 81
         and key(i['name']) == key('30/1 COMPACT PENYE SUPREM')]
assert len(items) == 1, 'Expected one existing active fabric identity'
rows = []
for exception in original['exceptions']:
    for source in exception['sources']:
        if source['supplier_id'] != 1 or source['batch_no'] not in batch_numbers:
            continue
        row = dict(source, fabric=fabric, item_id=items[0]['id'])
        row['identity_basis'] = 'Owner explicitly confirmed 30/1 COMPACT PENYA SUPREM for all five held SAMO batches'
        for field in ('received_kg', 'received_rolls', 'remaining_kg', 'remaining_rolls'):
            row[field] = Decimal(row[field])
        assert row['remaining_kg'] > 0 and not row['missing_quantity']
        rows.append(row)
assert {r['batch_no'] for r in rows} == batch_numbers and len(rows) == 5
evidence = [b for b in evidence if b['file'] == rows[0]['file']]
assert len(evidence) == 1
plan = build(evidence, snapshot, external_rows=rows)
assert not plan['exceptions'] and not plan['new_items'] and not plan['reservation_releases']
assert len(plan['actions']) == 5 and all(a['kind'] == 'receive' for a in plan['actions'])
(OUT/'current-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'fabric': fabric, 'item_id': items[0]['id'], 'batches': [dict(batch=r['batch_no'], kg=str(r['remaining_kg']), rolls=str(r['remaining_rolls'])) for r in rows], 'total_kg': str(sum(r['remaining_kg'] for r in rows))}))
