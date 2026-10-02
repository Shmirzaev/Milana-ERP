"""Read-only, repeatable fabric inventory evidence; no credentials in output."""
import json
import hashlib
from pathlib import Path
from sqlalchemy import text
from app.db.session import SessionLocal
from app.core.config import settings

def capture(db):
    queries = {
        "snapshot_time": "SELECT current_timestamp AS captured_at",
        "revision": "SELECT version_num FROM alembic_version",
        "warehouses": "SELECT id,name,type FROM warehouses ORDER BY id",
        "suppliers": "SELECT id,name,is_active FROM suppliers ORDER BY id",
        "items": "SELECT * FROM items WHERE category IN ('fabric','semi_finished') ORDER BY id",
        "batches": "SELECT b.* FROM stock_batches b JOIN items i ON i.id=b.item_id WHERE i.category IN ('fabric','semi_finished') ORDER BY b.id",
        "movements": "SELECT m.* FROM stock_movements m JOIN items i ON i.id=m.item_id WHERE i.category IN ('fabric','semi_finished') ORDER BY m.id",
        "reservations": "SELECT r.* FROM material_reservations r JOIN items i ON i.id=r.item_id WHERE i.category IN ('fabric','semi_finished') ORDER BY r.id",
        "batch_references": "SELECT tc.table_name,kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.constraint_schema=kcu.constraint_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name AND ccu.constraint_schema=tc.constraint_schema WHERE tc.constraint_type='FOREIGN KEY' AND ccu.table_name='stock_batches' ORDER BY tc.table_name,kcu.column_name",
        "fabric_scans": "SELECT id,batch_id,roll_number,direction,department,report_date FROM fabric_scans ORDER BY id",
    }
    result = {key: [dict(row) for row in db.execute(text(query)).mappings()] for key, query in queries.items()}
    result['linked_rows'] = {}
    for ref in result['batch_references']:
        table, column = ref['table_name'], ref['column_name']
        if table in ('stock_movements', 'material_reservations'):
            continue
        assert table.replace('_','').isalnum() and column.replace('_','').isalnum()
        result['linked_rows'][table+':'+column] = [dict(row) for row in db.execute(text(f'SELECT * FROM "{table}" WHERE "{column}" IN (SELECT b.id FROM stock_batches b JOIN items i ON i.id=b.item_id WHERE i.category IN (\'fabric\',\'semi_finished\')) ORDER BY id')).mappings()]
    result['images'] = []
    for url in sorted({b['image_url'] for b in result['batches'] if b['image_url']}):
        if not url.startswith('/storage/') or '..' in url:
            continue
        p=Path(settings.MODEL_FILES_DIR)/Path(url).name
        if p.is_file():
            result['images'].append({'url':url,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return json.loads(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == '__main__':
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
        print(json.dumps(capture(db), ensure_ascii=False))
        db.rollback()
