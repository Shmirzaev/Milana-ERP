"""Lock stocktake vocabulary and legacy evidence behavior."""
from types import SimpleNamespace

from app.models import stocktake_service as service


def test_expected_storage_status_subset():
    assert set(service.STORAGE_STATUSES) == {"received_in_storage", "reserved", "damaged"}
    assert not set(service.STORAGE_STATUSES) & {"packed", "shipped", "delivered"}


def test_legacy_unknown_category_and_sparse_snapshot_survive():
    row = SimpleNamespace(id=1, package_id=7, expected=False, category="old_unknown_value", snapshot={},
                          scan_snapshot=None, scanned_at=None, scanned_by=None, scan_code=None)
    payload = service.row_payload(row, {7: {"status": "old_status"}})
    assert payload["result"] == "old_unknown_value"
    assert payload["snapshot"] == {} and payload["current"] == {"status": "old_status"}
    assert service._row_selected(payload, "all", "")


def test_result_filter_values_and_invalid_request(client, auth_headers):
    schema = client.get('/openapi.json').json()
    params = schema['paths']['/api/warehouse-stocktakes/{count_id}']['get']['parameters']
    result = next(p for p in params if p['name'] == 'result')['schema']
    assert set(result['enum']) == {'all', 'scanned', 'found', 'missing', 'unknown', 'unexpected', 'ambiguous', 'changed'}
    assert client.get('/api/warehouse-stocktakes/1?result=invalid', headers=auth_headers).status_code == 422
