"""Explicit, atomic application of a reviewed inventory plan via ERP handlers.

Loaded inside the verified live container by run_fabric_reconciliation.py.
No standalone default execution and no direct SQL business-data mutation.
"""
import base64
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.routes.inventory import receive_stock, update_batch
from app.core.config import settings
from app.core.deps import user_permissions
from app.models import AuditLog, StockBatch, User
from app.schemas.inventory import StockBatchIn, StockBatchUpdate
from app.services.audit import log_action
from app.services.image_storage import convert_image_to_webp, prebuild_webp_thumbnails


class AtomicSession(Session):
    def commit(self):
        self.flush()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def assert_unchanged(expected, actual):
    for key in expected:
        if key != 'snapshot_time' and expected[key] != actual[key]:
            raise ValueError('Live evidence changed: ' + key)


def execute_rows(db, actor, plan, plan_hash, image_urls=None):
    changes = []
    for index, p in enumerate(plan['plans']):
        if p['status'] != 'prepared':
            continue
        target = Decimal(p['target_kg'])
        if not target.is_finite() or target < 0:
            raise ValueError('Invalid target')
        if p['action'] == 'receive':
            if p['erp_ids'] or p['before'] or target <= 0 or len(p['sources']) != 1:
                raise ValueError('Invalid new receipt identity')
            source = p['sources'][0]
            response = receive_stock(StockBatchIn(
                item_id=p['item_id'], batch_no=p['batch_no'], supplier_id=p['supplier_id'],
                color=source.get('color') or None, color_code=source.get('color_code') or None,
                quantity=float(target), piece_count=p.get('proposed_roll_count'),
                unit='kg', warehouse_id=1, cost_per_unit=0, qc_status='pending',
                image_url=(image_urls or {}).get(str(index)),
            ), db, actor, idempotency_key=f'fabric-reconcile:{plan_hash[:24]}:{index}')
            bid = response['id']
            update_batch(bid, StockBatchUpdate(received_date=datetime.fromisoformat(
                p['received_date'] + 'T00:00:00+05:00')), db, actor)
        else:
            if p['action'] not in ('adjust', 'archive') or len(p['erp_ids']) != 1:
                raise ValueError('Invalid existing batch action')
            if p['action'] == 'archive' and (target != 0 or p['linked_tables']):
                raise ValueError('Unsafe archive')
            bid = p['erp_ids'][0]
            batch = db.get(StockBatch, bid)
            if not batch or Decimal(str(batch.quantity)) != Decimal(p['current_kg']):
                raise ValueError('Stale batch quantity')
            update_batch(bid, StockBatchUpdate(quantity=float(target)), db, actor, force=False)
        batch = db.get(StockBatch, bid)
        db.refresh(batch)
        if Decimal(str(batch.quantity)) != target:
            raise ValueError('Handler quantity mismatch')
        if p['action'] == 'archive' and not batch.archived_at:
            raise ValueError('Depletion did not archive')
        log_action(db, None, 'workbook_reconcile', 'StockBatch', bid, new_value={
            'operator': 'Codex, explicit user request', 'plan_sha256': plan_hash,
            'source_rows': p['sources'], 'action': p['action'], 'before_kg': p['current_kg'],
            'after_kg': p['target_kg'], 'source_workbooks': plan['workbooks'],
        })
        changes.append({'plan_index': index, 'id': bid, 'batch_no': batch.batch_no,
                        'action': p['action'], 'before_kg': p['current_kg'],
                        'after_kg': str(batch.quantity), 'image_url': batch.image_url})
    return changes


def verify_after(before, after, changes):
    changed = {c['id']: c for c in changes}
    old = {b['id']: b for b in before['batches']}
    new = {b['id']: b for b in after['batches']}
    if len(changed) != len(changes) or not set(old) <= set(new):
        raise ValueError('Duplicate change or hard deletion')
    for bid, row in old.items():
        allowed = {'quantity', 'updated_at'} if bid in changed else set()
        if bid in changed and changed[bid]['action'] == 'archive':
            allowed |= {'archived_at', 'archived_by'}
        for field, value in row.items():
            if field not in allowed and new[bid][field] != value:
                raise ValueError(f'Unrelated batch metadata changed: {bid}/{field}')
    for c in changes:
        if Decimal(new[c['id']]['quantity']) != Decimal(c['after_kg']):
            raise ValueError('Post-application target mismatch')
    for field in ('items', 'suppliers', 'warehouses', 'revision', 'reservations', 'linked_rows', 'fabric_scans', 'batch_references'):
        if before[field] != after[field]:
            raise ValueError('Protected business data changed: ' + field)
    images = {r['url']: r['sha256'] for r in after['images']}
    if any(images.get(r['url']) != r['sha256'] for r in before['images']):
        raise ValueError('Existing picture changed')
    movements = {m['id']: m for m in after['movements']}
    if any(movements.get(m['id']) != m for m in before['movements']):
        raise ValueError('Historical movement changed')
    added = [m for m in after['movements'] if m['id'] not in {r['id'] for r in before['movements']}]
    if len(added) != len(changes):
        raise ValueError('Unexpected ledger count')
    for c in changes:
        delta = Decimal(c['after_kg']) - Decimal(c['before_kg'])
        found = [m for m in added if m['batch_id'] == c['id']]
        expected_type = 'receive' if c['action'] == 'receive' else ('adjustment' if delta > 0 else 'issue')
        if len(found) != 1 or Decimal(found[0]['quantity']) != abs(delta) or found[0]['movement_type'] != expected_type:
            raise ValueError('Unexpected ledger movement')
    before_kg = sum(Decimal(b['quantity']) for b in old.values())
    after_kg = sum(Decimal(b['quantity']) for b in new.values())
    delta = sum(Decimal(c['after_kg']) - Decimal(c['before_kg']) for c in changes)
    if after_kg - before_kg != delta or len(new) - len(old) != sum(c['action'] == 'receive' for c in changes):
        raise ValueError('Aggregate mismatch')
    return {'before_total_kg': str(before_kg), 'after_total_kg': str(after_kg),
            'net_delta_kg': str(delta), 'actions': dict(Counter(c['action'] for c in changes)),
            'new_movements': len(added), 'hard_deletions': 0, 'protected_data_preserved': True}


def apply(engine, capture, payload):
    plan, expected = payload['plan'], payload['snapshot']
    plan_hash = digest(plan)
    if payload['plan_sha256'] != plan_hash or plan['production_release'] != '20260930_053552':
        raise ValueError('Plan identity mismatch')
    if Counter(p['action'] for p in plan['plans'] if p['status'] == 'prepared') != {'receive': 91, 'adjust': 54, 'archive': 22}:
        raise ValueError('Reviewed scope changed')
    backup = payload['backup']
    if backup['bytes'] <= 0 or backup['restore_objects'] < 100 or backup['mode'] != '0o600':
        raise ValueError('Verified backup required')
    with AtomicSession(bind=engine, autoflush=False, expire_on_commit=False) as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE'))
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        db.execute(text("SET LOCAL statement_timeout = '60s'"))
        db.execute(text('SELECT pg_advisory_xact_lock(20260930, 167)'))
        tables = {'stock_batches', 'stock_movements', 'material_reservations', 'items', 'suppliers',
                  'warehouses', 'fabric_scans', 'audit_logs'}
        tables |= {r['table_name'] for r in expected['batch_references']}
        if not all(t.replace('_', '').isalnum() for t in tables):
            raise ValueError('Invalid lock identifier')
        db.execute(text('LOCK TABLE ' + ','.join('"'+t+'"' for t in sorted(tables)) + ' IN SHARE ROW EXCLUSIVE MODE'))
        prior = db.query(AuditLog).filter_by(action='workbook_reconcile_done', entity_type='StockBatch').all()
        for entry in prior:
            if (entry.new_value_json or {}).get('plan_sha256') == plan_hash:
                return {'already_applied': True, **entry.new_value_json}
        assert_unchanged(expected, capture(db))
        actor = db.get(User, 1)
        if not actor or actor.name != 'System Admin' or not actor.is_active or '*' not in user_permissions(actor):
            raise ValueError('Expected operations actor unavailable')
        image_urls = {}
        for index, record in payload.get('images', {}).items():
            raw = base64.b64decode(record['base64'], validate=True)
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('Picture fingerprint mismatch')
            converted = convert_image_to_webp(raw)
            name = 'fabric-reconcile-20260930-' + record['sha256'][:24] + '.webp'
            path = Path(settings.MODEL_FILES_DIR) / name
            if path.exists():
                if path.read_bytes() != converted.data:
                    raise ValueError('Picture filename collision')
            else:
                with path.open('xb') as output:
                    output.write(converted.data)
                prebuild_webp_thumbnails(converted.data, thumbnail_root=path.parent/'_thumbs', source_file_name=name)
            image_urls[index] = '/storage/model-files/' + name
        changes = execute_rows(db, actor, plan, plan_hash, image_urls)
        checks = verify_after(expected, capture(db), changes)
        result = {'plan_sha256': plan_hash, 'backup': backup, 'changes': changes, 'checks': checks,
                  'new_receipt_images': len(image_urls), 'applied_at': datetime.now().isoformat()}
        audit = log_action(db, None, 'workbook_reconcile_done', 'StockBatch', None, new_value=result)
        result['audit_id'] = audit.id
        Session.commit(db)
        return result
