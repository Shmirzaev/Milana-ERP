"""Reconcile Xitoy stock ledgers and roll packing lists without guessing identities."""
import argparse
from collections import Counter
import json
import re
from plan_current_fabric import OUT, build, num, date, key


def source_rows(evidence,snapshot,negative_zero):
    records=[];notes=[]
    items={i['id']:i['name'] for i in snapshot['items']}
    for bi,si,sid,iid in [(2,0,10,91),(2,1,10,91),(2,2,12,80),(3,0,21,4)]:
        book=evidence[bi];sheet=book['sheets'][si]
        for row in sheet['rows']:
            v=row['values']
            if row['row']<=(3 if bi==3 else 1) or not v[6]:continue
            used_roll,used_kg,left_roll,left_kg=(10,11,12,13) if bi==3 else (9,10,11,12) if si==2 else (11,12,13,14)
            kg=num(v[left_kg]) if v[left_kg] is not None else num(v[5])-num(v[used_kg])
            rolls=num(v[left_roll]) if v[left_roll] is not None else num(v[4])-num(v[used_roll])
            # Keep existing VISCON receipts on their original catalog identity;
            # only active VISCON 91 may receive newly missing stock.
            row_iid=iid
            if sid==10:
                live={b['item_id'] for b in snapshot['batches'] if b['supplier_id']==sid
                      and key(b['batch_no'])==key(v[6]) and num(b['quantity'])>0 and b['archived_at'] is None}
                if live=={79}:row_iid=79
            r=dict(file=book['file'],sheet=sheet['sheet'],row=row['row'],supplier_id=sid,item_id=row_iid,
                fabric=items[iid],source_fabric=v[8 if bi==3 or si!=2 else 7],batch_no=str(v[6]).strip(),
                date=date(v[2 if bi==3 else 3]),received_kg=num(v[5]),received_rolls=num(v[4]),
                remaining_kg=kg,remaining_rolls=rolls,color=str(v[7] or '').strip() if bi==3 else '',
                color_code=str(v[7] or '').strip() if bi==2 and si<2 else '',missing_quantity=False,
                basis='Displayed remaining kg; source-authoritative')
            if kg<0 and negative_zero:
                r.update(source_negative_kg=str(kg),remaining_kg=num(0),remaining_rolls=num(0),basis='User confirmed negative balance means depleted stock')
                notes.append(dict(file=r['file'],sheet=r['sheet'],row=r['row'],batch=r['batch_no'],reason=f'Negative {kg} kg treated as depleted by user decision'))
            records.append(r)
    book=evidence[1];pack=[]
    for sheet in book['sheets']:
        group=None
        for row in sheet['rows']:
            v=row['values']
            if isinstance(v[0],str) and re.fullmatch(r'[ABCD][#-]\d+',v[0]) and isinstance(v[2],(int,float)):
                prefix=v[0][0];batch=v[0].replace('A-','A#').replace('D#','D')
                iid={'A':119,'B':118,'C':120,'D':117}[prefix]
                group=dict(file=book['file'],sheet=sheet['sheet'],row=row['row'],supplier_id=30,item_id=iid,
                    fabric=items[iid],batch_no=batch,source_batch_no=v[0],date=None,received_kg=num(0),received_rolls=num(0),
                    used_kg=num(v[6]),color='',color_code='',missing_quantity=False,roll_weights_kg=[],roll_lengths_m=[],
                    stated_total_kg=v[8],basis='Sum of individual roll net kg minus recorded cutting kg; roll count remains receipt count')
                pack.append(group)
            if group is not None and isinstance(v[2],(int,float)) and isinstance(v[3],(int,float)):
                group['received_kg']+=num(v[3]);group['received_rolls']+=1
                group['roll_weights_kg'].append(float(v[3]));group['roll_lengths_m'].append(float(v[4]) if v[4] is not None else None)
        for g in [p for p in pack if p['sheet']==sheet['sheet']]:
            g['remaining_kg']=g['received_kg']-g['used_kg'];g['remaining_rolls']=g['received_rolls']
            if all(v is None for v in g['roll_lengths_m']):g['roll_lengths_m']=[]
            assert all(v is not None and v>0 for v in g['roll_lengths_m'])
            if g['stated_total_kg'] is not None and num(g['stated_total_kg'])!=g['received_kg']:
                notes.append(dict(file=g['file'],sheet=g['sheet'],row=g['row'],batch=g['batch_no'],reason=f"Receipt subtotal {g['stated_total_kg']} differs from roll sum {g['received_kg']}; used individual roll weights"))
            if g['remaining_kg']<0 and negative_zero:
                g['source_negative_kg']=str(g['remaining_kg']);g['remaining_kg']=num(0);g['remaining_rolls']=num(0)
                notes.append(dict(file=g['file'],sheet=g['sheet'],row=g['row'],batch=g['batch_no'],reason='Negative calculated balance treated as depleted by user decision'))
    records+=pack
    return records,notes


def main(negative_zero):
    evidence=json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8'))
    snapshot=json.loads((OUT/'production-snapshot.json').read_text())
    rows,notes=source_rows(evidence,snapshot,negative_zero)
    # Count can stay at its original receipt count when lengths are individually
    # recorded. A zero physical balance archives the batch without reindexing rolls.
    plan=build(evidence,snapshot,external_rows=rows)
    plan['reactivate_items']=[80]
    active_items={i['id'] for i in snapshot['items'] if i['is_active']}|set(plan['reactivate_items'])
    assert all(a['item_ref'] in active_items for a in plan['actions'] if a['kind']=='receive')
    replacements=[]
    for r in rows:
        if 'roll_weights_kg' not in r or r['remaining_kg']<=0 or r['used_kg']!=0:continue
        matches=[b for b in snapshot['batches'] if b['supplier_id']==30 and b['batch_no']==r['batch_no'] and num(b['quantity'])>0]
        assert len(matches)==1
        b=matches[0]
        if b['roll_weights_kg']==r['roll_weights_kg'] and b['roll_lengths_m']==r['roll_lengths_m']:continue
        assert not any(m['batch_id']==b['id'] and m['movement_type']!='receive' for m in snapshot['movements'])
        assert not any(x['stock_batch_id']==b['id'] for x in snapshot['reservations'])
        assert not any(x['batch_id']==b['id'] for x in snapshot['fabric_scans'])
        assert not any(x.get(k.split(':')[1])==b['id'] for k,v in snapshot['linked_rows'].items() for x in v)
        o=next(o for o in plan['outcomes'] if o['sources'][0]['supplier_id']==30 and o['sources'][0]['batch_no']==r['batch_no'])
        plan['actions']=[a for a in plan['actions'] if not (a['kind']=='update' and a['id']==b['id'])]
        source=json.loads(json.dumps(r,default=str))
        plan['actions']+=[dict(ref=o['ref'],kind='update',id=b['id'],values={'quantity':'0'},sources=[source],reason='Replace unused receipt with corrected source roll weights/lengths; retain old arrays and identity'),
            dict(ref=o['ref'],kind='receive',item_ref=r['item_id'],quantity=str(r['remaining_kg']),piece_count=int(r['received_rolls']),
                supplier_id=30,batch_no=r['batch_no'],color=b['color'],color_code=b['color_code'],received_date=b['received_date'][:10],
                cost_per_unit=b['cost_per_unit'],sources=[source],roll_weights_kg=r['roll_weights_kg'],roll_lengths_m=r['roll_lengths_m'])]
        replacements.append(dict(batch=r['batch_no'],old_id=b['id'],weights_changed=b['roll_weights_kg']!=r['roll_weights_kg'],lengths_changed=b['roll_lengths_m']!=r['roll_lengths_m']))
    changed={a['id'] for a in plan['actions'] if a['kind']=='update'}
    plan['preserved_ids']=[b['id'] for b in snapshot['batches'] if b['id'] not in changed]
    plan['roll_detail_replacements']=replacements
    plan['notes']=notes
    plan['empty_workbooks']=[evidence[0]['file']]
    plan['negative_zero']=negative_zero
    (OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    current={b['id']:b for b in snapshot['batches']}
    print(json.dumps(dict(actions=dict(Counter(a['kind'] for a in plan['actions'])),groups=len(plan['outcomes']),new_items=plan['new_items'],
        archives=sum(a['kind']=='update' and a['values'].get('quantity')=='0' for a in plan['actions']),exceptions=plan['exceptions'],notes=notes,
        array_differences=[dict(batch=r['batch_no'],id=b['id'],weights=b['roll_weights_kg']!=r['roll_weights_kg'],lengths=b['roll_lengths_m']!=r['roll_lengths_m']) for r in rows if 'roll_weights_kg' in r for b in snapshot['batches'] if b['supplier_id']==30 and b['batch_no']==r['batch_no'] and (b['roll_weights_kg']!=r['roll_weights_kg'] or b['roll_lengths_m']!=r['roll_lengths_m'])],
        delta_kg=str(sum(num(a['quantity']) if a['kind']=='receive' else num(a['values'].get('quantity',current[a['id']]['quantity']))-num(current[a['id']]['quantity']) for a in plan['actions'])))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--negative-zero',action='store_true')
    main(parser.parse_args().negative_zero)
