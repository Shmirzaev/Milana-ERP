"""Receiving must expose every eligible Nastil, without changing receipt state."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas import Bundle, BundleScanLog, ProductionBatch, ProductionOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_bundle_receiving_factory_scope import _headers, _ready_bundle


def waiting_batches(factory="MIL", count=49):
    bundle_id, _, order_id, _ = _ready_bundle(factory, "created")
    with TestSessionLocal() as db:
        template = db.get(Bundle, bundle_id)
        order_no = db.get(ProductionOrder, order_id).production_no
        ids = []
        # Same timestamp deliberately challenges the old nondeterministic ordering.
        stamp = datetime(2026, 11, 11, tzinfo=timezone.utc)
        for index in range(count):
            batch = ProductionBatch(production_order_id=order_id,
                batch_no=f"PAGE-{index:03}", batch_index=index + 1,
                name=f"Nastil {index + 1}", planned_quantity=10)
            db.add(batch)
            db.flush()
            row = template if index == 0 else Bundle(
                bundle_no=f"PAGE-{uuid4().hex}", barcode=uuid4().hex,
                production_order_id=order_id, model_id=template.model_id,
                color=template.color, size=template.size, quantity=10,
                sewing_factory_code=factory, status="created",
                current_department_id=template.current_department_id,
                next_department_id=template.next_department_id,
            )
            row.production_batch_id = batch.id
            row.created_at = stamp
            db.add(row)
            ids.append(batch.id)
        db.commit()
        return order_no, ids


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_every_waiting_nastil_is_reachable_and_reads_do_not_receive(client, auth_headers, factory):
    order_no, ids = waiting_batches(factory, 123)
    headers = _headers(client, auth_headers, factory)
    collected = []
    lengths = []
    for offset in range(0, 140, 20):
        response = client.get("/api/bundles/sewing-receive-options", headers=headers,
            params={"q": order_no, "factory_code": factory, "limit": 20, "offset": offset})
        assert response.status_code == 200, response.text
        rows = response.json()
        lengths.append(len(rows))
        collected.extend(row["production_batch_id"] for row in rows)
        assert all(row["quantity"] == 10 and row["bundle_count"] == 1 for row in rows)
    assert lengths == [20, 20, 20, 20, 20, 20, 3]
    assert collected == list(reversed(ids))
    assert len(set(collected)) == 123
    assert client.get("/api/bundles/sewing-receive-options", headers=headers,
        params={"q": order_no, "limit": 20, "offset": 140}).json() == []
    with TestSessionLocal() as db:
        assert db.query(Bundle).filter(Bundle.production_batch_id.in_(ids), Bundle.status != "created").count() == 0
        assert db.query(BundleScanLog).join(Bundle).filter(Bundle.production_batch_id.in_(ids)).count() == 0


def test_offset_validation_and_existing_limit_cap(client, auth_headers):
    order_no, _ = waiting_batches(count=123)
    assert client.get("/api/bundles/sewing-receive-options", headers=auth_headers,
        params={"offset": -1}).status_code == 422
    response = client.get("/api/bundles/sewing-receive-options", headers=auth_headers,
        params={"q": order_no, "limit": 999})
    assert len(response.json()) == 100


def test_later_pages_keep_factory_status_and_search_scope(client, auth_headers):
    order_no, ids = waiting_batches("MIL")
    waiting_batches("ECO")
    headers = _headers(client, auth_headers, "MIL")
    with TestSessionLocal() as db:
        db.query(Bundle).filter_by(production_batch_id=ids[-1]).update({"status": "received_sewing"})
        db.commit()
    rows = client.get("/api/bundles/sewing-receive-options", headers=headers,
        params={"q": order_no, "offset": 40, "limit": 20}).json()
    assert [row["production_batch_id"] for row in rows] == list(reversed(ids[:-1]))[40:]
    assert client.get("/api/bundles/sewing-receive-options", headers=headers,
        params={"factory_code": "ECO", "offset": 20}).status_code == 403
    assert client.get("/api/bundles/sewing-receive-options", headers=headers,
        params={"q": "no-such-order", "offset": 20}).json() == []


def test_legacy_band_caller_can_omit_offset(client, auth_headers):
    from app.api.routes.bundles import sewing_receive_options
    from app.schemas import User

    order_no, ids = waiting_batches("ECO", 3)
    # The band's existing route calls this function directly with plain values.
    with TestSessionLocal() as db:
        current = db.query(User).filter_by(email="admin@example.com").one()
        current.session_factory_code = "ECO"
        rows = sewing_receive_options(db, current, q=order_no, limit=100, factory_code="ECO")
        assert [row["production_batch_id"] for row in rows] == list(reversed(ids))
