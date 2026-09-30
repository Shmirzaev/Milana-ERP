"""Conservative batch-level plan. Ambiguous source evidence never becomes a write."""
from collections import defaultdict, Counter
from datetime import datetime, date
from decimal import Decimal
import hashlib
import json
from reconcile_fabric_workbooks import OUT, number, key, read_sources

ALIASES = {
    87: ['30/1 P_CMP SUPREM','30/1 P-CMP SUPREM'],
    12: ['36/1 P_CMP 20 DEN 8% LYC SUPREM','36/1P_CMP 20 DEN 8% LYC SUPREM','36/1 P_CMP 20 DEN LYC 8% SUPREM'],
    81: ['30/1 COMPACT PENYA SUPREM'],
    82: ['30/1 COMPACT SUPREM'],
    7: ['36/1 PENYA COMPACT 5*2 INTERLOK'],
    14: ['36/1 PENYA COMPACT 12*12 INTERLOK','12*12 inerlok'],
    122: ['30/1 PENYA SUPREM'],
    112: ['75/36 COMPACT/SIYAH POL W FACE INTERLOK'],
}
GROUPS={1:'Samo',2:'Dinar',3:'Saff Zuxra',19:'Saff Dana'}

def source_date(value):
    for fmt in ('%Y-%m-%d %H:%M:%S','%d,%m,%Y','%d.%m.%Y'):
        try:return datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    return None

def build_plan(records, snapshot):
    items={i['id']:i for i in snapshot['items']}
    aliases={key(i['name']):i['id'] for i in snapshot['items'] if i['is_active']}
    for item_id, names in ALIASES.items():
        for name in names:aliases[key(name)]=item_id
    src=defaultdict(list); erp=defaultdict(list); linked=defaultdict(list)
    for r in records:src[(r['supplier_id'],key(r['batch_no']))].append(r)
    for b in snapshot['batches']:erp[(b['supplier_id'],key(b['batch_no']))].append(b)
    for name, rows in snapshot['linked_rows'].items():
        table,col=name.split(':')
        for row in rows:linked[row[col]].append(table)
    for r in snapshot['reservations']:linked[r['stock_batch_id']].append('material_reservations')
    for r in snapshot.get('fabric_scans',[]):linked[r['batch_id']].append('fabric_scans')
    movement_types=defaultdict(set)
    for m in snapshot['movements']:movement_types[m['batch_id']].add(m['movement_type'])
    plans=[]
    def entry(rows, batches, status, reason, action=None, target=None, item_id=None):
        current=sum((number(b['quantity']) for b in batches),Decimal(0))
        value={'group':rows[0]['group'] if rows else GROUPS.get(batches[0]['supplier_id'],'Other'),
               'supplier_id':rows[0]['supplier_id'] if rows else batches[0]['supplier_id'],
               'batch_no':rows[0]['batch_no'] if rows else batches[0]['batch_no'],
               'sources':rows,'erp_ids':[b['id'] for b in batches], 'before':batches,
               'current_kg':current,'target_kg':target,'delta_kg':None if target is None else target-current,
               'status':status,'action':action,'reason':reason,'item_id':item_id,
               'erp_fabrics':list(dict.fromkeys(items[b['item_id']]['name'] for b in batches)),
               'linked_tables':sorted({t for b in batches for t in linked[b['id']]}),
               'source_remaining_rolls':sum((r['remaining_rolls'] for r in rows),Decimal(0)) if rows else None}
        plans.append(value)
        return value
    for k,rows in src.items():
        all_batches=erp.get(k,[])
        active=[b for b in all_batches if number(b['quantity'])>0]
        target=sum((r['remaining_kg'] for r in rows),Decimal(0))
        mapped={aliases.get(key(r['fabric'])) for r in rows if r['remaining_kg']>0}
        if not k[1] or any(r['remaining_kg']<0 or ('Receipt rolls or kg missing' in r['issues'] and r['cached_remaining_kg'] is None) for r in rows):
            entry(rows,active,'review','; '.join(sorted({issue for r in rows for issue in r['issues']})),target=target);continue
        if not active and target==0:
            entry(rows,[], 'historical','Source depleted; no active stock to change',target=target);continue
        if len(active)>1:
            entry(rows,active,'review','Multiple active ERP batches share this supplier/batch number; allocation needs review',target=target);continue
        b=active[0] if active else None
        if target==0 and b:
            historical_materials={aliases.get(key(r['fabric'])) for r in rows}
            if historical_materials!={b['item_id']}:
                entry(rows,[b],'review','Workbook depleted but fabric identity differs; do not archive by batch number alone',target=target);continue
            if linked[b['id']]:
                entry(rows,[b],'review','Workbook depleted, but ERP batch has linked business records; preserve history and resolve links',target=target);continue
            entry(rows,[b],'prepared','Workbook explicitly reports zero; archive through stock adjustment, retain historical row','archive',target);continue
        if b:
            target_item=next(iter(mapped)) if len(mapped)==1 else None
            if target_item is None or target_item!=b['item_id']:
                entry(rows,[b],'review','Fabric description differs or is incomplete; batch/material identity needs review',target=target);continue
            if b['warehouse_id']!=1 or b['unit']!='kg' or b['archived_at']:
                entry(rows,[b],'review','Warehouse, unit or archive state needs review',target=target);continue
            reserved=sum((number(r['reserved_quantity'])-number(r['consumed_quantity'])-number(r['released_quantity']) for r in snapshot['reservations'] if r['stock_batch_id']==b['id'] and r['status'] in ('reserved','partially_consumed')),Decimal(0))
            if target<reserved:
                entry(rows,[b],'review','Target falls below active reserved quantity',target=target);continue
            if any(r['batch_id']==b['id'] and r['returned_at'] is None for r in snapshot['linked_rows'].get('eco_fabric_rolls:batch_id',[])):
                entry(rows,[b],'review','Outstanding Eco Cotton rolls must return through existing workflow',target=target);continue
            changed=abs(target-number(b['quantity']))>=Decimal('0.0001')
            p=entry(rows,[b],'prepared' if changed else 'unchanged','Authoritative workbook remaining balance; preserve receipt and consumption history','adjust' if changed else None,target,b['item_id'])
            # Roll arrays and QR positions are receipt history. Do not rewrite
            # them from aggregate remaining-roll counts.
            if p['source_remaining_rolls']!=number(b['piece_count']):
                p['roll_note']='Workbook remaining rolls differ from ERP receipt roll count; historical roll arrays/count preserved'
            continue
        if all_batches:
            entry(rows,all_batches,'review','Source has positive stock but ERP records are depleted/archived; choose receipt identity before restoration',target=target);continue
        other=[b for b in snapshot['batches'] if key(b['batch_no'])==k[1]]
        if other:
            entry(rows,[],'review','Batch number exists under another supplier; avoid duplicate receipt',target=target)
            plans[-1]['other_supplier_candidates']=[b['id'] for b in other];continue
        if len(mapped)!=1 or None in mapped:
            entry(rows,[],'review','Fabric name cannot be mapped unambiguously to active ERP material',target=target);continue
        item_id=next(iter(mapped))
        positive=[r for r in rows if r['remaining_kg']>0]
        fingerprints=[(r['date'],key(r['fabric']),r['received_kg'],r['received_rolls'],r['color_code'],r['color']) for r in positive]
        if len(fingerprints)!=len(set(fingerprints)):
            entry(rows,[],'review','Repeated identical receipt identity in workbook',target=target);continue
        for r in positive:
            dt=source_date(r['date'])
            if dt is None or dt>date(2026,9,30).isoformat() or not re_batch(r['batch_no']):
                entry([r],[],'review','Invalid/future receipt date or nonstandard batch identifier needs confirmation',target=r['remaining_kg']);continue
            p=entry([r],[],'prepared','Missing in ERP; receive current balance only, with source receipt/usage retained in audit evidence','receive',r['remaining_kg'],item_id)
            p['received_date']=dt
            p['proposed_roll_count']=int(r['remaining_rolls']) if r['remaining_rolls']>0 else None
            if p['proposed_roll_count'] is None:
                p['receiving_note']='Authoritative kg accepted; zero/invalid remaining rolls withheld pending corrected count'
    for k,bs in erp.items():
        if k[0] not in GROUPS or k in src:continue
        for b in bs:
            if number(b['quantity'])<=0:continue
            entry([],[b],'review','Positive ERP stock absent from detailed source rows; confirm omission means removal, with linked records preserved',target=Decimal(0),action='proposed_removal')
    return plans

def re_batch(value):
    import re
    return bool(re.fullmatch(r'[A-Za-z0-9/._-]+',value))

def main():
    evidence=json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8'))
    snapshot=json.loads((OUT/'production-snapshot.json').read_text(encoding='utf-8'))
    records=read_sources(evidence)
    plans=build_plan(records,snapshot)
    supplemental=[]
    for r in evidence[0]['sheets'][1]['rows'][1:]:
        v=r['values'];used=number(v[8])
        supplemental.append({'file':evidence[0]['file'],'sheet':'Лист5','row':r['row'],'description':v[5],'received_rolls':v[1],'received_kg':v[2],'remaining_rolls':number(v[1])-used,'remaining_kg':number(v[2]) if not used else None,'color_code':v[4], 'status':'review','reason':'User confirmed current stock. Missing batch and supplier identities; used kg also absent where rolls were issued.'})
    for r in evidence[2]['sheets'][1]['rows'][1:-1]:
        v=r['values'];supplemental.append({'file':evidence[2]['file'],'sheet':'Лист1','row':r['row'],'description':v[1],'batch_no':v[5],'received_rolls':v[3],'received_kg':v[4],'remaining_kg':None,'status':'review','reason':'Receipt-only auxiliary list; current balance and material missing; check overlap before adding'})
    result={'production_release':'20260930_053552','source_commit':'ceadc220003b021a48362ecd95d989c119c7d6d7','snapshot_time':snapshot['snapshot_time'],
            'snapshot_sha256':hashlib.sha256((OUT/'production-snapshot.json').read_bytes()).hexdigest(),
            'workbooks':[{k:b[k] for k in ('file','sha256')} for b in evidence], 'plans':plans,'supplemental':supplemental,
            'notes':['No production writes. Prepared quantities are a partial reconciliation until review rows are resolved.',
                     'User confirmed the displayed remaining-kg column is authoritative, including arithmetic/formula conflicts. Preserve those values; disclose inconsistent rolls separately.',
                     'User confirmed DINAR blank remaining-kg cells use received kg minus recorded usage; blank usage is zero.',
                     'Keep all original IDs, images, costs, roll weights/lengths and business links on existing batches.',
                     'Saff Zuxra N210 double-counts N192 subtotal; sum detail rows only.',
                     'DINAR summary tab omits numbers stored as text and is inconsistent with detailed rows; it is not an import source.',
                     'No hard deletions. Reserved or linked removals remain withheld. Roll-count differences are separately disclosed.']}
    (OUT/'reconciliation-plan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('STATUS',Counter(p['status'] for p in plans))
    print('PREPARED',Counter(p['action'] for p in plans if p['status']=='prepared'))
    for action in ('receive','adjust','archive','proposed_removal'):
        ps=[p for p in plans if p['action']==action]
        print(action,len(ps),'current',sum(p['current_kg'] for p in ps),'target',sum(p['target_kg'] for p in ps),'delta',sum(p['delta_kg'] for p in ps))
    print('REVIEW REASONS',Counter(p['reason'] for p in plans if p['status']=='review'))

if __name__=='__main__':main()
