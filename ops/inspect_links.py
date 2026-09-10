import json
from sqlalchemy import text
from app.db.session import SessionLocal

numbers = list(range(3,14))+list(range(15,23))+list(range(25,32))+[33,34,35,40,47]
names = [f"PUR-{n:04d}" for n in numbers]
with SessionLocal() as db:
    db.execute(text("SET TRANSACTION READ ONLY"))
    ids = list(db.execute(text("select id from purchase_orders where po_no=ANY(:names)"),{"names":names}).scalars())
    lines = list(db.execute(text("select id from purchase_order_lines where purchase_order_id=ANY(:ids)"),{"ids":ids}).scalars())
    queries = {
        "movements": "select * from stock_movements where reference_type ilike '%purchase%' and reference_id=ANY(:ids)",
        "batches": "select id,batch_no,internal_batch_no,order_no,quantity from stock_batches where internal_batch_no=ANY(:names) or batch_no=ANY(:names) or order_no=ANY(:names)",
        "aliases": "select * from business_order_aliases where canonical_reference=ANY(:names)",
        "tasks": "select id,entity_type,entity_id from tasks where entity_type ilike '%purchase%' and entity_id=ANY(:ids)",
    }
    params={"names":names+[f"PUR-2026-{n:06d}" for n in numbers],"ids":sorted(set(ids+lines))}
    result={key:[dict(r) for r in db.execute(text(q),params).mappings()] for key,q in queries.items()}
    result["target_count"]=len(ids)
    print(json.dumps(result,default=str,indent=2))
