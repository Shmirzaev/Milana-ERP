"""Purchasing receipt QC typing, old retry fingerprints, and persisted values."""
from copy import deepcopy
from typing import get_type_hints

import pytest
from pydantic import BaseModel, Field
from app.libs.dto.common import StoredUnitCost
from app.libs.dto.purchasing.purchase_quantity import PurchaseReceiptQuantity

from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderReceiveLineIn
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.types.purchasing import PurchaseOrderReceiptLineCommand
from app.models.idempotency_service import request_fingerprint
from app.schemas import IdempotencyRecord, StockBatch
from app.db import session as session_module
from app.tests.test_purchase_receipt_idempotency import receipt_order as receipt_order, receive, receipt_state

# Recreate the previous input's string field independently from the new enum.
class LegacyLine(BaseModel):
    purchase_order_line_id: int
    received_quantity: PurchaseReceiptQuantity
    batch_no: str
    warehouse_id: int | None = None
    supplier_id: int | None = None
    cost_per_unit: StoredUnitCost | None = None
    color: str | None = None
    old_code: str | None = None
    color_code: str | None = None
    color_status: str | None = None
    order_no: str | None = None
    width: float | None = None
    gsm: float | None = None
    piece_count: int | None = None
    roll_weights_kg: list[float] = Field(default_factory=list, max_length=1000)
    processes: str | None = None
    qc_status: str = 'passed'
class LegacyReceipt(BaseModel):
    supplier_id: int | None = None
    close_order: bool = False
    lines: list[LegacyLine] = Field(max_length=1000)

@pytest.mark.parametrize('raw,expected', [(None,'passed'),('', 'passed'),('pending','pending'),('passed','passed'),('failed','failed'),('rejected','rejected'),('hold','hold')])
def test_receipt_status_persists_and_legacy_retry_hash_is_unchanged(client, auth_headers, receipt_order, raw, expected):
    payload = deepcopy(receipt_order['payload'])
    if raw is not None:
        payload['lines'][0]['qc_status'] = raw
    # Previous DTO had no normalization and serialized this exact spelling.
    legacy = LegacyReceipt.model_validate(payload).model_dump(mode='json')
    expected_hash = request_fingerprint(legacy)
    first = receive(client, auth_headers, receipt_order, payload=payload)
    assert first.status_code == 200, first.text
    after = receipt_state(receipt_order)
    with session_module.SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(internal_batch_no=receipt_order['po_no']).one()
        record = db.query(IdempotencyRecord).filter_by(key='st01-receipt').one()
        assert type(batch.qc_status) is str and batch.qc_status == expected
        assert record.request_hash == expected_hash
    again = receive(client, auth_headers, receipt_order, payload=payload)
    assert again.status_code == 200 and again.json() == first.json()
    assert receipt_state(receipt_order) == after


def test_empty_and_explicit_passed_remain_distinct_retry_payloads(client, auth_headers, receipt_order):
    first = deepcopy(receipt_order['payload']); first['lines'][0]['qc_status'] = ''
    assert receive(client, auth_headers, receipt_order, payload=first).status_code == 200
    after = receipt_state(receipt_order)
    changed = deepcopy(first); changed['lines'][0]['qc_status'] = 'passed'
    assert receive(client, auth_headers, receipt_order, payload=changed).status_code == 409
    assert receipt_state(receipt_order) == after


@pytest.mark.parametrize('bad', ['other','PASSED',' passed ', None, 1])
def test_invalid_qc_now_422_before_order_lookup_and_no_write(client, auth_headers, receipt_order, bad):
    payload = deepcopy(receipt_order['payload']); payload['lines'][0]['qc_status'] = bad
    before = receipt_state(receipt_order)
    result = receive(client, auth_headers, receipt_order, payload=payload)
    assert result.status_code == 422
    assert result.json()['detail'][0]['loc'][-1] == 'qc_status'
    assert receipt_state(receipt_order) == before
    # The old string field accepted nonempty unknown strings and a missing
    # order then yielded 404. Canonical enum validation deliberately runs first.
    if isinstance(bad,str):
        assert LegacyReceipt.model_validate(payload).lines[0].qc_status == bad
        missing = client.post('/api/purchasing/orders/2147483000/receive', headers=auth_headers, json=payload)
        assert missing.status_code == 422


def test_qc_type_and_defaults_on_dto_and_command():
    assert get_type_hints(PurchaseOrderReceiptLineCommand)['qc_status'] is StockBatchQcStatus
    assert PurchaseOrderReceiveLineIn.model_fields['qc_status'].annotation is StockBatchQcStatus
    line = {'purchase_order_line_id':1,'received_quantity':1,'batch_no':'synthetic'}
    assert PurchaseOrderReceiveLineIn.model_validate(line).qc_status is StockBatchQcStatus.PASSED
    assert PurchaseOrderReceiveLineIn.model_validate({**line,'qc_status':''}).qc_status is StockBatchQcStatus.PASSED

@pytest.mark.parametrize('raw,expected', [
    ('', 'passed'), ('pending', 'pending'), ('passed', 'passed'), ('failed', 'failed'),
    ('rejected', 'rejected'), ('hold', 'hold'), (StockBatchQcStatus.HOLD, 'hold'),
])
def test_direct_legacy_core_caller_keeps_plain_string_storage(receipt_order, raw, expected):
    from app.models.purchasing_service import receive_purchase_order
    from app.schemas import User

    data = deepcopy(receipt_order['payload'])
    data['lines'][0]['qc_status'] = raw
    with session_module.SessionLocal() as db:
        actor = db.query(User).filter_by(email='admin@example.com').one()
        receive_purchase_order(db, order_id=receipt_order['order_id'], data=data, current=actor)
        db.commit()
    with session_module.SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(internal_batch_no=receipt_order['po_no']).one()
        assert type(batch.qc_status) is str and batch.qc_status == expected
