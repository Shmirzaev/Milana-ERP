import pytest

from app.db.session import SessionLocal
from app.models import Bundle, CuttingRecord, ProductionBatch, StockBatch, WorkOrder
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


def read_passport(client, headers, payload):
    result = client.get(f"/api/cutting-passports/{payload['cutting_passport_id']}", headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def test_later_passports_reopen_cutting_and_stay_visible_until_all_confirmed(client, auth_headers, passport_cutting):
    fabrics, order, work, payload = passport_cutting
    first = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert first.status_code == 201, first.text
    with SessionLocal() as db:
        assert db.get(WorkOrder, work['id']).status == 'completed'
    later = []
    for number in ('SECOND', 'THIRD'):
        passport = client.post('/api/cutting-passports', headers=auth_headers, json={
            'passport_no': number, 'production_order_id': order['id'],
            'date': '2026-10-07T00:00:00Z', 'pieces': 10,
        })
        assert passport.status_code == 201, passport.text
        later.append(passport.json())
    assert [row['nastil_name'] for row in later] == ['Nastil 2', 'Nastil 3']
    with SessionLocal() as db:
        cutting = db.get(WorkOrder, work['id'])
        assert cutting.status == 'in_progress' and cutting.end_time is None
        assert cutting.passed_qty == 10
        assert db.query(Bundle).filter_by(production_order_id=order['id']).count() == 1
        assert [float(db.get(StockBatch, row['id']).quantity) for row in fabrics] == [93.5, 93.5]
    for index, passport in enumerate(later):
        inbox = client.get('/api/inbox?dept=CUT', headers=auth_headers)
        assert inbox.status_code == 200, inbox.text
        assert any(row['id'] == work['id'] for row in inbox.json()['in_progress_work_orders'])
        manual = {**payload, 'cutting_passport_id': None, 'use_passport_materials': False,
                  'production_batch_id': passport['production_batch_id'],
                  'defer_material_usage': True, 'input_quantity': 0}
        saved = client.post('/api/cutting/records', headers=auth_headers, json=manual)
        assert saved.status_code == 201, saved.text
        with SessionLocal() as db:
            assert db.get(WorkOrder, work['id']).status == ('completed' if index == 1 else 'in_progress')
            assert db.get(WorkOrder, work['id']).passed_qty == 20 + index * 10


def test_save_and_repeat_update_sync_one_nastil_without_crediting_output(client, auth_headers, passport_cutting):
    fabrics, order, work, payload = passport_cutting
    passport = read_passport(client, auth_headers, payload)
    assert passport['nastil_name'] == 'Nastil 1'
    bid = passport['production_batch_id']
    passport['materials'][0]['pieces'] = 13
    for _ in range(2):
        response = client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport)
        assert response.status_code == 200, response.text
        assert response.json()['production_batch_id'] == bid
    with SessionLocal() as db:
        batch = db.get(ProductionBatch, bid)
        assert (batch.planned_quantity, batch.passport_actual_quantity) == (13, 13)
        assert db.query(ProductionBatch).filter_by(production_order_id=order['id']).count() == 1
        assert db.query(CuttingRecord).filter_by(work_order_id=work['id']).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=order['id']).count() == 0
        assert db.get(WorkOrder, work['id']).passed_qty == 0
        assert [float(db.get(StockBatch, row['id']).quantity) for row in fabrics] == [100, 100]
    progress = client.get(f"/api/work-orders/{work['id']}/cutting-batch-progress", headers=auth_headers).json()
    assert progress['items'][0]['passport_actual_quantity'] == 13
    passport['passport_no'] = 'SECOND'
    second = client.post('/api/cutting-passports', headers=auth_headers, json=passport)
    assert second.status_code == 201, second.text
    assert second.json()['nastil_name'] == 'Nastil 2'


def test_confirmed_passport_preserves_bundle_stock_and_guards_later_count_changes(client, auth_headers, passport_cutting):
    fabrics, order, work, payload = passport_cutting
    response = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    passport = read_passport(client, auth_headers, payload)
    assert passport['used_for_cutting']
    unchanged = client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport)
    assert unchanged.status_code == 200, unchanged.text
    passport['materials'][0]['pieces'] = 11
    changed = client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport)
    assert changed.status_code == 409, changed.text
    with SessionLocal() as db:
        assert db.get(WorkOrder, work['id']).passed_qty == 10
        assert db.get(ProductionBatch, payload['production_batch_id']).passport_actual_quantity == 10
        assert db.query(Bundle).filter_by(production_order_id=order['id']).one().quantity == 10
        assert [float(db.get(StockBatch, row['id']).quantity) for row in fabrics] == [93.5, 93.5]


def test_manual_entry_remains_available_and_cannot_be_counted_again_as_passport(client, auth_headers, passport_cutting):
    _, _, _, payload = passport_cutting
    manual = {**payload, 'cutting_passport_id': None, 'use_passport_materials': False,
              'defer_material_usage': True, 'input_quantity': 0}
    response = client.post('/api/cutting/records', headers=auth_headers, json=manual)
    assert response.status_code == 201, response.text
    passport = read_passport(client, auth_headers, payload)
    assert passport['used_for_cutting']
    again = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert again.status_code in (400, 409), again.text


def test_passport_updates_keep_manual_nastil_name_and_factory_authorization(client, auth_headers, passport_cutting):
    from app.tests.test_passport_get_scope import _actor, _headers
    _, _, _, payload = passport_cutting
    passport = read_passport(client, auth_headers, payload)
    with SessionLocal() as db:
        db.get(ProductionBatch, passport['production_batch_id']).name = 'Morning layup'
        db.commit()
    passport['materials'][0]['pieces'] = 12
    denied = client.put(f"/api/cutting-passports/{passport['id']}", headers=_headers(_actor('ECO'), 'ECO'), json=passport)
    assert denied.status_code == 403, denied.text
    with SessionLocal() as db:
        assert db.get(ProductionBatch, passport['production_batch_id']).passport_actual_quantity == 10
    saved = client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport)
    assert saved.status_code == 200, saved.text
    assert saved.json()['nastil_name'] == 'Morning layup'


def test_passport_cannot_be_applied_to_a_different_nastil(client, auth_headers, passport_cutting):
    _, order, _, payload = passport_cutting
    with SessionLocal() as db:
        other = ProductionBatch(production_order_id=order['id'], batch_index=2, batch_no='manual-2', name='Manual', planned_quantity=10)
        db.add(other)
        db.commit()
        payload['production_batch_id'] = other.id
    response = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert response.status_code == 409, response.text


def test_old_passport_with_unlinked_manual_production_is_not_counted_as_a_new_nastil(client, auth_headers, passport_cutting):
    _, order, work, payload = passport_cutting
    response = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        batch = db.get(ProductionBatch, payload['production_batch_id'])
        batch.cutting_passport_id = None
        batch.passport_actual_quantity = None
        db.get(CuttingRecord, response.json()['id']).cutting_passport_id = None
        db.get(WorkOrder, work['id']).status = 'in_progress'
        db.commit()
    passport = read_passport(client, auth_headers, payload)
    saved = client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport)
    assert saved.status_code == 200, saved.text
    assert saved.json()['production_batch_id'] is None
    with SessionLocal() as db:
        assert db.query(ProductionBatch).filter_by(production_order_id=order['id']).count() == 1


def test_direct_bundle_creation_also_locks_the_passport_nastil(client, auth_headers, passport_cutting):
    _, order, _, payload = passport_cutting
    response = client.post('/api/bundles', headers=auth_headers, json={
        'production_order_id': order['id'], 'production_batch_id': payload['production_batch_id'],
        'model_id': 1, 'color': 'white', 'size': '46', 'quantity': 10,
    })
    assert response.status_code == 201, response.text
    passport = read_passport(client, auth_headers, payload)
    assert passport['used_for_cutting']
    listed = client.get(f"/api/cutting-passports?production_order_id={order['id']}", headers=auth_headers)
    assert listed.json()[0]['used_for_cutting']
    passport['materials'][0]['pieces'] = 11
    assert client.put(f"/api/cutting-passports/{passport['id']}", headers=auth_headers, json=passport).status_code == 409
    assert client.delete(f"/api/cutting-passports/{passport['id']}", headers=auth_headers).status_code == 409
    assert client.post('/api/cutting/records', headers=auth_headers, json=payload).status_code == 409


@pytest.mark.parametrize('factory,name', [('MIL', 'Milana'), ('BST', 'Besttex'), ('ECO', 'Eco Cotton')])
def test_uzbek_bundle_labels_use_each_bundles_sewing_destination(client, auth_headers, passport_cutting, factory, name):
    _, _, _, payload = passport_cutting
    response = client.post('/api/cutting/records', headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    bundle_id = response.json()['bundles'][0]['id']
    with SessionLocal() as db:
        db.get(Bundle, bundle_id).sewing_factory_code = factory
        db.commit()
    for path in (f'/api/bundles/{bundle_id}/label', f'/api/bundles/label-sheet/by-ids?ids={bundle_id}'):
        label = client.get(path, headers=auth_headers)
        assert label.status_code == 200, label.text
        assert "lang='uz'" in label.text
        assert f'<b>Tikuv fabrikasi</b><span>{name}</span>' in label.text
        assert '<b>Bog‘lam</b>' in label.text and '<b>Nastil</b>' in label.text
        assert '>Chop etish</button>' in label.text
        assert '<b>Bundle</b>' not in label.text and '<b>Qty</b>' not in label.text
