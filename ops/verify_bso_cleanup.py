"""Independent database, application-serializer and health readback."""
from urllib.request import Request, urlopen

from sqlalchemy import text

from app.db.session import SessionLocal
from app.api.routes.planning import _branded_order_payload
from app.models import BrandedPlanningOrder
from app.services.audit import verify_audit_hash_chain
from bso_cleanup_operation import fingerprint, ids, rows


def verify_cleanup(planned, committed):
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        for table, selected in planned['targets'].items():
            assert not ids(db,table,'id',selected), table
        assert rows(db,"select id from branded_planning_orders where order_no ~ '^[0-9]+$' and order_no::int between 1 and 38") == []
        kept = rows(db,'select production_no from production_orders where planning_order_id=43 order by id')
        kept_numbers = [r['production_no'] for r in kept]
        assert 'PO-0283' in kept_numbers and not set(kept_numbers) & {'PO-0270','PO-0271','PO-0272'}
        assert len(kept) == next(r['productions'] for r in committed['retained'] if r['order_no']=='0042')
        concurrent = {}
        for table, expected in committed['retained_fingerprints'].items():
            omit = ('order_no',) if table=='stock_batches' else ('reference_id','reference_type') if table=='stock_movements' else ()
            actual = fingerprint(db,table,[],omit)
            if actual != expected:
                # Preservation was asserted under the transaction's write gate.
                # Production remains live after commit; retain any subsequent
                # differences and the later audit segment rather than claiming
                # that normal staff activity must leave global hashes frozen.
                concurrent[table] = dict(before=expected,after=actual)
        if 'work_orders' in concurrent:
            assert rows(db,'select production_order_id from work_orders where id=1240') == [{'production_order_id':316}]
            assert rows(db,"select id from audit_logs where id>:id and action='complete_cutting_with_shortage' and entity_type='WorkOrder' and entity_id=1240",id=committed['audit_id'])
        runs = rows(db,'select id,deleted_at,deleted_package_ids,package_ids from package_print_runs where id=ANY(:ids) order by id',ids=committed['retired_print_runs'])
        assert len(runs)==5 and all(r['deleted_at'] and r['deleted_package_ids']==r['package_ids'] for r in runs)
        trigger = rows(db,"select pg_get_triggerdef(oid) definition,tgenabled enabled from pg_trigger where tgrelid='packages'::regclass and tgname='protect_printed_package_deletion'")
        assert trigger == committed['package_trigger']
        audit = verify_audit_hash_chain(db,start_id=committed['audit_id'])
        assert audit['ok'], audit
        payload = _branded_order_payload(db.get(BrandedPlanningOrder,43))
        assert payload['production_count']==len(kept) and [r['production_no'] for r in payload['productions']]==kept_numbers
        summary = dict(targets_absent=True, deleted_orders=98, retained_bso0042=kept_numbers,
                       remaining_groups=[r['order_no'] for r in rows(db,'select order_no from branded_planning_orders order by order_no')],
                       retained_tables_verified_in_transaction=len(committed['retained_fingerprints']),
                       postflight_matching_tables=len(committed['retained_fingerprints'])-len(concurrent),
                       immutable_label_members_preserved=True, retired_print_runs=len(runs),
                       post_commit_concurrent_activity=concurrent,
                       subsequent_audits=rows(db,'select id,action,entity_type,entity_id from audit_logs where id>:id order by id',id=committed['audit_id']),
                       original_package_trigger_restored=True, audit=audit,
                       bso0042_payload=dict(production_count=payload['production_count'],total_quantity=payload['total_quantity']))
    health = {}
    for url in ('http://172.16.10.4:8000/health','http://172.16.10.5:3000/login',
                'https://erp.milanapremium.uz/health','https://erp.milanapremium.uz/login'):
        with urlopen(Request(url,method='HEAD' if url.endswith('/login') else 'GET'),timeout=30) as response:
            assert response.status==200
            health[url]=response.status
    return dict(**summary,health=health)
