"""Prepare current physical balances using approved source and preservation rules."""
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/fabric-reconciliation'


def num(v):
    return Decimal(str(v or 0).replace(' ','').replace('\u00a0','').replace(',','.')).quantize(Decimal('.0001'))


def key(v):
    return ''.join(str(v or '').upper().split())


def date(v):
    if isinstance(v,(int,float)):
        return (datetime(1899,12,30)+timedelta(days=v)).date().isoformat()
    for fmt in ('%Y-%m-%d %H:%M:%S','%d,%m,%Y','%d.%m.%Y'):
        try:
            d=datetime.strptime(str(v),fmt)
            return d.date().isoformat() if 2000<=d.year<=2026 else None
        except ValueError:
            pass
    return None


def read(evidence,dinar_sheet):
    records=[]
    for bi, title, sid, cols in [(0,dinar_sheet,2,(3,4,5,9,2,10,11,12,13,6,7)),
           (1,'Samo',1,(3,4,5,8,2,10,11,12,13,6,None)),
           (2,' DANA RUSLAN SAFF',19,(4,5,6,8,3,10,11,12,13,7,None)),
           (2,' ZUXRA OPA  SAFF',3,(4,5,6,8,3,10,11,12,13,7,None))]:
        b=evidence[bi];s=next(s for s in b['sheets'] if s['sheet']==title)
        rr,rk,bn,fa,dt,ur,uk,lr,lk,cc,co=cols
        for row in s['rows']:
            v=row['values']
            if not any(v[i] is not None for i in (rr,rk,bn,ur,uk)):
                continue
            try:
                vals=[num(v[i]) for i in (rr,rk,ur,uk)]
                kg=num(v[lk]) if v[lk] is not None else num(v[rk])-num(v[uk])
                rolls=num(v[lr]) if v[lr] is not None else num(v[rr])-num(v[ur])
            except Exception:
                continue
            if not any(vals) and not v[bn]:
                continue
            r=dict(file=b['file'],sheet=title,row=row['row'],supplier_id=sid,
                batch_no=str(v[bn]).strip() if v[bn] is not None else '',fabric=str(v[fa] or '').strip(),
                date=date(v[dt]),received_rolls=vals[0],received_kg=vals[1],remaining_kg=kg,
                remaining_rolls=rolls,color_code=str(v[cc] or '').strip(),
                color=str(v[co] or '').strip() if co is not None else '',
                basis='Displayed remaining kg' if v[lk] is not None else 'Received minus recorded usage',
                missing_quantity=v[lk] is None and v[rk] is None)
            if sid==19 and r['fabric'].upper() in ('BEYAZ KASAR','BEYAS KASAR','KIRMIZI') and v[7]:
                r.update(fabric=str(v[7]).strip(),color=r['fabric'],color_code='')
            records.append(r)
    return records


def build(evidence,snapshot,dinar_sheet=None,external_rows=None):
    rows=read(evidence,dinar_sheet) if external_rows is None else external_rows
    names={key(i['name']):i['id'] for i in snapshot['items'] if i['is_active']}
    aliases={87:['30/1 P_CMP SUPREM','30/1 P-CMP SUPREM'],12:['36/1 P_CMP 20 DEN 8% LYC SUPREM','36/1P_CMP 20 DEN 8% LYC SUPREM','36/1 P_CMP 20 DEN LYC 8% SUPREM','36/1 P_CMP 20 DEN 8% LUC SUPREM'],81:['30/1 COMPACT PENYA SUPREM'],82:['30/1 COMPACT SUPREM'],7:['36/1 PENYA COMPACT 5*2 INTERLOK'],14:['36/1 PENYA COMPACT 12*12 INTERLOK','12*12 inerlok'],122:['30/1 PENYA SUPREM'],112:['75/36 COMPACT/SIYAH POL W FACE INTERLOK'],115:['36/1 VOSKON 20 DEN 8% LYC SUPREM']}
    for iid,variants in aliases.items():
        for name in variants:names[key(name)]=iid
    names[key('уч ип')]=93
    grouped=defaultdict(list);erp=defaultdict(list)
    for r in rows:grouped[(r['supplier_id'],key(r['batch_no']))].append(r)
    for b in snapshot['batches']:erp[(b['supplier_id'],key(b['batch_no']))].append(b)
    actions=[];outcomes=[];exceptions=[];new_items={};releases={}
    reservations=defaultdict(list)
    for r in snapshot['reservations']:
        if r['status'] in ('reserved','partially_consumed') and num(r['reserved_quantity'])>num(r['consumed_quantity'])+num(r['released_quantity']):
            reservations[r['stock_batch_id']].append(r)

    def update(ref,b,values,sources):
        values={k:v for k,v in values.items() if (num(b[k])!=num(v) if k=='quantity' else b[k]!=v)}
        if not values:return
        assert b['warehouse_id']==1 and b['unit']=='kg'
        outstanding=sum(num(r['reserved_quantity'])-num(r['consumed_quantity'])-num(r['released_quantity']) for r in reservations[b['id']])
        if 'quantity' in values and num(values['quantity'])<outstanding:
            if num(values['quantity'])!=0:raise ValueError(f"Nonzero target below reservation: {b['batch_no']}")
            for r in reservations[b['id']]:
                releases[r['id']]=dict(id=r['id'],batch_id=b['id'],ref=ref,before=r,
                    remaining_kg=str(num(r['reserved_quantity'])-num(r['consumed_quantity'])-num(r['released_quantity'])),
                    reason='Source confirms zero physical stock; release unused reservation only.')
        if 'piece_count' in values and b['roll_lengths_m']:raise ValueError('Recorded roll lengths prevent count change')
        if any(r['batch_id']==b['id'] and r['returned_at'] is None for r in snapshot['linked_rows'].get('eco_fabric_rolls:batch_id',[])):
            raise ValueError('Outstanding Eco fabric prevents stock mutation')
        actions.append(dict(ref=ref,kind='update',id=b['id'],values=values,sources=sources))

    for idx,(g,source) in enumerate(grouped.items(),1):
        ref=f'C{idx:04}';existing=erp[g];active=[b for b in existing if num(b['quantity'])>0]
        target=sum(r['remaining_kg'] for r in source)
        if target<0 or any(r['missing_quantity'] or r['remaining_kg']<0 for r in source):
            exceptions.append(dict(ref=ref,reason='Missing or negative stock kg',sources=source));continue
        if not g[1] and target>0:
            exceptions.append(dict(ref=ref,reason='Missing batch number needs exact receipt identification',sources=source));continue
        positive=[r for r in source if r['remaining_kg']>0]
        resolved=[]
        for r in positive:
            iid=r.get('item_id') or names.get(key(r['fabric']))
            if not r['fabric'] or key(r['fabric']) in (',,,','BEYAZKASAR'):
                identities={b['item_id'] for b in active or existing}
                iid=next(iter(identities)) if len(identities)==1 else None
                if iid is None:
                    exceptions.append(dict(ref=ref,reason='Missing material identity',sources=[r]));break
            elif iid is None:
                sku='FAB-SOURCE-'+hashlib.sha256(r['fabric'].encode()).hexdigest()[:16].upper()
                new_items[sku]=dict(sku=sku,name=r['fabric'],category='fabric',unit='kg',track_batch=True)
                iid=sku
            resolved.append((r,iid))
        else:
            segments=defaultdict(list)
            for r,iid in resolved:segments[(iid,key(r['color']),key(r['color_code']))].append(r)
            used=set();planned=[]
            for (iid,color,code),src in segments.items():
                qty=sum(r['remaining_kg'] for r in src);rolls=sum(r['remaining_rolls'] for r in src)
                count=int(rolls) if rolls>=0 and rolls==int(rolls) else None
                if count is None:exceptions.append(dict(ref=ref,reason='Invalid roll count left blank',sources=src))
                candidates=[b for b in active if b['id'] not in used and b['item_id']==iid and b['archived_at'] is None]
                candidates.sort(key=lambda b:(key(b['color'])==color and key(b['color_code'])==code,num(b['quantity'])==qty,b['id']),reverse=True)
                chosen=candidates[0] if candidates else None
                if chosen:
                    used.add(chosen['id']);values=dict(quantity=str(qty),piece_count=count)
                    if src[0]['color']:values['color']=src[0]['color']
                    if src[0]['color_code']:values['color_code']=src[0]['color_code']
                    planned.append((chosen,values,src))
                else:
                    r=src[0]
                    actions.append(dict(ref=ref,kind='receive',item_ref=iid,quantity=str(qty),piece_count=count,
                        supplier_id=g[0],batch_no=r['batch_no'],color=r['color'] or None,color_code=r['color_code'] or None,
                        received_date=r['date'],cost_per_unit=active[0]['cost_per_unit'] if len(active)==1 else '0',sources=src))
            for b in active:
                if b['id'] not in used:update(ref,b,dict(quantity='0',piece_count=0),source)
            for b,values,src in planned:update(ref,b,values,src)
            outcomes.append(dict(ref=ref,target_kg=str(target),sources=source,target_rolls=str(sum(r['remaining_rolls'] for r in positive))))
            continue
        # An unresolved subgroup leaves the whole supplier/batch group unchanged.
    if external_rows is not None:
        changed={a['id'] for a in actions if a['kind']=='update'}
        assert len(changed)==sum(a['kind']=='update' for a in actions)
        needed={a['item_ref'] for a in actions if a['kind']=='receive'}
        return json.loads(json.dumps(dict(version=3,workbooks=[{k:b[k] for k in ('file','sha256')} for b in evidence],
            actions=actions,outcomes=outcomes,new_items=[v for k,v in new_items.items() if k in needed],
            reservation_releases=list(releases.values()),exceptions=exceptions,supplemental=[],auxiliary=[],source_records=rows,
            preserved_ids=[b['id'] for b in snapshot['batches'] if b['id'] not in changed],
            omitted_positive_ids=[b['id'] for b in snapshot['batches'] if num(b['quantity'])>0 and (b['supplier_id'],key(b['batch_no'])) not in grouped]),default=str))
    # Preserve existing supplemental BAMBUK using the previously verified source row mapping.
    prior=Path('C:/ERP/.codex-work/fabric-reconcile-20260930/outputs/fabric-reconciliation')
    old_plan=json.loads((prior/'continuation-plan.json').read_text(encoding='utf-8'))
    old_result=json.loads((prior/'continuation-result.json').read_text())
    old_actions={c['ref']:(c,old_plan['actions'][c['index']]) for c in old_result['changes'] if c['ref'].startswith('S')}
    supplemental=[];current={b['id']:b for b in snapshot['batches']}
    for row in next(s for s in evidence[0]['sheets'] if s['sheet']=='Лист5')['rows'][1:]:
        v=row['values'];matches=[(c,a) for c,a in old_actions.values() if a['sources'][0]['row']==row['row']]
        assert len(matches)==1 and key(v[5])==key('БАМБУК')
        c,a=matches[0];b=current[c['id']]
        assert b['item_id']==4 and b['supplier_id'] is None and b['batch_no']==''
        qty=num(v[11]) if v[11] is not None else num(v[2])-num(v[9])
        rolls=num(v[10]) if v[10] is not None else num(v[1])-num(v[8])
        update(c['ref'],b,dict(quantity=str(qty),piece_count=int(rolls)),[dict(file=evidence[0]['file'],sheet='Лист5',row=row['row'])])
        supplemental.append(dict(ref=c['ref'],id=b['id'],kg=str(qty),rolls=int(rolls)))
    changed={a['id'] for a in actions if a['kind']=='update'}
    assert len(changed)==sum(a['kind']=='update' for a in actions)
    needed={a['item_ref'] for a in actions if a['kind']=='receive'}
    auxiliary=[]
    for row in evidence[2]['sheets'][1]['rows'][1:-1]:
        v=row['values'];sid=1 if key(v[1]) in ('САМО','CAMO','SAMO') else 3
        matched=[r for r in rows if r['supplier_id']==sid and key(r['batch_no'])==key(v[5]) and r['received_kg']==num(v[4]) and r['received_rolls']==num(v[3])]
        auxiliary.append(dict(file=evidence[2]['file'],sheet='Лист1',row=row['row'],batch_no=str(v[5]),
            status='Duplicate main-sheet receipt; not added' if matched else 'Not posted: material and remaining kg missing',
            received_kg=str(num(v[4])),received_rolls=str(num(v[3])),matched_rows=[r['row'] for r in matched]))
    plan=dict(version=3,dinar_sheet=dinar_sheet,workbooks=[{k:b[k] for k in ('file','sha256')} for b in evidence],
        actions=actions,outcomes=outcomes,new_items=[v for k,v in new_items.items() if k in needed],
        reservation_releases=list(releases.values()),exceptions=exceptions,supplemental=supplemental,auxiliary=auxiliary,
        preserved_ids=[b['id'] for b in snapshot['batches'] if b['id'] not in changed],
        omitted_positive_ids=[b['id'] for b in snapshot['batches'] if num(b['quantity'])>0 and (b['supplier_id'],key(b['batch_no'])) not in grouped],
        source_records=rows)
    return json.loads(json.dumps(plan,default=str))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dinar-sheet',required=True);args=p.parse_args()
    plan=build(json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8')),json.loads((OUT/'production-snapshot.json').read_text()),args.dinar_sheet)
    (OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(actions=dict(Counter(a['kind'] for a in plan['actions'])),groups=len(plan['outcomes']),
        new_items=plan['new_items'],exceptions=plan['exceptions'],releases=plan['reservation_releases'],omitted_positive=len(plan['omitted_positive_ids']))))
