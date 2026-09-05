"""Read-only photo isolation and complete image-relation evidence."""
import hashlib
import json
from sqlalchemy import text
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models import Model, ModelBOM
from app.api.routes.catalog import _fabric_picture_url_for_model, _variant_picture_url_for_model


with SessionLocal() as db:
    assert db.execute(text('select current_database()')).scalar() == 'erp'
    rows = db.query(Model).options(selectinload(Model.images), selectinload(Model.bom).selectinload(ModelBOM.item)).order_by(Model.id).all()
    images = [dict(r._mapping) for r in db.execute(text('SELECT id, model_id, file_url, file_name, content_type, image_type, is_primary, md5(file_data) AS data_md5 FROM model_images ORDER BY id'))]
    result = {
        'models': [{'id': m.id, 'code': m.code, 'general': (m.details_json or {}).get('general'),
                    'independent_variant_url': _fabric_picture_url_for_model(m),
                    'effective_variant_url': _variant_picture_url_for_model(m)} for m in rows],
        'images': images,
        'model_data_fingerprint': hashlib.sha256(str([list(r) for r in db.execute(text('SELECT id, md5(row_to_json(models)::text) FROM models ORDER BY id'))]).encode()).hexdigest(),
        'bom_fingerprint': hashlib.sha256(str([list(r) for r in db.execute(text('SELECT id, md5(row_to_json(model_bom)::text) FROM model_bom ORDER BY id'))]).encode()).hexdigest(),
    }
    print(json.dumps(result, ensure_ascii=False, default=str))
