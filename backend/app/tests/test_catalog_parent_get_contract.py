"""Normal-CI actual route contract against independently reviewed frozen baseline."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import hashlib

import pytest
from app.schemas import Model, ModelBOM, ModelColor, ModelImage, ModelSize
from app.tests.conftest import TestSessionLocal
from app.tests.test_paid_operation_factory_scope import _create_payroll_manager, _operation

STAMP = datetime(2020, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
PATHS = ('/api/models/{mid}', '/api/usluga/models/{mid}')


def ref_closure(spec, values):
    """Cycle-safe closure of local component references; reject unresolved refs."""
    found = {}
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == '$ref':
                    if not isinstance(item, str) or not item.startswith('#/components/'):
                        raise AssertionError('unsupported OpenAPI reference')
                    parts = [part.replace('~1', '/').replace('~0', '~') for part in item[2:].split('/')]
                    if item not in found:
                        node = spec
                        for part in parts: node = node[part]
                        found[item] = node
                        visit(node)
                else: visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(values)
    return {key: found[key] for key in sorted(found)}


def operation_contract(spec):
    result = {}
    schemes = {}
    for path in PATHS:
        path_item = spec['paths'][path]
        op = path_item['get']
        security = op['security'] if 'security' in op else spec.get('security', [])
        for alternative in security:
            for name in alternative:
                schemes[name] = spec['components']['securitySchemes'][name]
        result[path] = {'get': op, 'path_parameters': path_item.get('parameters', []),
                        'security_source': 'operation' if 'security' in op else 'global',
                        'effective_security': security}
    return result, schemes


def seed_contract():
    with TestSessionLocal() as db:
        ids = (870001, 870002)
        assert db.query(Model).filter(Model.id.in_(ids)).count() == 0
        for model, start in ((ModelSize, 871001), (ModelColor, 872001), (ModelImage, 873001), (ModelBOM, 874001)):
            assert db.query(model).filter(model.id.in_(range(start, start + 4))).count() == 0
        for index, (scope, factory) in enumerate((('standard', 'MIL'), ('usluga', 'ECO'))):
            m = Model(id=ids[index], code=f'FULL-CONTRACT-{scope}', name=f'Full {scope}',
                      catalog_scope=scope, factory_code=factory, status='draft', created_at=STAMP,
                      updated_at=STAMP, details_json={'note': ' O‘z 🧵 ', 'paid_operations': [
                          _operation('mil', 'milana'), _operation('bst', 'besttex'), _operation('eco', 'eco_cotton')]})
            m.sizes = [ModelSize(id=871001+2*index, size='  M 🧵  ', measurement_json={'chest':12.5,'other':None}, created_at=STAMP, updated_at=STAMP), ModelSize(id=871002+2*index, size=' XL ', measurement_json=None, created_at=STAMP, updated_at=STAMP)]
            m.colors = [ModelColor(id=872001+2*index, color_name='  Qizil-Красный  ', color_code=None, created_at=STAMP, updated_at=STAMP), ModelColor(id=872002+2*index, color_name='Р'*64, color_code=' #ff0000 ', created_at=STAMP, updated_at=STAMP)]
            m.images = [ModelImage(id=873001+2*index, file_url='/synthetic/model.png', file_name='model.png', content_type='image/png', image_type='model', is_primary=True, created_at=STAMP, updated_at=STAMP), ModelImage(id=873002+2*index, file_url='/synthetic/secondary.png', file_name=None, content_type=None, image_type='model', is_primary=False, created_at=STAMP, updated_at=STAMP)]
            m.bom = [ModelBOM(id=874001+2*index, material_name='Материал', material_role=None, quantity_per_piece=1.25, unit='m', waste_percent=0, created_at=STAMP, updated_at=STAMP), ModelBOM(id=874002+2*index, material_name='Cotton', material_role='secondary', quantity_per_piece=2.5, unit='m', waste_percent=1, created_at=STAMP, updated_at=STAMP)]
            db.add(m)
        db.commit()


def read_contract(client, auth_headers):
    ids = (870001, 870002)
    eco = _create_payroll_manager(client, auth_headers, 'ECO')
    standard = client.get(f'/api/models/{ids[0]}', headers=auth_headers)
    usluga = client.get(f'/api/usluga/models/{ids[1]}', headers=eco)
    assert standard.status_code == usluga.status_code == 200
    spec = client.get('/openapi.json').json()
    operations, schemes = operation_contract(spec)
    for value in operations.values():
        assert not any(item.get('name') == 'catalog_scope' for item in value['get'].get('parameters', []) + value['path_parameters'])
    return {'responses': {'standard': standard.json(), 'usluga': usluga.json()},
            'openapi_operations': operations, 'security_schemes': schemes,
            'openapi_components': ref_closure(spec, [operations, schemes])}


def collect_contract(client, auth_headers):
    seed_contract()
    return read_contract(client, auth_headers)


GOLDEN = Path(__file__).parent / 'data' / 'catalog_parent_get_contract.json'
GOLDEN_SHA = 'e8d5ad83665dc9610be20e093cab6c2135314acb88ed4c148d11cb49c686e937'


def reviewed_golden():
    raw = GOLDEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == GOLDEN_SHA
    return json.loads(raw)


def compare(actual, expected):
    assert actual == expected


def test_full_route_and_openapi_contract(client, auth_headers):
    compare(collect_contract(client, auth_headers), reviewed_golden())


def test_real_mil_operation_leak_is_detected_by_full_comparator(client, auth_headers, monkeypatch):
    from app.models.catalog import models_service as service
    # First prove this exact stored fixture and real unmodified routes match the golden.
    seed_contract()
    expected = reviewed_golden()
    healthy = read_contract(client, auth_headers)
    compare(healthy, expected)
    original = service.filter_paid_operations_for_factory
    leaked = _operation('mil', 'milana')
    calls = []
    def fault(details, factory):
        result = original(details, factory)
        if factory == 'eco_cotton':
            source = [row for row in details['paid_operations'] if row == leaked]
            assert len(source) == 1
            result['paid_operations'].append(deepcopy(source[0]))
            calls.append(source[0])
        return result
    monkeypatch.setattr(service, 'filter_paid_operations_for_factory', fault)
    actual = read_contract(client, auth_headers)
    assert calls == [leaked]
    assert leaked in actual['responses']['usluga']['details_json']['paid_operations']
    with pytest.raises(AssertionError): compare(actual, expected)


def test_reviewed_contract_mutation_controls(client, auth_headers):
    expected = reviewed_golden(); actual = collect_contract(client, auth_headers)
    compare(actual, expected)
    altered = deepcopy(expected)
    sizes = [row for row in altered['responses']['standard']['sizes'] if row['id'] == 871001]
    assert len(sizes) == 1 and sizes[0]['measurement_json']['chest'] == 12.5
    sizes[0]['measurement_json']['chest'] = 99
    with pytest.raises(AssertionError): compare(actual, altered)
    altered = deepcopy(expected)
    colors = [row for row in altered['responses']['standard']['colors'] if row['id'] == 872001]
    assert len(colors) == 1 and colors[0]['color_code'] is None
    del colors[0]['color_code']
    with pytest.raises(AssertionError): compare(actual, altered)
    altered = deepcopy(expected)
    altered['openapi_operations'][PATHS[0]]['get']['responses']['200']['description'] = 'changed'
    with pytest.raises(AssertionError): compare(actual, altered)


def test_collector_effective_security_inheritance_and_explicit_empty():
    spec = {'security': [{'token': ['read']}], 'components': {'securitySchemes': {'token': {'type': 'http', 'scheme': 'bearer'}}},
            'paths': {PATHS[0]: {'get': {'responses': {}}}, PATHS[1]: {'get': {'security': [], 'responses': {}}}}}
    operations, schemes = operation_contract(spec)
    assert operations[PATHS[0]]['security_source'] == 'global'
    assert operations[PATHS[0]]['effective_security'] == [{'token': ['read']}]
    assert operations[PATHS[1]]['security_source'] == 'operation'
    assert operations[PATHS[1]]['effective_security'] == []
    assert schemes == {'token': {'type': 'http', 'scheme': 'bearer'}}


def test_collector_ref_closure_cycles_dedup_and_rejection():
    spec = {'components': {'schemas': {'A': {'$ref': '#/components/schemas/B'},
                                         'B': {'$ref': '#/components/schemas/A'}}}}
    a = {'$ref': '#/components/schemas/A'}
    closure = ref_closure(spec, [a, a])
    assert set(closure) == {'#/components/schemas/A', '#/components/schemas/B'}
    with pytest.raises(KeyError): ref_closure(spec, {'$ref': '#/components/schemas/Missing'})
    with pytest.raises(AssertionError): ref_closure(spec, {'$ref': 'https://example.invalid/schema'})
