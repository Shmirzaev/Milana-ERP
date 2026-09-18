"""Payroll label query-growth and canonical printed-reference regressions."""

from datetime import datetime, timezone
import json

from fastapi import HTTPException
import pytest
from sqlalchemy import event

from app.api.routes import payroll
from app.core.order_reference import canonical_order_reference, order_reference_variants
from app.models import PayrollQrLabel, ProductionOrder, SalesOrder
from app.models.order_reference import BusinessOrderAlias
from app.schemas.payroll import PayrollQrLabelOut
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_package_query_growth import _captured_get


def test_payroll_label_global_reference_queries_are_bounded(client, auth_headers):
    counts = []
    previous = 0
    for size in (1, 10, 50):
        with TestSessionLocal() as db:
            db.add_all(PayrollQrLabel(
                label_uid=f"query-growth-{index}", factory_code="MIL", sales_order_no=f"MANUAL-{index:04d}",
                issued_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ) for index in range(previous, size))
            db.commit()
        response, statements = _captured_get(client, auth_headers, "/api/payroll/qr-labels?limit=1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == size and len(body["items"]) == 1
        assert len(body["order_counts"]) == size
        assert sum(row["total"] for row in body["order_counts"]) == size
        counts.append(len(statements))
        previous = size
    print(f"Payroll one-label page SELECTs for 1/10/50 reference groups: {counts}")
    assert counts == [9, 9, 9], counts


@pytest.fixture
def order_references():
    with TestSessionLocal() as db:
        first, second = SalesOrder(order_no="SO-9101"), SalesOrder(order_no="SO-9102")
        db.add_all([first, second])
        db.flush()
        linked = ProductionOrder(production_no="PO-9101", sales_order_id=first.id, model_id=1,
                                 production_type="client_order")
        standalone = ProductionOrder(production_no="PO-9102", model_id=1, production_type="branded_stock")
        service = ProductionOrder(production_no="USL-9103", model_id=1, production_type="branded_stock", source_type="usluga")
        db.add_all([linked, standalone, service])
        db.flush()
        aliases = [
            ("PO", "OLD-PO", linked.id), ("SO", "OLD-SO", first.id),
            ("PO", "OTHER-OLD-PO", linked.id), ("SO", "OTHER-OLD-SO", first.id),
            ("PUBLIC_PO", "PUBLIC-STANDALONE", standalone.id), ("PUBLIC_PO", "PUBLIC-LINKED", linked.id),
            ("PO", "PO-9101", standalone.id),  # Real rows take priority over aliases.
            ("PO", "COLLISION-PROD", linked.id), ("USL", "COLLISION-PROD", standalone.id),
            ("SO", "COLLISION-SALES", first.id), ("PUBLIC_PO", "COLLISION-SALES", standalone.id),
            ("PO", "STALE-PO", 999991), ("SO", "STALE-SO", 999992),
            ("PUBLIC_PO", "STALE-PUBLIC", 999993),
            ("USL", "OLD-USL", service.id),
        ]
        db.add_all(BusinessOrderAlias(namespace=namespace, reference=reference, entity_id=identity,
                                     canonical_reference="STALE-ALIAS-TEXT") for namespace, reference, identity in aliases)
        db.commit()
        return linked.id, standalone.id, service.id, first.id, second.id


def _outcome(call):
    try:
        return call()
    except HTTPException as error:
        return error.status_code, error.detail


def test_batch_reference_lookup_matches_original_values_variants_and_errors(order_references):
    linked, standalone, service, first, second = order_references
    requests = {
        ("PO", "OLD-PO", None, None), ("PO", "PO-9101", None, None),
        ("PO", "COLLISION-PROD", None, None), ("PO", "COLLISION-PROD", linked, None),
        ("PO", "OLD-PO", 999991, None), ("PO", "STALE-PO", None, None),
        ("SO", "OLD-SO", None, None), ("SO", "STALE-SO", None, None),
        ("SO", "STALE-PUBLIC", None, None), ("SO", "PUBLIC-STANDALONE", None, None),
        ("SO", "PUBLIC-LINKED", None, None), ("SO", "PUBLIC-LINKED", None, linked),
        ("SO", "COLLISION-SALES", None, None), ("SO", "COLLISION-SALES", None, standalone),
        ("SO", "COLLISION-SALES", second, standalone), ("SO", "OLD-SO", 999994, linked),
        ("SO", "PO-9102", None, None), ("SO", "PO-9101", None, None),
        ("SO", "  PUBLIC-STANDALONE  ", None, None), ("SO", "  OLD-SO  ", None, None),
        ("SO", "manual order", None, standalone), ("SO", "manual order", None, 999995),
        ("SO", None, first, standalone), ("PO", "", linked, None),
        ("USL", "OLD-USL", None, None), ("USL", "OLD-USL", linked, None),
        ("USL", "USL-9103", service, None),
    }
    with TestSessionLocal() as db:
        expected = {}
        for key in requests:
            namespace, reference, identity, production_id = key
            kwargs = {"entity_id": identity, "production_order_id": production_id}
            canonical = _outcome(lambda: canonical_order_reference(db, namespace, reference, **kwargs))
            expected[key] = canonical, (
                _outcome(lambda: order_reference_variants(db, namespace, canonical, **kwargs))
                if not isinstance(canonical, tuple) and canonical != reference else None
            )
    with TestSessionLocal() as db:
        # Count preparation and resolution together; no warmed ORM/session cache.
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            lookup = payroll._PayrollOrderLookup(db, requests, requests)
            loaded_count = len(statements)
            for key, (expected_canonical, expected_variants) in expected.items():
                namespace, reference, identity, production_id = key
                kwargs = {"entity_id": identity, "production_order_id": production_id, "lookup": lookup}
                canonical = _outcome(lambda: canonical_order_reference(db, namespace, reference, **kwargs))
                assert canonical == expected_canonical, key
                if not isinstance(canonical, tuple) and canonical != reference:
                    assert _outcome(lambda: order_reference_variants(db, namespace, canonical, **kwargs)) == expected_variants, key
            assert len(statements) == loaded_count  # Resolution never falls back to SQL.
            # Two scalar-loading passes plus four distinct variant namespaces:
            # SO, PO/USL/PUBLIC_PO, PUBLIC_PO-only, and USL-only.
            assert loaded_count == 10
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)


def test_label_payload_and_global_counts_match_original_across_filters(client, auth_headers, order_references):
    linked, standalone, _, first, _ = order_references
    payload = {"production_no": "OLD-PO", "sales_order_no": "OLD-SO", "label_id": "OLD-PO",
               "quantity": 7, "rate_per_piece": 250, "notes": "OLD-SO"}
    with TestSessionLocal() as db:
        rows = [
            dict(production_no="OLD-PO", sales_order_no="OLD-SO", payload=json.dumps(payload)),
            dict(production_order_id=linked, sales_order_id=first, production_no="manual PO", sales_order_no="manual SO",
                 payload=json.dumps({**payload, "production_no": "manual PO", "sales_order_no": "manual SO"})),
            dict(production_order_id=linked, sales_order_id=first, production_no="OTHER-OLD-PO", sales_order_no="OTHER-OLD-SO",
                 payload=f"MW2*{linked}*OLD-PO*-*1*1*MODEL*sewing*SEW*Sleeve*7*250*UZS*1*{first}*OLD-SO"),
            dict(production_order_id=standalone, sales_order_no="PUBLIC-STANDALONE", payload=json.dumps({"so": "PUBLIC-STANDALONE"})),
            dict(sales_order_no="PUBLIC-STANDALONE", payload=json.dumps({"so": "PUBLIC-STANDALONE"})),
            dict(sales_order_no="  manual text  ", payload="not a structured payload"),
            dict(production_order_id=linked, production_no="OLD-PO", sales_order_no=None, payload=' ["OLD-PO"] '),
            dict(production_order_id=999991, production_no="OLD-PO", sales_order_no="STALE-SO", payload=None),
            dict(production_no=None, sales_order_no=None, payload=' {"notes":"OLD-PO"} '),
            dict(production_no="STALE-PO", sales_order_no="STALE-PUBLIC", payload=None, status="superseded"),
        ]
        for index, values in enumerate(rows):
            db.add(PayrollQrLabel(label_uid=f"contract-{index}", factory_code="MIL",
                                 issued_at=datetime(2026, 9, index + 1, tzinfo=timezone.utc),
                                 **{"status": "scanned" if index % 2 else "available", **values}))
        db.add(PayrollQrLabel(label_uid="other-factory", factory_code="BST", sales_order_no="OTHER-FACTORY"))
        db.commit()
    with TestSessionLocal() as db:
        labels = db.query(PayrollQrLabel).filter_by(factory_code="MIL").order_by(PayrollQrLabel.issued_at.desc(), PayrollQrLabel.id.desc()).all()
        expected = [PayrollQrLabelOut.model_validate(
            payroll._serialize_qr_label(row, records={}, employees={}, departments={}),
        ).model_dump(mode="json") for row in labels]
        expected_counts = {}
        for row in labels:
            if row.status == "superseded":
                continue
            key = (payroll._canonical_payroll_reference(db, "SO", row.sales_order_no, entity_id=row.sales_order_id,
                                                       production_order_id=row.production_order_id)
                   or payroll._canonical_payroll_reference(db, "PO", row.production_no, entity_id=row.production_order_id) or "No order")
            entry = expected_counts.setdefault(key, {"order_no": key, "total": 0, "scanned": 0})
            entry["total"] += 1
            entry["scanned"] += row.status == "scanned"
    for params, expected_items in [
        ({"include_superseded": "true"}, expected),
        ({"include_superseded": "true", "offset": 2, "limit": 3}, expected[2:5]),
        ({"search": "contract-0"}, [item for item in expected if item["label_uid"] == "contract-0"]),
        ({"status": "scanned"}, [item for item in expected if item["status"] == "scanned"]),
        ({"offset": 100}, []),
    ]:
        response = client.get("/api/payroll/qr-labels", headers=auth_headers, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"] == expected_items
        assert sorted(body["order_counts"], key=lambda row: row["order_no"]) == sorted(expected_counts.values(), key=lambda row: row["order_no"])
    with TestSessionLocal() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid="contract-0").one().payload == json.dumps(payload)


@pytest.mark.parametrize("reference,field", [("COLLISION-PROD", "production_no"), ("COLLISION-SALES", "sales_order_no")])
def test_global_count_ambiguity_is_not_hidden_by_page_filters(client, auth_headers, order_references, reference, field):
    with TestSessionLocal() as db:
        db.add(PayrollQrLabel(label_uid="hidden-ambiguous", factory_code="MIL", **{field: reference}))
        db.commit()
    response = client.get("/api/payroll/qr-labels?search=does-not-match&limit=1", headers=auth_headers)
    assert response.status_code == 409
    assert "Ambiguous" in response.json()["detail"]


@pytest.mark.parametrize("linked_ids", [False, True])
def test_alias_payload_query_count_is_flat_for_one_and_many_labels(client, auth_headers, linked_ids):
    counts = []
    previous = 0
    for size in (1, 10, 50):
        with TestSessionLocal() as db:
            for index in range(previous, size):
                sales = SalesOrder(order_no=f"SO-{9200 + index}")
                db.add(sales)
                db.flush()
                production = ProductionOrder(production_no=f"PO-{9200 + index}", sales_order_id=sales.id,
                                             model_id=1, production_type="client_order")
                db.add(production)
                db.flush()
                old_po, old_so = f"OLD-PRODUCTION-{index}", f"OLD-SALES-{index}"
                db.add_all([
                    BusinessOrderAlias(namespace="PO", reference=old_po, entity_id=production.id, canonical_reference=production.production_no),
                    BusinessOrderAlias(namespace="SO", reference=old_so, entity_id=sales.id, canonical_reference=sales.order_no),
                    PayrollQrLabel(label_uid=f"alias-growth-{index}", factory_code="MIL", production_no=old_po,
                                   sales_order_no=old_so, payload=json.dumps({"po": old_po, "so": old_so, "quantity": 7}),
                                   production_order_id=production.id if linked_ids else None,
                                   sales_order_id=sales.id if linked_ids else None),
                ])
            db.commit()
        for page_size in (1, size):
            response, statements = _captured_get(client, auth_headers, f"/api/payroll/qr-labels?limit={page_size}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == size and len(body["items"]) == page_size
            for row in body["items"]:
                index = int(row["label_uid"].rsplit("-", 1)[1])
                assert row["production_no"] == f"PO-{9200 + index}"
                assert row["sales_order_no"] == f"SO-{9200 + index}"
                assert json.loads(row["payload"]) == {"po": f"PO-{9200 + index}", "so": f"SO-{9200 + index}", "quantity": 7}
            counts.append(len(statements))
        previous = size
    print(f"Payroll alias/payload SELECTs (one/full page) for 1/10/50 groups: {counts}")
    assert counts == [14] * 6, counts


def test_reference_batches_cross_400_without_per_reference_queries(client, auth_headers):
    with TestSessionLocal() as db:
        db.add_all(PayrollQrLabel(label_uid=f"boundary-{index}", factory_code="MIL", sales_order_no=f"BOUNDARY-{index}")
                   for index in range(401))
        db.commit()
    response, statements = _captured_get(client, auth_headers, "/api/payroll/qr-labels?limit=1")
    assert response.status_code == 200, response.text
    assert len(response.json()["order_counts"]) == 401
    assert len(statements) == 12


def test_page_only_payload_ambiguity_is_not_suppressed(client, auth_headers, order_references):
    with TestSessionLocal() as db:
        db.add(PayrollQrLabel(label_uid="payload-ambiguity", factory_code="MIL", status="superseded",
                             payload=json.dumps({"so": "COLLISION-SALES"})))
        db.commit()
    hidden = client.get("/api/payroll/qr-labels", headers=auth_headers)
    assert hidden.status_code == 200 and hidden.json()["order_counts"] == []
    visible = client.get("/api/payroll/qr-labels?include_superseded=true", headers=auth_headers)
    assert visible.status_code == 409 and "Ambiguous sales/factory" in visible.json()["detail"]
