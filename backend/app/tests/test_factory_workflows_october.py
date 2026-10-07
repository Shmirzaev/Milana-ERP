import json
import pytest
from decimal import Decimal
from uuid import uuid4

from app.models import Model, Package, PayrollRecord, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions
from app.tests.test_payroll_scan_allocations import issue, scan
from app.tests.test_usluga import _create_usluga_order, _login_eco
from app.tests.test_warehouse_pack_reservations import fixture_pack, reserve


def test_hb_hg_numbers_reserve_and_skip_occupied(client, auth_headers):
    for prefix, expected in [('HB', 17002), ('HG', 18002)]:
        response = client.get(f'/api/models/next-number?prefix={prefix}', headers=auth_headers)
        assert response.status_code == 200
        assert response.json()['model_no'] == f'{prefix}{expected}'
        payload = {'code': f'{prefix}{expected}', 'name': 'Numbering regression', 'automatic_model_prefix': prefix}
        first = client.post('/api/models', headers=auth_headers, json=payload)
        second = client.post('/api/models', headers=auth_headers, json=payload)
        assert first.status_code == second.status_code == 201
        assert first.json()['code'] == f'{prefix}{expected}'
        assert second.json()['code'] == f'{prefix}{expected + 1}'


def test_large_realistic_paid_operation_template_preserves_other_factory(client, auth_headers):
    rows = [{'id': str(i), 'code': f'OP-{i}', 'name': 'Tikuv операция ' * 9, 'rate': 1500, 'sewingFactory': 'besttex'} for i in range(250)]
    assert len(json.dumps(rows, ensure_ascii=False).encode()) > 65536
    with TestSessionLocal() as db:
        model = Model(code=f'OPS-{uuid4().hex}', name='Operations', details_json={'paid_operations': [
            {'id': 'eco', 'name': 'Eco', 'sewingFactory': 'eco_cotton'},
        ]})
        db.add(model); db.commit(); mid = model.id
    response = client.patch(f'/api/models/{mid}/paid-operations', headers=auth_headers,
                            json={'paid_operations': rows, 'sewing_factory': 'besttex'})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        stored = db.get(Model, mid).details_json['paid_operations']
        assert len(stored) == 251 and any(row['id'] == 'eco' for row in stored)


def test_scanned_reservation_is_read_only_and_revalidates_stock(client, auth_headers):
    pid, cid = fixture_pack()
    with TestSessionLocal() as db:
        barcode = db.get(Package, pid).barcode
    response = client.post('/api/warehouse-reservations/scan', headers=auth_headers, json={'code': barcode})
    assert response.status_code == 200 and response.json()['id'] == pid, response.text
    with TestSessionLocal() as db:
        assert db.get(Package, pid).status == 'received_in_storage'
    assert reserve(client, auth_headers, pid, cid).status_code == 200
    assert client.post('/api/warehouse-reservations/scan', headers=auth_headers, json={'code': barcode}).status_code == 409
    assert client.post('/api/warehouse-reservations/scan', json={'code': barcode}).status_code == 401


def test_split_prints_authoritative_labels_without_crediting_again(client, auth_headers):
    worker = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    original = scan(client, auth_headers, label, worker).json()['record']
    endpoint = f"/api/payroll/records/{original['id']}/split"
    result = client.post(endpoint, headers=auth_headers, json={'parts': [
        {'employee_id': worker['id'], 'quantity': 7}, {'employee_id': worker['id'], 'quantity': 13},
    ]})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        before = [(r.id, r.total_amount, r.status) for r in db.query(PayrollRecord).order_by(PayrollRecord.id)]
    for _ in range(2):
        printed = client.get(endpoint + '-labels/print', headers=auth_headers)
        assert printed.status_code == 200 and printed.text.count('<article>') == 2, printed.text
    with TestSessionLocal() as db:
        assert before == [(r.id, r.total_amount, r.status) for r in db.query(PayrollRecord).order_by(PayrollRecord.id)]
    assert sum(Decimal(r['total_amount']) for r in result.json()) == Decimal(original['total_amount'])
    other = _create_user_with_permissions(client, auth_headers, email=f'eco-{uuid4().hex}@example.com', permissions=['payroll.scan'], factory_code='ECO')
    assert client.get(endpoint + '-labels/print', headers=other).status_code == 404


def test_usluga_confirm_edit_complete_handover_without_packages(client):
    _login_eco(client)
    model, order = _create_usluga_order(client)
    works = {row['operation']: row['id'] for row in order['work_orders']}
    for role in ['main', 'secondary']:
        result = client.post('/api/cutting/records', json={
            'work_order_id': works['cutting'], 'model_bom_id': model[f'{role}_bom_id'],
            'input_quantity': 6, 'input_unit': 'kg', 'cut_pieces': 12 if role == 'main' else 0,
            'passed_pieces': 12 if role == 'main' else 0, 'waste_quantity': 0,
            'bundles': [{'color': 'Natural', 'size': 'M', 'quantity': 12, 'count': 1, 'next': 'sewing'}] if role == 'main' else [],
        })
        assert result.status_code == 201, result.text
        if role == 'main':
            bundle = result.json()['bundles'][0]['id']
        assert client.post(f"/api/cutting/records/{result.json()['id']}/approve-usluga-batch", json={}).status_code == 200
    assert client.post(f'/api/bundles/{bundle}/receive-sewing').status_code == 200
    sewn = client.post('/api/sewing/records', json={'work_order_id': works['sewing'], 'input_qty': 0,
        'sewn_qty': 12, 'passed_qty': 12, 'size_quantities': [{'size': 'M', 'quantity': 12}]})
    assert sewn.status_code == 201, sewn.text
    wid = works['packaging']
    endpoint = f'/api/work-orders/{wid}/usluga-packaging'
    assert client.get(endpoint).json()['version'] == 0
    payload = {'version': 0, 'items': [{'size': 'M', 'quantity': 13}], 'done': True}
    assert client.put(endpoint, json=payload).status_code == 409
    payload['items'][0]['quantity'] = 10
    payload['done'] = False
    saved = client.put(endpoint, json=payload)
    assert saved.status_code == 200 and saved.json()['version'] == 1, saved.text
    legacy = client.post('/api/packaging/records', json={'work_order_id': wid, 'input_qty': 12, 'packed_qty': 12})
    assert legacy.status_code == 409, legacy.text
    assert client.put(endpoint, json=payload).status_code == 409
    payload.update(version=1, items=[{'size': 'M', 'quantity': 12}], done=True)
    done = client.put(endpoint, json=payload)
    assert done.status_code == 200, done.text
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, wid).passed_qty == 12
        assert db.get(ProductionOrder, order['id']).status == 'ready_for_handover'
        assert db.query(Package).filter_by(production_order_id=order['id']).count() == 0
    result = client.post(f"/api/usluga/orders/{order['id']}/handover", json={'recipient': 'Customer'})
    assert result.status_code == 200, result.text
    payload['version'] = 2
    assert client.put(endpoint, json=payload).status_code == 409


def test_planning_customer_lookup_and_create(client, auth_headers):
    _, cid = fixture_pack()
    response = client.get('/api/planning/branded-order-customers', headers=auth_headers)
    assert response.status_code == 200 and cid in [row['id'] for row in response.json()]
    response = client.post('/api/planning/branded-orders', headers=auth_headers,
                           json={'ordered_for_type': 'customer', 'customer_id': cid})
    assert response.status_code == 201 and response.json()['customer_id'] == cid


def test_roster_import_dry_run_idempotence_and_conflict(client):
    from app.models import Employee, User
    from scripts.import_employee_roster import import_roster
    payload = {'factory_code': 'ECO', 'source': 'test.xlsx', 'source_sha256': 'test-sha', 'records': [
        {'employee_no': '81001', 'full_name': 'Synthetic employee', 'source_sheet': 'Kroy', 'source_row': 5},
        {'employee_no': '81002', 'full_name': 'Synthetic packer', 'source_sheet': 'UPAKOVKA', 'source_row': 6},
    ]}
    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email='admin@example.com').one()
        count = db.query(Employee).count()
        assert import_roster(db, payload, actor)['to_create'] == 2
        assert db.query(Employee).count() == count
        assert import_roster(db, payload, actor, apply=True)['created'] == 2
        db.commit()
        assert import_roster(db, payload, actor, apply=True)['matched'] == 2
        assert db.query(Employee).count() == count + 2
        payload['records'][0]['full_name'] = 'Different person'
        with pytest.raises(ValueError, match='another person'):
            import_roster(db, payload, actor, apply=True)


def test_nastil_migration_preserves_custom_names():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('nastil_migration', Path(__file__).parents[2] / 'alembic/versions/0140_usluga_packaging_nastil.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine('sqlite://').begin() as conn:
        conn.execute(text('CREATE TABLE work_orders (id INTEGER PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE production_batches (id INTEGER PRIMARY KEY, name TEXT, batch_index INTEGER)'))
        conn.execute(text("INSERT INTO production_batches VALUES (1, 'Batch 10', 1), (2, 'Extra batch 11', 2), (3, 'Customer special', 3), (4, NULL, 4)"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert list(conn.execute(text('SELECT name FROM production_batches ORDER BY id')).scalars()) == ['Nastil 1', 'Nastil 2', 'Customer special', 'Nastil 4']


def test_passport_offers_model_sizes_without_rewriting_order_plan(client):
    from app.models.catalog import ModelSize
    from app.api.routes.cutting_passports import material_defaults
    from app.tests.test_cutting_passport_defaults_query_growth import _material_order, _factory_user
    with TestSessionLocal() as db:
        pid, _ = _material_order(db, 1)
        po = db.get(ProductionOrder, pid)
        db.add_all([ModelSize(model_id=po.model_id, size=size) for size in ['M', 'L', 'XL']])
        db.commit()
        data = material_defaults(pid, db, _factory_user())
        assert data['sizes'] == ['M', 'L']
        assert data['size_count'] == 2
        assert data['available_sizes'] == ['M', 'L', 'XL']
