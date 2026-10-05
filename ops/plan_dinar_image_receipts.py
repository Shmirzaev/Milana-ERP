"""Reconcile DINAR documents supplied as images; omit prices and normalize batch IDs."""
import hashlib
import json
from pathlib import Path
from plan_current_fabric import OUT, num

paths=[Path('C:/Users/User/AppData/Local/Temp/codex-clipboard-0a96786c-5947-4a85-b5b4-9c3004d26259.png'),
       Path('C:/Users/User/AppData/Local/Temp/codex-clipboard-6ada99f8-5e21-4bd4-a6e2-51ee857f9770.png')]
images=[dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
# Batch, kg, rolls, color, color code, tone, receipt date, fabric, invoice, old code.
entries=[
 ('6634','546.8',24,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-01',87,'7117013',None),
 ('6885','576.4',23,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-01',87,'7117013',None),
 ('7036','981.6',40,'BORDO','DG-50205.1','Koyu','2026-10-01',87,'7117013',None),
 ('6901','456.8',20,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-01',87,'7117013',None),
 ('7051','277.8',12,'HAKI','DG-70454.1','Orta','2026-10-01',87,'7117013',None),
 ('7052','141.8',6,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-01',87,'7117013',None),
 ('6799','23.2',1,'FISTIK','DG-70433.1','Koyu','2026-10-01',87,'7117013',None),
 ('6902','577.2',24,'T.SINIY','DG-90006.1','Koyu','2026-10-02',87,'7117027',None),
 ('6312','17',1,'PEMBE','DG-30581.1','Acik','2026-10-02',122,'7117027',None),
 ('7001','530.4',24,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-02',87,'7117027',None),
 ('7102','20',1,'SEKER KASAR','DG-00001.1','S.Kasar','2026-10-03',87,'7117050','ЭКРЮ'),
 ('7114','535',23,'T.SINIY','DG-90006.1','Koyu','2026-10-03',87,'7117050','D-90046'),
 ('7147','559.8',24,'QORA','DG-0098.1','Koyu','2026-10-03',87,'7117050',None),
]
assert sum(num(r[1]) for r in entries[:10])==num(4129) and sum(r[2] for r in entries[:10])==175
assert sum(num(r[1]) for r in entries[10:])==num('1114.8') and sum(r[2] for r in entries[10:])==48
s=json.loads((OUT/'production-snapshot.json').read_text())
assert s['revision']==[{'version_num':'0137_perf34_shipment_indexes'}]
assert all(any(i['id']==iid and i['is_active'] for i in s['items']) for iid in (87,122))
actions=[];outcomes=[];rows=[]
for index,(batch,kg,rolls,color,code,tone,dt,iid,invoice,oldcode) in enumerate(entries):
    ref=f'CIMG{index+1:02}'
    src=dict(**images[0 if index<10 else 1],row=index+1 if index<10 else index-9,
        supplier_id=2,batch_no=batch,remaining_kg=str(num(kg)),remaining_rolls=str(rolls),invoice=invoice,
        source_batch_no='(2026) '+batch+({10:'.3',11:'.2',12:'.1'}.get(index,'')),
        basis='Owner requested receipt import without price, year prefix or dot suffix in batch number')
    rows.append(src)
    matches=[b for b in s['batches'] if b['supplier_id']==2 and b['batch_no']==batch and num(b['quantity'])>0]
    if index<10:
        assert len(matches)==1
        b=matches[0]
        assert num(b['quantity'])==num(kg) and b['piece_count']==rolls and num(b['cost_per_unit'])==0
        assert b['received_date'][:10] in (dt,{'2026-10-01':'2026-09-30','2026-10-02':'2026-10-01'}[dt])
        if b['item_id']==iid:
            values=dict(color=color,color_code=code,color_status=tone)
            values={k:v for k,v in values.items() if b[k]!=v}
            if values:actions.append(dict(ref=ref,kind='update',id=b['id'],values=values,sources=[src]))
        else:
            assert batch=='6312' and b['id']==1803
            assert not any(r['stock_batch_id']==b['id'] for r in s['reservations'])
            assert not any(r.get(k.split(':')[1])==b['id'] for k,rs in s['linked_rows'].items() for r in rs)
            assert not any(m['batch_id']==b['id'] and m['movement_type']!='receive' for m in s['movements'])
            actions.append(dict(ref=ref,kind='update',id=b['id'],values=dict(quantity='0',piece_count=0),sources=[src]))
    else:
        assert not any(b['supplier_id']==2 and (b['batch_no']==batch or b['batch_no'].startswith(batch+'.')) for b in s['batches'])
    if not matches or matches[0]['item_id']!=iid:
        actions.append(dict(ref=ref,kind='receive',item_ref=iid,quantity=str(num(kg)),piece_count=rolls,
            supplier_id=2,batch_no=batch,color=color,color_code=code,color_status=tone,old_code=oldcode,
            received_date=dt,cost_per_unit='0',sources=[src]))
    outcomes.append(dict(ref=ref,target_kg=str(num(kg)),target_rolls=str(rolls),sources=[src]))
changed={a['id'] for a in actions if a['kind']=='update'}
plan=dict(version=3,workbooks=[],source_images=images,actions=actions,outcomes=outcomes,new_items=[],reservation_releases=[],
    exceptions=[],supplemental=[],auxiliary=[],source_records=rows,
    preserved_ids=[b['id'] for b in s['batches'] if b['id'] not in changed],
    omitted_positive_ids=[b['id'] for b in s['batches'] if num(b['quantity'])>0 and not(b['supplier_id']==2 and b['batch_no'] in {r[0] for r in entries})])
(OUT/'current-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'receipts':sum(a['kind']=='receive' for a in actions),'existing_updates':len(changed),
    'new_stock_kg':'1114.8000','new_stock_rolls':48,'document_kg':'5243.8000','document_rolls':223}))
