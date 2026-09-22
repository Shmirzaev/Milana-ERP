"""One-off, reviewed production cleanup. Default is read-only; apply needs an exact plan.

Run with PYTHONPATH=/app:/app/backend. The caller verifies a fresh full database
backup before apply. This is an operational script, not a startup migration.
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.audit import log_action

ALLOWED = set('''branded_planning_orders production_orders production_batches
production_order_items production_order_materials work_orders cutting_passports
cutting_records cutting_material_usages cutting_beika_material_usages bundles
bundle_scan_logs printing_records sewing_records sewing_assignments sewing_daily_reports
sewing_replacement_requests packaging_records packaging_receipts packages package_items
package_batch_allocations package_scan_logs package_barcode_aliases finished_goods_stock
waste_records payroll_qr_labels payroll_records material_reservations quality_checks
manual_accessory_issues package_change_requests warehouse_stocktake_rows
business_order_aliases notifications tasks idempotency_records'''.split())
SOFT = {'package_change_requests': ('package_id', 'packages'),
        'warehouse_stocktake_rows': ('package_id', 'packages')}
FK_SQL = """select tc.table_name child,kcu.column_name col,ccu.table_name parent,
ccu.column_name pcol from information_schema.table_constraints tc
join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name
and tc.constraint_schema=kcu.constraint_schema
join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
and ccu.constraint_schema=tc.constraint_schema
where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'"""


def rows(db, sql, **params):
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def ids(db, table, col, values):
    if not values:
        return set()
    return set(db.execute(text(f'SELECT id FROM "{table}" WHERE "{col}"=ANY(:ids)'),
                          {'ids': sorted(values)}).scalars())


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def plan(db, links):
    targets = defaultdict(set)
    groups = rows(db, "select id,order_no from branded_planning_orders where order_no ~ '^[0-9]+$' and order_no::int between 1 and 31 order by order_no")
    assert [r['order_no'] for r in groups] == [f'{n:04}' for n in range(1, 32)], 'BSOrder range changed'
    targets['branded_planning_orders'] = {r['id'] for r in groups}
    kept = rows(db, "select id,order_no from branded_planning_orders where order_no in ('0032','0033') order by order_no")
    assert len(kept) == 2, 'Required retained groups missing'
    for _ in range(30):
        changed = False
        for edge in links:
            if not targets.get(edge['parent']):
                continue
            assert edge['pcol'] == 'id'
            found = ids(db, edge['child'], edge['col'], targets[edge['parent']])
            assert not found or edge['child'] in ALLOWED, f'Unreviewed dependency: {edge["child"]}'
            new = found - targets[edge['child']]
            if new:
                targets[edge['child']].update(new)
                changed = True
        if not changed:
            break
    else:
        raise RuntimeError('Dependency traversal did not converge')
    for table, (col, parent) in SOFT.items():
        targets[table].update(ids(db, table, col, targets[parent]))
    # A shared child may never pull another workflow into this deletion.
    for edge in links:
        if not targets.get(edge['child']) or not targets.get(edge['parent']):
            continue
        mixed = rows(db, f'SELECT id FROM "{edge["child"]}" WHERE id=ANY(:child) AND "{edge["col"]}" IS NOT NULL AND NOT ("{edge["col"]}"=ANY(:parent))',
                     child=sorted(targets[edge['child']]), parent=sorted(targets[edge['parent']]))
        assert not mixed, f'Shared retained-workflow reference: {edge}'
    productions = rows(db, 'select id,production_no,sales_order_id from production_orders where id=ANY(:ids) order by id', ids=sorted(targets['production_orders']))
    assert len(productions) == 73 and all(r['sales_order_id'] is None for r in productions)
    aliases = rows(db, "select id,reference,namespace from business_order_aliases where (namespace in ('PO','USL','PUBLIC_PO') and entity_id=ANY(:po)) or (namespace='BND' and entity_id=ANY(:bnd))", po=sorted(targets['production_orders']), bnd=sorted(targets['bundles']))
    targets['business_order_aliases'] = {r['id'] for r in aliases}
    references = {r['production_no'] for r in productions}
    references.update(r['reference'] for r in aliases if r['namespace'] != 'BND')
    # Full authoritative references only; bare numeric manual references are not identities.
    references = {r for r in references if re.match(r'^(PO|SO|USL)-', r)}
    for table in ('payroll_records','payroll_qr_labels'):
        extra = rows(db, f'SELECT id FROM {table} WHERE production_no=ANY(:refs) OR sales_order_no=ANY(:refs)', refs=sorted(references))
        assert all(r['id'] in targets[table] for r in extra), f'Review unlinked {table} dependencies'
    extra_reports = rows(db, 'select id,production_order_id from sewing_daily_reports where order_no=ANY(:refs) or sales_order_no=ANY(:refs)', refs=sorted(references))
    assert all(r['production_order_id'] is None or r['production_order_id'] in targets['production_orders'] for r in extra_reports)
    targets['sewing_daily_reports'].update(r['id'] for r in extra_reports)
    extra_passports = rows(db, 'select id,production_order_id from cutting_passports where order_no=ANY(:refs)', refs=sorted(references))
    assert all(r['production_order_id'] is None or r['production_order_id'] in targets['production_orders'] for r in extra_passports)
    assert all(r['id'] in targets['cutting_passports'] for r in extra_passports), 'Review unlinked passport dependencies'
    bundle_refs = {r['bundle_no'] for r in rows(db, 'select bundle_no from bundles where id=ANY(:ids)', ids=sorted(targets['bundles']))}
    package_refs = {r['package_no'] for r in rows(db, 'select package_no from packages where id=ANY(:ids)', ids=sorted(targets['packages']))}
    reference_re = re.compile(r'(?<![A-Za-z0-9-])(?:'+'|'.join(re.escape(r) for r in sorted(references | bundle_refs | package_refs, key=len, reverse=True))+r')(?![A-Za-z0-9-])')
    routes = {'work-orders': 'work_orders', 'production-orders': 'production_orders', 'bundles': 'bundles', 'packages': 'packages', 'cutting-passports': 'cutting_passports'}
    for row in rows(db, 'select id,title,message,link from notifications'):
        link_match = re.search(r'/(work-orders|production-orders|bundles|packages|cutting-passports)/(\d+)(?:/|\?|#|$)', row['link'] or '')
        if (link_match and int(link_match[2]) in targets[routes[link_match[1]]]) or reference_re.search((row['title'] or '')+' '+(row['message'] or '')):
            targets['notifications'].add(row['id'])
    entity_tables = {'ProductionOrder':'production_orders','WorkOrder':'work_orders','Bundle':'bundles','Package':'packages','CuttingPassport':'cutting_passports','BrandedPlanningOrder':'branded_planning_orders'}
    for row in rows(db, 'select id,entity_type,entity_id from tasks'):
        table = entity_tables.get(row['entity_type'])
        if table and row['entity_id'] in targets[table]:
            targets['tasks'].add(row['id'])
    identity_keys = {'production_order_id':'production_orders','work_order_id':'work_orders','production_batch_id':'production_batches','package_id':'packages','bundle_id':'bundles','cutting_passport_id':'cutting_passports'}
    def linked_payload(obj):
        if isinstance(obj, dict):
            return any((key in identity_keys and isinstance(value,int) and value in targets[identity_keys[key]]) or linked_payload(value) for key,value in obj.items())
        if isinstance(obj, list):
            return any(linked_payload(value) for value in obj)
        return isinstance(obj,str) and bool(reference_re.search(obj))
    for row in rows(db, 'select id,scope,response_json from idempotency_records'):
        if linked_payload(row['response_json']):
            targets['idempotency_records'].add(row['id'])
    # Do not erase wages that are payable or belong to an accounting period.
    wages = rows(db, 'select id,status,payroll_period_id from payroll_records where id=ANY(:ids)', ids=sorted(targets['payroll_records']))
    assert all(r['status']=='voided' and r['payroll_period_id'] is None for r in wages)
    # Physical material consumption stays in the stock ledger, with an explicit
    # historical reference type rather than a link to a deleted cutting record.
    movements = rows(db, "select id,reference_type,reference_id from stock_movements where reference_type in ('CuttingRecord','CuttingCorrection','CuttingRollback') and reference_id=ANY(:ids) order by id", ids=sorted(targets['cutting_records']))
    batches = rows(db, 'select id,order_no from stock_batches where order_no=ANY(:refs) order by id', refs=sorted(references))
    media = []
    for table in ('bundles','packages'):
        for row in rows(db, f'SELECT id,qr_code_url FROM {table} WHERE id=ANY(:ids)', ids=sorted(targets[table])):
            if row['qr_code_url'] and not row['qr_code_url'].startswith('/api/'):
                media.append({'table':table, **row})
    filenames = {row['qr_code_url'].removeprefix('/storage/barcodes/') for row in media}
    historic_bundle_refs = bundle_refs | {r['reference'] for r in aliases if r['namespace']=='BND'}
    for prefix, refs in (('bundle',historic_bundle_refs),('package',package_refs)):
        for ref in refs:
            assert re.fullmatch(r'[A-Za-z0-9_-]+',ref), 'Unsafe barcode filename'
            filenames.update(f'{prefix}_{kind}_{ref}.png' for kind in ('qr','bc'))
    for table in ('bundles','packages'):
        shared = rows(db, f'SELECT id,qr_code_url FROM {table} WHERE NOT (id=ANY(:ids)) AND qr_code_url=ANY(:urls)', ids=sorted(targets[table]), urls=[r['qr_code_url'] for r in media])
        assert not shared, 'QR media shared with a retained workflow'
    targets = {k:sorted(v) for k,v in targets.items() if v}
    return {'groups':groups, 'retained_groups':kept, 'production_orders':productions,
            'targets':targets,'counts':{k:len(v) for k,v in targets.items()},
            'stock_movement_references':movements,'stock_batch_references':batches,'media':media,
            'barcode_filenames':sorted(filenames)}


def fingerprint(db, table, excluded, omit=()):
    projection = 'to_jsonb(t)'+''.join("-'"+col+"'" for col in omit)
    return rows(db, f"SELECT count(*) n, md5(coalesce(string_agg(({projection})::text,E'\\n' ORDER BY id),'')) digest FROM {table} t WHERE NOT (id=ANY(:ids))", ids=excluded)[0]


def execute(db, planned, links, backup):
    targets = planned['targets']
    before = {table:fingerprint(db,table,selected) for table,selected in targets.items()}
    before['stock_batches'] = fingerprint(db,'stock_batches',[],('order_no',))
    before['stock_movements'] = fingerprint(db,'stock_movements',[],('reference_id','reference_type'))
    pending = set(targets)
    order = []
    while pending:
        leaves = sorted(table for table in pending if not any(e['parent']==table and e['child'] in pending and e['child']!=table for e in links))
        assert leaves, 'Cyclic dependency requires explicit review'
        order.extend(leaves)
        pending.difference_update(leaves)
    for table in order:
        result = db.execute(text(f'DELETE FROM "{table}" WHERE id=ANY(:ids)'), {'ids':targets[table]})
        assert result.rowcount == len(targets[table]), table
    for row in planned['stock_movement_references']:
        db.execute(text("UPDATE stock_movements SET reference_type='DeletedProductionWorkflow',reference_id=NULL WHERE id=:id"), {'id':row['id']})
    for row in planned['stock_batch_references']:
        db.execute(text('UPDATE stock_batches SET order_no=NULL WHERE id=:id'), {'id':row['id']})
    for table, expected in before.items():
        omit = ('order_no',) if table=='stock_batches' else ('reference_id','reference_type') if table=='stock_movements' else ()
        assert fingerprint(db,table,[],omit) == expected, f'Retained rows changed: {table}'
    for table, selected in targets.items():
        assert not ids(db,table,'id',selected), table
    retained = rows(db, "select b.order_no,count(p.id) productions from branded_planning_orders b left join production_orders p on p.planning_order_id=b.id where b.order_no in ('0032','0033') group by b.order_no order by b.order_no")
    assert retained == [{'order_no':'0032','productions':9},{'order_no':'0033','productions':14}]
    entry = log_action(db,None,'delete_bs_orders_before_0032','BrandedPlanningOrder',
                       old_value={'plan_sha256':signature(planned),'counts':planned['counts'],'groups':planned['groups'],
                                  'stock_movement_references':planned['stock_movement_references'],
                                  'stock_batch_references':planned['stock_batch_references']},
                       new_value={'retained':retained,'backup':backup,'physical_material_balances_preserved':True})
    return {'deleted':planned['counts'],'retained':retained,'audit_id':entry.id,
            'retained_fingerprints':before,'stock_movement_references_cleared':len(planned['stock_movement_references']),
            'stock_batch_references_cleared':len(planned['stock_batch_references'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan-file',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    path = Path(args.plan_file)
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='90s'"))
        if not args.apply:
            db.execute(text('SET TRANSACTION READ ONLY'))
        links = rows(db,FK_SQL)
        if args.apply:
            assert args.backup and re.fullmatch(r'/opt/milana-erp/shared/backups/milana_erp_pre_\d{8}_\d{6}\.dump',args.backup)
            lock_tables = ALLOWED | {'stock_batches','stock_movements','audit_logs'}
            lock_tables.update(e['child'] for e in links if e['parent'] in ALLOWED)
            db.execute(text('LOCK TABLE '+','.join('"'+t+'"' for t in sorted(lock_tables))+' IN SHARE ROW EXCLUSIVE MODE'))
        planned = plan(db,links)
        if not args.apply:
            path.write_text(json.dumps(planned,indent=2,sort_keys=True),encoding='utf-8')
            print(json.dumps({'plan_sha256':signature(planned),'counts':planned['counts'],
                              'stock_references':len(planned['stock_movement_references']),
                              'batch_references':len(planned['stock_batch_references']),'media':len(planned['media'])}))
            return
        assert planned == json.loads(path.read_text()), 'Plan changed: review again before apply'
        result = execute(db,planned,links,args.backup)
        db.commit()
        print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
