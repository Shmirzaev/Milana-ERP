"""Follow-up decisions: retain omitted stock, use workbook counts and identities."""
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from plan_fabric_reconciliation import ALIASES, source_date
from reconcile_fabric_workbooks import OUT, key, number


def make_plan(original, snapshot):
    items = {i['id']: i for i in snapshot['items']}
    batches = {b['id']: b for b in snapshot['batches']}
    names = {key(i['name']): i['id'] for i in snapshot['items'] if i['is_active']}
    for iid, variants in ALIASES.items():
        for name in variants:
            names[key(name)] = iid
    names[key('36/1 VOSKON 20 DEN 8% LYC SUPREM')] = 115
    names[key('36/1 P_CMP 20 DEN 8% LUC SUPREM')] = 12
    links = defaultdict(set)
    for name, rows in snapshot['linked_rows'].items():
        column = name.split(':')[1]
        for r in rows:
            links[r[column]].add(name)
    reserved = defaultdict(Decimal)
    active_reservations = defaultdict(list)
    for r in snapshot['reservations']:
        if r['status'] in ('reserved', 'partially_consumed'):
            remaining = number(r['reserved_quantity'])-number(r['consumed_quantity'])-number(r['released_quantity'])
            reserved[r['stock_batch_id']] += remaining
            if remaining > 0:
                active_reservations[r['stock_batch_id']].append(r)
    actions, outcomes, new_items, releases, exceptions = [], [], {}, {}, []
    preserved_ids = sorted(p['erp_ids'][0] for p in original['plans'] if p['action']=='proposed_removal')

    def action(ref, bid, values, rows, reason):
        before = batches[bid]
        for field in ('quantity',):
            if field in values and number(values[field]) == number(before[field]):
                values.pop(field)
        if 'piece_count' in values and values['piece_count'] == before['piece_count']:
            values.pop('piece_count')
        if not values:
            return
        if 'quantity' in values and number(values['quantity']) < reserved[bid]:
            if number(values['quantity']) != 0:
                raise ValueError('Nonzero target below reservation needs a separate allocation')
            for r in active_reservations[bid]:
                releases[r['id']] = {'id':r['id'],'batch_id':bid,'ref':ref,
                    'remaining_kg':str(number(r['reserved_quantity'])-number(r['consumed_quantity'])-number(r['released_quantity'])),
                    'before':r,'reason':'User confirmed Excel zero physical stock; release only the unconsumed reservation, retain consumed history.'}
        if 'piece_count' in values and before['roll_lengths_m']:
            raise ValueError('Do not reindex individual roll lengths')
        actions.append({'ref':ref,'kind':'update','id':bid,'values':values,'sources':rows,'reason':reason})

    def target_item(r, existing):
        # Dana row 26 puts the material in H and its color in I.
        if r['supplier_id']==19 and r['row']==26 and r['fabric']=='KIRMIZI':
            r['fabric']='RAPORLI INTERLOK 5*2';r['color']='KIRMIZI';r['color_code']=''
            return 40
        # This source row supplies only a color. Keep the known ERP material.
        if r['supplier_id']==19 and r['row']==247 and key(r['fabric'])==key('beyaz kasar'):
            r['color']=r['fabric'];r['fabric']='';r['color_code']=''
            assert len(existing)==1 and existing[0]['item_id']==121
            return 121
        iid=names.get(key(r['fabric']))
        if iid:
            return iid
        if not r['fabric']:
            raise ValueError('Missing required material')
        name=r['fabric']; sku='FAB-SOURCE-'+hashlib.sha256(name.encode()).hexdigest()[:16].upper()
        new_items[sku]={'sku':sku,'name':name,'category':'fabric','unit':'kg','track_batch':True}
        return sku

    def receive(ref,r,iid,qty,count,cost='0',image_fallback=None):
        actions.append({'ref':ref,'kind':'receive','item_ref':iid,'quantity':str(qty),'piece_count':count,
            'supplier_id':r.get('supplier_id'),'batch_no':r.get('batch_no',''),
            'color':r.get('color') or None,'color_code':r.get('color_code') or None,
            'received_date':source_date(r.get('date','')),'cost_per_unit':str(cost),
            'sources':[r], 'image_fallback':image_fallback})

    conflicts=[p for p in original['plans'] if p['status']=='review' and p['action']!='proposed_removal']
    for idx,p in enumerate(conflicts,1):
        ref=f'C{idx:03}';rows=deepcopy(p['sources']);target=number(p['target_kg'])
        existing=[batches[i] for i in p['erp_ids']]
        active=[b for b in existing if number(b['quantity'])>0]
        if target==0:
            for b in active:
                counts=sum(number(r['cached_remaining_rolls'] if r['cached_remaining_rolls'] is not None else r['remaining_rolls']) for r in rows)
                count=0 if counts>=0 else None
                if counts<0:
                    exceptions.append({'ref':ref,'reason':'Excel remaining rolls are negative; ERP count left blank, kg set to zero.','source_rolls':str(counts),'sources':rows})
                action(ref,b['id'],{'quantity':'0','piece_count':count},rows,'Excel explicitly depleted; archive through adjustment, retain links and history.')
            outcomes.append({'ref':ref,'target_kg':'0','ids':[b['id'] for b in active],'status':'zero balance','sources':rows})
            continue
        positive=[r for r in rows if number(r['remaining_kg'])>0]
        assert len(positive)==1, ('Multiple positive source identities need allocation',ref)
        r=positive[0];iid=target_item(r,existing)
        roll=number(r['cached_remaining_rolls'] if r['cached_remaining_rolls'] is not None else r['remaining_rolls'])
        if roll<0 or roll!=int(roll):
            raise ValueError('Invalid positive-stock roll count')
        count=int(roll)
        # Prefer the existing exact material/quantity/color/roll match. Explicit
        # user authority to follow Excel permits zeroing obsolete duplicate balances.
        matching=[b for b in active if b['item_id']==iid and b['archived_at'] is None]
        matching.sort(key=lambda b:(number(b['quantity'])==target,
                       key(b['color'])==key(r['color']) and bool(r['color']),b['piece_count']==count,b['id']),reverse=True)
        chosen=matching[0] if matching else None
        for b in active:
            if chosen and b['id']==chosen['id']:
                continue
            action(ref,b['id'],{'quantity':'0','piece_count':0},rows,
                   'Replace conflicting current balance with source-identified stock; preserve historical material references.')
        if chosen:
            values={'quantity':str(target),'piece_count':count}
            if r['color']:values['color']=r['color']
            if r['color_code']:values['color_code']=r['color_code']
            action(ref,chosen['id'],values,rows,'Use the authoritative Excel balance and remaining roll count.')
            outcomes.append({'ref':ref,'target_kg':str(target),'target_rolls':count,'ids':[chosen['id']],
                             'status':'existing batch matched','sources':rows})
        else:
            cost=active[0]['cost_per_unit'] if len(active)==1 else '0'
            # Retain all old depleted/used batch identities. A reconciliation
            # receipt represents the confirmed current balance without rewriting consumption.
            receive(ref,r,iid,target,count,cost)
            outcomes.append({'ref':ref,'target_kg':str(target),'target_rolls':count,'ids':[],
                             'status':'source receipt','sources':rows})

    roll_plans=[p for p in original['plans'] if p.get('roll_note')]
    for idx,p in enumerate(roll_plans,1):
        ref=f'R{idx:03}';bid=p['erp_ids'][0]
        count=sum(number(r['cached_remaining_rolls'] if r['cached_remaining_rolls'] is not None else r['remaining_rolls']) for r in p['sources'])
        assert count>=0 and count==int(count)
        action(ref,bid,{'piece_count':int(count)},p['sources'],'User requested Excel remaining-roll count; keep original roll weights and QR history.')
        outcomes.append({'ref':ref,'target_rolls':int(count),'ids':[bid],'status':'remaining rolls matched','sources':p['sources']})

    supplemental=[]
    for idx,p in enumerate(original['supplemental'],1):
        ref=f'S{idx:03}';row=deepcopy(p)
        if idx<=15:
            r={'file':p['file'],'sheet':p['sheet'],'row':p['row'],'batch_no':'','supplier_id':None,
               'fabric':'БАМБУК','color':'','color_code':'','date':'','remaining_kg':p['remaining_kg'],
               'remaining_rolls':p['remaining_rolls']}
            receive(ref,r,4,number(p['remaining_kg']),int(number(p['remaining_rolls'])))
            row.update(ref=ref,status='added with supplier/batch blank',target_kg=p['remaining_kg'])
        elif idx>=23:
            bn=str(p['batch_no']);matches=[r for x in original['plans'] for r in x['sources']
                  if r['supplier_id']==3 and r['batch_no']==bn and number(r['received_kg'])==number(p['received_kg'])
                  and number(r['received_rolls'])==number(p['received_rolls'])]
            assert len(matches)==1 and number(matches[0]['remaining_kg'])==0
            row.update(ref=ref,status='duplicate receipt, detailed sheet confirms depleted',duplicate_source=matches[0])
        else:
            row.update(ref=ref,status='not posted: ERP requires material and known remaining kg')
            exceptions.append({'ref':ref,'reason':row['status'],'sources':[p]})
        supplemental.append(row)
    # The earlier two receipts with zero displayed rolls used unknown counts.
    # The user's new explicit rule now permits recording the exact zero.
    prior_by_ref={(b['supplier_id'],key(b['batch_no'])):b for b in snapshot['batches'] if number(b['quantity'])>0}
    for p in original['plans']:
        if p['status']=='prepared' and p['action']=='receive' and p.get('proposed_roll_count') is None:
            b=prior_by_ref[(p['supplier_id'],key(p['batch_no']))]
            action('Additional roll balance',b['id'],{'piece_count':0},p['sources'],'Record source zero rolls exactly per updated user instruction.')
    assert not set(preserved_ids)&{a['id'] for a in actions if a['kind']=='update'}
    assert len(conflicts)==89 and len(roll_plans)==49 and len(preserved_ids)==69
    # A single batch may have at most one planned mutation, so accounting is exact.
    ids=[a['id'] for a in actions if a['kind']=='update']
    assert len(ids)==len(set(ids))
    return {'version':2,'workbooks':original['workbooks'],'preserved_ids':preserved_ids,'actions':actions,
            'outcomes':outcomes,'supplemental':supplemental,'new_items':list(new_items.values()),
            'reservation_releases':list(releases.values()),'exceptions':exceptions}


if __name__=='__main__':
    original=json.loads((OUT/'reconciliation-plan.json').read_text(encoding='utf-8'))
    snapshot=json.loads((OUT/'continuation-before.json').read_text(encoding='utf-8'))
    result=make_plan(original,snapshot)
    (OUT/'continuation-plan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'actions':dict(Counter(a['kind'] for a in result['actions'])),
         'new_items':result['new_items'],'reservation_releases':result['reservation_releases'],
         'exceptions':[(r['ref'],r['reason']) for r in result['exceptions']]},ensure_ascii=True))
