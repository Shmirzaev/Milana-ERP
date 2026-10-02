"""Offline inventory preview. Cannot connect to or change the production ERP."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from reconcile_fabric_workbooks import OUT, number

def preview(snapshot, plan):
    after=deepcopy(snapshot)
    batches={b['id']:b for b in after['batches']}
    new_id=max(batches)+1
    movement_id=max(m['id'] for m in after['movements'])+1
    changed=[]
    for p in plan['plans']:
        if p['status']!='prepared':continue
        qty=number(p['target_kg'])
        if qty<0:raise ValueError('Negative target')
        if p['action']=='receive':
            if p['erp_ids'] or p['before']:raise ValueError('New receipt has an existing identity')
            row={'id':new_id,'item_id':p['item_id'],'batch_no':p['batch_no'],'supplier_id':p['supplier_id'],
                 'quantity':str(qty),'piece_count':p.get('proposed_roll_count'),
                 'unit':'kg','warehouse_id':1,'received_date':p['received_date'],'qc_status':'pending',
                 'archived_at':None,'roll_weights_kg':[],'roll_lengths_m':[],
                 'preview_only':True,'cost_per_unit':None,'image_url':None}
            # Costs and individual-roll weights are not present in the source.
            # These are unresolved receiving fields, not invented financial data.
            batches[new_id]=row;after['batches'].append(row);new_id+=1
            delta=qty;action='receive'
        else:
            if len(p['erp_ids'])!=1:raise ValueError('Ambiguous existing batch')
            row=batches[p['erp_ids'][0]]
            if row!=p['before'][0]:raise ValueError('Snapshot changed since plan creation')
            delta=qty-number(row['quantity']);row['quantity']=str(qty)
            if p['action']=='archive':
                if p['linked_tables']:raise ValueError('Linked archive forbidden')
                row['archived_at']='PREVIEW ONLY: depletion reconciliation'
            action='adjustment' if delta>0 else 'issue'
        if delta:
            after['movements'].append({'id':movement_id,'movement_type':action,'item_id':row['item_id'],
               'batch_id':row['id'],'quantity':str(abs(delta)),'unit':'kg',
               'from_warehouse_id':1 if delta<0 else None,'to_warehouse_id':1 if delta>0 else None,
               'reference_type':'FabricReconciliationPreview','preview_only':True})
            movement_id+=1
        changed.append(row['id'])
    before_total=sum((number(b['quantity']) for b in snapshot['batches']),Decimal(0))
    after_total=sum((number(b['quantity']) for b in after['batches']),Decimal(0))
    expected=sum((number(p['delta_kg']) for p in plan['plans'] if p['status']=='prepared'),Decimal(0))
    assert after_total-before_total==expected
    assert len(changed)==len(set(changed))
    for field in ('items','suppliers','reservations','linked_rows','fabric_scans'):
        assert after[field]==snapshot[field],field
    originals={b['id']:b for b in snapshot['batches']}
    for bid,b in batches.items():
        if bid not in originals:continue
        for field,value in originals[bid].items():
            if field not in ('quantity','archived_at'):assert b[field]==value,(bid,field)
        if bid not in changed:assert b==originals[bid]
    return after, {'before_total_kg':str(before_total),'after_preview_total_kg':str(after_total),'net_delta_kg':str(expected),
                   'existing_batch_count':len(snapshot['batches']),'preview_batch_count':len(after['batches']),
                   'changed_batch_count':len(changed),'new_movements':len(after['movements'])-len(snapshot['movements']),
                   'production_writes':0,'hard_deletions':0,'unrelated_data_preserved':True,
                   'limitation':'Offline data preview only; no API/SQL execution rehearsal or production change. New receipt valuation, QC, photos and roll-weight allocation still require the existing receiving workflow.'}

def main():
    raw=(OUT/'production-snapshot.json').read_bytes()
    snapshot=json.loads(raw)
    plan=json.loads((OUT/'reconciliation-plan.json').read_text(encoding='utf-8'))
    if hashlib.sha256(raw).hexdigest()!=plan['snapshot_sha256']:raise ValueError('Snapshot fingerprint mismatch')
    after,checks=preview(snapshot,plan)
    (OUT/'offline-inventory-preview.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'preview-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks))

if __name__=='__main__':main()
