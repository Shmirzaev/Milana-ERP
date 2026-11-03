"""Read-only process-QR resolution around legacy size deletion, no QR issuance."""
from app.models.catalog import models_service as service
from app.schemas import Model, ModelSize
from app.tests.conftest import TestSessionLocal
from app.tests.test_modelsize_create_operation import size_case  # noqa: F401


def test_family_resolution_transitions_after_deletes(size_case):
    actor_id = size_case['actors']['standard']
    from app.schemas import User
    with TestSessionLocal.begin() as db:
        family = [Model(code=f'DELETE-QR-{i}', name='QR family', catalog_scope='standard', factory_code='MIL', details_json={'general': {'model_no': 'DELETE-QR'}}) for i in range(3)]
        db.add_all(family); db.flush()
        rows = [ModelSize(model_id=family[1].id, size='48'), ModelSize(model_id=family[2].id, size='50')]
        db.add_all(rows); db.flush()
        mids, ids = [m.id for m in family], [r.id for r in rows]
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        resolve = lambda mid: service.get_process_qr_model_sizes(actor, db, mid)
        assert resolve(mids[0]) == {'model_id': mids[0], 'sizes': [], 'resolution': 'conflict'}
        assert resolve(mids[1]) == {'model_id': mids[1], 'sizes': ['48'], 'resolution': 'own'}
        service.delete_size(actor, db, mids[2], ids[1])
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        assert service.get_process_qr_model_sizes(actor, db, mids[0]) == {'model_id': mids[0], 'sizes': ['48'], 'resolution': 'inherited'}
        assert service.get_process_qr_model_sizes(actor, db, mids[2]) == {'model_id': mids[2], 'sizes': ['48'], 'resolution': 'inherited'}
        service.delete_size(actor, db, mids[1], ids[0])
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        for mid in mids:
            assert service.get_process_qr_model_sizes(actor, db, mid) == {'model_id': mid, 'sizes': [], 'resolution': 'missing'}
