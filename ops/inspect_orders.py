import json
from sqlalchemy import text
from app.db.session import SessionLocal

with SessionLocal() as db:
    db.execute(text("SET TRANSACTION READ ONLY"))
    queries = {
        "revision": "select version_num from alembic_version",
        "orders": """select p.id,p.po_no,p.status,p.purchase_request_id,
        s.name supplier,p.expected_date,l.id line_id,l.item_id,i.name item,
        l.ordered_quantity,l.received_quantity,l.photo_url,
        r.sales_order_id,r.production_order_id
        from purchase_orders p join purchase_order_lines l on l.purchase_order_id=p.id
        left join suppliers s on s.id=p.supplier_id left join items i on i.id=l.item_id
        left join purchase_requests r on r.id=p.purchase_request_id
        order by p.po_no,l.id""",
        "foreign_keys": """select conrelid::regclass::text source, pg_get_constraintdef(oid) definition
        from pg_constraint where contype='f' and confrelid in
        ('purchase_orders'::regclass,'purchase_order_lines'::regclass)""",
        "reference_columns": """select table_name,column_name from information_schema.columns
        where table_schema='public' and (column_name like '%purchase%' or column_name like '%reference%')
        order by table_name,column_name""",
    }
    print(json.dumps({key:[dict(r) for r in db.execute(text(q)).mappings()] for key,q in queries.items()},default=str,indent=2))
