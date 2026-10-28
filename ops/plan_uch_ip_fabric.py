"""Match the seven unnumbered UCH IP rows to existing dated/color receipts."""
import json
from plan_current_fabric import OUT, build, num, date, key

evidence=json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8'))
snapshot=json.loads((OUT/'production-snapshot.json').read_text())
assert len(evidence)==1 and len(evidence[0]['sheets'])==1
book=evidence[0];sheet=book['sheets'][0]
aliases={'GOLUBOY':'GALUBOY','OKIAN':'OKEAN'}
rows=[];matched=[]
assert any(i['id']==93 and i['name']=='UCH IP' and i['is_active'] for i in snapshot['items'])
for row in sheet['rows']:
    v=row['values']
    if not isinstance(v[3],(int,float)) or not v[6]:continue
    color=str(v[6]).strip();received=date(v[2])
    assert received=='2026-08-19' and v[1] is None and v[5] is None and v[7] is None
    candidates=[b for b in snapshot['batches'] if b['item_id']==93
                and key(b['color'])==key(aliases.get(color,color))
                and b['received_date'][:10]==received and b['archived_at'] is None]
    assert len(candidates)==1,(color,'Ambiguous existing receipt')
    b=candidates[0]
    assert b['supplier_id']==17 and b['warehouse_id']==1
    ledger=[m for m in snapshot['movements'] if m['batch_id']==b['id']]
    receipts=sum(num(m['quantity']) for m in ledger if m['movement_type']=='receive')
    assert receipts==num(v[4]) or (color=='IZUMRUT' and receipts==num(8337)
        and any(m['movement_type']=='issue' and num(m['quantity'])==num(7503.3) for m in ledger))
    assert len(b['roll_weights_kg'])==int(v[3])
    kg=num(v[11]);rolls=num(v[10])
    assert kg==num(v[4])-num(v[9]) and rolls==num(v[3])-num(v[8]) and kg>=0
    rows.append(dict(file=book['file'],sheet=sheet['sheet'],row=row['row'],supplier_id=b['supplier_id'],
        item_id=93,fabric='UCH IP',batch_no=b['batch_no'],date=received,
        received_kg=num(v[4]),received_rolls=num(v[3]),remaining_kg=kg,remaining_rolls=rolls,
        color=color,color_code='',missing_quantity=False,
        basis='Displayed remaining kg/rolls; matched existing receipt by fabric, date, color and original receipt quantity',
        source_batch_no=None,source_supplier=None,matched_batch_id=b['id']))
    matched.append(b['id'])
assert len(rows)==7 and len(set(matched))==7
assert sum(r['remaining_kg'] for r in rows)==num(4864.7)
plan=build(evidence,snapshot,external_rows=rows)
assert not plan['exceptions'] and not plan['new_items'] and not plan['reservation_releases']
assert len(plan['actions'])==6 and all(a['kind']=='update' and a['id'] in matched for a in plan['actions'])
plan['notes']=['Row 9 is a receipt subtotal, not another stock row. The final 12619.4 kg formula includes it and is excluded.',
    'Source batch/supplier cells are blank. Preserve existing A1-A7 batch numbers and QIRGIZISTON supplier on the seven uniquely matched receipts.',
    'Excel has no individual roll weights or lengths. Existing receipt arrays and photos remain unchanged; remaining piece counts follow Excel.']
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
old={b['id']:b for b in snapshot['batches']}
print(json.dumps({'matched_rows':len(rows),'updates':[dict(batch=old[a['id']]['batch_no'],color=a['sources'][0]['color'],before_kg=old[a['id']]['quantity'],after_kg=a['values'].get('quantity'),before_rolls=old[a['id']]['piece_count'],after_rolls=a['values'].get('piece_count',old[a['id']]['piece_count'])) for a in plan['actions']],
    'before_kg':str(sum(num(old[i]['quantity']) for i in matched)), 'after_kg':str(sum(r['remaining_kg'] for r in rows)), 'rolls':str(sum(r['remaining_rolls'] for r in rows))}))
