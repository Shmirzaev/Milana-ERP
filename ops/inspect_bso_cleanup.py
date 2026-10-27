"""Read-only dependency inventory for the owner's BSO cleanup."""
import json
from collections import defaultdict

from sqlalchemy import text

from app.db.session import SessionLocal

FK_SQL = """select tc.table_name child,kcu.column_name col,ccu.table_name parent,
ccu.column_name pcol from information_schema.table_constraints tc
join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name
and tc.constraint_schema=kcu.constraint_schema
join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
and ccu.constraint_schema=tc.constraint_schema
where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'"""

with SessionLocal() as db:
    db.execute(text('SET TRANSACTION READ ONLY'))
    db.execute(text("SET LOCAL statement_timeout='45s'"))
    def rows(sql, **params):
        return [dict(r) for r in db.execute(text(sql), params).mappings()]
    links = rows(FK_SQL)
    groups = rows('select id,order_no,status from branded_planning_orders order by id')
    targets = defaultdict(set)
    targets['branded_planning_orders'] = {r['id'] for r in groups if r['order_no'].isdigit() and 1 <= int(r['order_no']) <= 38}
    pictured = rows("select id from production_orders where planning_order_id=43 and production_no in ('PO-0270','PO-0271','PO-0272')")
    targets['production_orders'] = {r['id'] for r in pictured}
    protected = {'models','sales_orders','sales_order_items','stock_batches','items','users','employees','payroll_periods','shipments','invoices','payments','price_calculation_requests','audit_logs','stock_movements'}
    blocked = {}
    for _ in range(30):
        changed = False
        for edge in links:
            if not targets.get(edge['parent']):
                continue
            assert edge['pcol'] == 'id'
            found = {r['id'] for r in rows(f'SELECT id FROM "{edge["child"]}" WHERE "{edge["col"]}"=ANY(:ids)', ids=sorted(targets[edge['parent']]))}
            if edge['child'] in protected:
                if found:
                    blocked[edge['child']+':'+edge['col']] = sorted(found)
                continue
            new = found - targets[edge['child']]
            if new:
                targets[edge['child']].update(new)
                changed = True
        if not changed:
            break
    productions = rows('select id,production_no,planning_order_id,sales_order_id,status from production_orders where id=ANY(:ids) order by id', ids=sorted(targets['production_orders']))
    columns = rows("select table_name,column_name,data_type from information_schema.columns where table_schema='public' and (column_name ~ '(ref|order|batch|package|bundle|passport|record|source|entity|payload|data|link)' or data_type in ('json','jsonb')) order by table_name,ordinal_position")
    evidence = {}
    for table in ('payroll_records','packages','finished_goods_stock','material_reservations','warehouse_stocktake_rows'):
        if targets.get(table):
            evidence[table] = rows(f'SELECT * FROM "{table}" WHERE id=ANY(:ids) ORDER BY id', ids=sorted(targets[table]))
    print(json.dumps(dict(groups=groups, productions=productions, targets={k:sorted(v) for k,v in targets.items() if v}, counts={k:len(v) for k,v in targets.items() if v}, blocked=blocked, links=links, columns=columns, evidence=evidence, revision=rows('select version_num from alembic_version')), default=str))
