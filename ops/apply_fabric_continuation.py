"""Apply the user's follow-up decisions with an atomic ERP transaction."""
import base64
import hashlib
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.routes.inventory import create_item, update_item, receive_stock, update_batch, release_reservation, restore_material_batch
from app.core.config import settings
from app.core.deps import user_permissions
from app.models import AuditLog, User, StockBatch, MaterialReservation, Item
from app.schemas.inventory import ItemIn, StockBatchIn, StockBatchUpdate, StockBatchRestoreIn
from app.services.audit import log_action
from app.services.image_storage import convert_image_to_webp, prebuild_webp_thumbnails
from app.services.inventory import material_reservation_status_for_production_order
from apply_fabric_reconciliation import AtomicSession, digest, assert_unchanged


def execute(db, actor, plan, plan_hash, image_urls):
    item_ids={};changes=[];released=[]
    for iid in plan.get('reactivate_items',[]):
        item=db.get(Item,iid)
        assert item and not item.is_active
        data={k:getattr(item,k) for k in ItemIn.model_fields}
        data['is_active']=True
        update_item(iid,ItemIn(**data),db,actor)
    for row in plan['new_items']:
        item=create_item(ItemIn(**row),db,actor)
        item_ids[row['sku']]=item.id
    for row in plan['reservation_releases']:
        before=db.get(MaterialReservation,row['id'])
        assert before and before.stock_batch_id==row['batch_id']
        assert Decimal(str(before.consumed_quantity))==Decimal(row['before']['consumed_quantity'])
        response=release_reservation(row['id'],db,actor)
        log_action(db,None,'source_zero_reservation','MaterialReservation',row['id'],
            new_value={'operator':'Codex, explicit Excel-as-source user decision', 'plan_sha256':plan_hash,
                       'source_ref':row['ref'],'released_kg':row['remaining_kg'],'reason':row['reason']})
        released.append({'id':row['id'],'kg':row['remaining_kg'],'production_order_id':before.production_order_id})
    for index,a in enumerate(plan['actions']):
        if a['kind']=='update':
            bid=a['id'];batch=db.get(StockBatch,bid)
            before_kg=str(batch.quantity)
            values=dict(a['values'])
            if 'quantity' in values:values['quantity']=float(values['quantity'])
            if a.get('restore_reason'):
                assert Decimal(before_kg)==0 and batch.archived_at is not None
                restore_material_batch(bid,StockBatchRestoreIn(quantity=Decimal(a['values']['quantity']),
                    reason=a['restore_reason']),db,actor)
                update_batch(bid,StockBatchUpdate(piece_count=values['piece_count']),db,actor,force=False)
            else:
                update_batch(bid,StockBatchUpdate(**values),db,actor,force=False)
        else:
            iid=item_ids.get(a['item_ref'],a['item_ref'])
            response=receive_stock(StockBatchIn(item_id=iid,batch_no=a['batch_no'],supplier_id=a['supplier_id'],
                quantity=float(a['quantity']),piece_count=a['piece_count'],unit='kg',warehouse_id=1,
                cost_per_unit=float(a['cost_per_unit']),qc_status='pending',color=a['color'],color_code=a['color_code'],
                old_code=a.get('old_code'),color_status=a.get('color_status'),
                roll_weights_kg=a.get('roll_weights_kg',[]),roll_lengths_m=a.get('roll_lengths_m',[]),
                image_url=image_urls.get(str(index))),db,actor,idempotency_key=f'fabric-current:{plan_hash[:24]}:{index}')
            bid=response['id'];before_kg='0'
            if a['received_date']:
                update_batch(bid,StockBatchUpdate(received_date=datetime.fromisoformat(a['received_date']+'T00:00:00+05:00')),db,actor)
        db.flush();batch=db.get(StockBatch,bid);db.refresh(batch)
        log_action(db,None,'workbook_current_sync','StockBatch',bid,new_value={
            'operator':'Codex, explicit user follow-up', 'plan_sha256':plan_hash,'review_id':a['ref'],
            'source_rows':a['sources'],'before_kg':before_kg,'after_kg':str(batch.quantity),
            'after_rolls':batch.piece_count,'workbooks':plan['workbooks'],
            'meaning':'Current physical balance; preserve historical batches, movements and downstream references.'})
        changes.append({'index':index,'ref':a['ref'],'id':bid,'kind':a['kind'],'before_kg':before_kg,
                        'after_kg':str(batch.quantity),'after_rolls':batch.piece_count,'item_id':batch.item_id,
                        'image_url':batch.image_url})
    return changes,item_ids,released


def verify(before,after,plan,changes,new_items):
    old={r['id']:r for r in before['batches']};new={r['id']:r for r in after['batches']}
    by_id={c['id']:c for c in changes};assert len(by_id)==len(changes)
    assert set(old)<=set(new)
    for bid,row in old.items():
        c=by_id.get(bid);allowed=set()
        if c:
            a=plan['actions'][c['index']];allowed=set(a['values'])|{'updated_at'}
            if a['values'].get('quantity')=='0':allowed|={'archived_at','archived_by'}
        assert all(new[bid][k]==v for k,v in row.items() if k not in allowed),('Protected batch field',bid)
    for bid in plan['preserved_ids']:assert old[bid]==new[bid],('Retained ERP-only batch',bid)
    for c in changes:
        a=plan['actions'][c['index']];b=new[c['id']]
        if a['kind']=='update':
            for k,v in a['values'].items():
                assert (Decimal(b[k])==Decimal(v)) if k=='quantity' else b[k]==v,(c['ref'],k)
        else:
            assert Decimal(b['quantity'])==Decimal(a['quantity']) and b['piece_count']==a['piece_count']
            assert b['supplier_id']==a['supplier_id'] and b['batch_no']==a['batch_no']
            assert b['item_id']==new_items.get(a['item_ref'],a['item_ref'])
            assert Decimal(b['cost_per_unit'])==Decimal(a['cost_per_unit'])
            for k in ('color','color_code','old_code','color_status'):
                assert b[k]==a.get(k),(c['ref'],k)
            assert b['roll_weights_kg']==a.get('roll_weights_kg',[]) and b['roll_lengths_m']==a.get('roll_lengths_m',[])
        if Decimal(b['quantity'])==0:assert b['archived_at']
    for key in ('suppliers','warehouses','revision','batch_references','linked_rows','fabric_scans'):
        assert before[key]==after[key],key
    ai={i['id']:i for i in after['items']}
    for r in before['items']:
        expected=dict(r)
        if r['id'] in plan.get('reactivate_items',[]):
            expected['is_active']=True
            expected['updated_at']=ai[r['id']]['updated_at']
        assert ai[r['id']]==expected
    assert len(ai)==len(before['items'])+len(new_items)
    old_movements={m['id']:m for m in before['movements']};new_movements={m['id']:m for m in after['movements']}
    assert all(new_movements.get(mid)==m for mid,m in old_movements.items()),'Historical ledger changed'
    added=[m for mid,m in new_movements.items() if mid not in old_movements]
    expected_count=0
    for c in changes:
        delta=Decimal(c['after_kg'])-Decimal(c['before_kg'])
        movement=[m for m in added if m['batch_id']==c['id']]
        if delta:
            expected_count+=1
            assert len(movement)==1 and Decimal(movement[0]['quantity'])==abs(delta)
            restoration=plan['actions'][c['index']].get('restore_reason')
            assert movement[0]['movement_type']==('return' if restoration else 'receive' if c['kind']=='receive' else 'issue' if delta<0 else 'adjustment')
            if restoration:assert movement[0]['reference_type']=='StockBatchRestore'
        else:assert not movement
    assert len(added)==expected_count
    r_after={r['id']:r for r in after['reservations']};released={r['id']:r for r in plan['reservation_releases']}
    for r in before['reservations']:
        actual=r_after[r['id']]
        if r['id'] not in released:assert actual==r
        else:
            assert all(actual[k]==v for k,v in r.items() if k not in ('released_quantity','status','updated_at'))
            assert Decimal(actual['released_quantity'])==Decimal(r['released_quantity'])+Decimal(released[r['id']]['remaining_kg'])
            assert actual['status']=='released'
    for r in after['reservations']:
        if r['status'] in ('reserved','partially_consumed'):
            outstanding=Decimal(r['reserved_quantity'])-Decimal(r['consumed_quantity'])-Decimal(r['released_quantity'])
            assert Decimal(new[r['stock_batch_id']]['quantity'])>=outstanding
    pictures={r['url']:r['sha256'] for r in after['images']}
    assert all(pictures[r['url']]==r['sha256'] for r in before['images'])
    norm=lambda v: ''.join(str(v or '').upper().split())
    for o in plan['outcomes']:
        if o['ref'].startswith('C'):
            row=o['sources'][0]
            total=sum(Decimal(b['quantity']) for b in new.values() if b['supplier_id']==row['supplier_id'] and norm(b['batch_no'])==norm(row['batch_no']))
            assert total==Decimal(o['target_kg']),(o['ref'],total,o['target_kg'])
            live=[b for b in new.values() if b['supplier_id']==row['supplier_id'] and norm(b['batch_no'])==norm(row['batch_no']) and Decimal(b['quantity'])>0]
            if Decimal(o['target_rolls'])>=0 and all(b['piece_count'] is not None for b in live):
                assert sum(b['piece_count'] for b in live)==Decimal(o['target_rolls']),(o['ref'],'remaining rolls')
        else:
            assert new[o['ids'][0]]['piece_count']==o['target_rolls']
    assert len(new)-len(old)==sum(c['kind']=='receive' for c in changes)
    for r in plan['supplemental']:
        assert Decimal(new[r['id']]['quantity'])==Decimal(r['kg']) and new[r['id']]['piece_count']==r['rolls']
    total_before=sum(Decimal(r['quantity']) for r in old.values());total_after=sum(Decimal(r['quantity']) for r in new.values())
    assert total_after-total_before==sum(Decimal(c['after_kg'])-Decimal(c['before_kg']) for c in changes)
    return {'before_kg':str(total_before),'after_kg':str(total_after),'net_change_kg':str(total_after-total_before),
        'updated_batches':sum(c['kind']=='update' for c in changes),'new_receipts':sum(c['kind']=='receive' for c in changes),
        'archived_batches':sum(bool(new[c['id']]['archived_at']) and c['kind']=='update' for c in changes),
        'new_ledger_movements':len(added),'untouched_existing_batches':len(plan['preserved_ids']),
        'kept_erp_only':len(plan['omitted_positive_ids']),
        'source_group_kg_matches':len(plan['outcomes']),'new_items':len(new_items),
        'supplemental_verified':len(plan['supplemental']),'exceptions':len(plan['exceptions']),
        'hard_deletions':0,'historical_records_preserved':True}


def apply(engine,capture,payload):
    plan=payload['plan'];ph=digest(plan);backup=payload['backup']
    assert ph==payload['plan_sha256'] and plan['version']==3
    assert plan['actions'] and all(a['kind'] in ('update','receive') for a in plan['actions'])
    assert backup['bytes']>0 and backup['restore_objects']>100 and backup['mode']=='0o600'
    # Convert source files before holding inventory table locks. Atomic files
    # may remain unattached after rollback; no stock is created until commit.
    urls={}
    for index,record in payload['images'].items():
        raw=base64.b64decode(record['base64'],validate=True);assert hashlib.sha256(raw).hexdigest()==record['sha256']
        converted=convert_image_to_webp(raw)
        name='fabric-current-20261003-'+record['sha256'][:24]+'.webp';p=Path(settings.MODEL_FILES_DIR)/name
        if p.exists():assert p.read_bytes()==converted.data
        else:
            with p.open('xb') as f:f.write(converted.data)
            prebuild_webp_thumbnails(converted.data,thumbnail_root=p.parent/'_thumbs',source_file_name=name)
        urls[index]='/storage/model-files/'+name
    with AtomicSession(bind=engine,autoflush=False,expire_on_commit=False) as db:
        # Current audit serialization requires READ COMMITTED; explicit domain
        # locks and a full evidence recheck prevent concurrent inventory drift.
        db.execute(text('SET TRANSACTION ISOLATION LEVEL READ COMMITTED'))
        db.execute(text("SET LOCAL lock_timeout='10s'"));db.execute(text("SET LOCAL statement_timeout='60s'"))
        db.execute(text('SELECT pg_advisory_xact_lock(20261002,188)'))
        tables={'items','suppliers','warehouses','stock_batches','stock_movements','material_reservations','fabric_scans'}
        tables|={r['table_name'] for r in payload['snapshot']['batch_references']}
        assert all(t.replace('_','').isalnum() for t in tables)
        db.execute(text('LOCK TABLE '+','.join('"'+t+'"' for t in sorted(tables))+' IN SHARE ROW EXCLUSIVE MODE'))
        for a in db.query(AuditLog).filter_by(action='workbook_current_sync_done',entity_type='StockBatch').all():
            if (a.new_value_json or {}).get('plan_sha256')==ph:return {'already_applied':True,**a.new_value_json}
        assert_unchanged(payload['snapshot'],capture(db))
        actor=db.get(User,1);assert actor and actor.is_active and actor.name=='System Admin' and '*' in user_permissions(actor)
        changes,new_items,released=execute(db,actor,plan,ph,urls)
        checks=verify(payload['snapshot'],capture(db),plan,changes,new_items)
        planning=[]
        for r in released:
            status=material_reservation_status_for_production_order(db,r['production_order_id'])
            planning.append({'production_order_id':r['production_order_id'],'summary':status['summary']})
        result={'plan_sha256':ph,'changes':changes,'new_items':new_items,'released_reservations':released,
                'planning':planning,'checks':checks,'backup':backup,'source_images':len(urls),
                'applied_at':datetime.now(timezone.utc).isoformat()}
        audit=log_action(db,None,'workbook_current_sync_done','StockBatch',None,new_value=result)
        Session.commit(db)
        result['audit_id']=audit.id
        return result
