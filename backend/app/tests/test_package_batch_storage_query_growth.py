from math import ceil
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import packages as package_routes
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Model,
    Package,
    PackageItem,
    PackagePrintRun,
    PackagePrintRunMember,
    PackageScanLog,
    ProductionOrder,
    User,
)
from app.schemas.tracking import PackageBatchReceiveStorageIn, PackageBatchStoragePlacementIn
from app.services import packages as package_service


def _select_trace(bind, callback):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


def _table_selects(statements, table):
    return sum(f" from {table} " in statement for statement in statements)


def _batch_packages(package_count: int, *, status: str) -> list[int]:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        models = [
            Model(
                code=f"PERF10-M-{marker}-{number:04d}",
                name=f"PERF10 model {number}",
                product_type="shirt",
            )
            for number in range(package_count)
        ]
        db.add_all(models)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF10-PO-{marker}-{number:04d}",
                production_type="branded_stock",
                model_id=model.id,
                status="packaging",
                planned_quantity=1,
            )
            for number, model in enumerate(models)
        ]
        db.add_all(orders)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF10-PKG-{marker}-{number:04d}",
                barcode=f"PERF10-BC-{marker}-{number:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status=status,
                storage_cell="A-01" if status == "received_in_storage" else None,
                storage_shelf="S1" if status == "received_in_storage" else None,
            )
            for number, (order, model) in enumerate(zip(orders, models, strict=True))
        ]
        db.add_all(packages)
        db.flush()
        db.add_all([
            PackageItem(
                package_id=package.id,
                model_id=package.model_id,
                color=package.color,
                size="M",
                quantity=1,
            )
            for package in packages
        ])
        db.commit()
        return [int(package.id) for package in packages]


def test_batch_production_sync_deduplicates_in_deterministic_order(monkeypatch):
    calls = []
    monkeypatch.setattr(
        package_service,
        "_sync_package_production",
        lambda _db, production_order_id: calls.append(production_order_id),
    )

    package_service.sync_package_production_orders(None, [3, 2, None, 3, 1, 2])

    assert calls == [1, 2, 3]


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_batch_receive_batches_locked_guards_and_response_context(monkeypatch, package_count):
    package_ids = _batch_packages(package_count, status="packed")
    request_ids = list(reversed(package_ids))
    monkeypatch.setattr(package_routes, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "_sync_package_production", lambda *_args, **_kwargs: None)

    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        result, statements = _select_trace(
            db.bind,
            lambda: package_routes.api_batch_receive_storage(
                PackageBatchReceiveStorageIn(
                    package_ids=[*request_ids, request_ids[0]],
                    storage_cell="B-02",
                    storage_shelf="S2",
                ),
                db,
                current,
            ),
        )

    assert result["count"] == package_count
    assert [row["id"] for row in result["packages"]] == request_ids
    assert all(row["status"] == "received_in_storage" for row in result["packages"])
    assert all(len(row["items"]) == 1 and len(row["scan_logs"]) == 1 for row in result["packages"])
    expected_chunks = ceil(package_count / 400)
    assert _table_selects(statements, "package_print_run_members") == 2 * expected_chunks
    assert _table_selects(statements, "models") == expected_chunks
    assert _table_selects(statements, "package_items") == expected_chunks
    assert _table_selects(statements, "package_scan_logs") == expected_chunks
    assert _table_selects(statements, "production_orders") == 2 * expected_chunks
    assert len(statements) <= 12 * expected_chunks + 1


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_batch_place_batches_fresh_source_checks_and_response_context(monkeypatch, package_count):
    package_ids = _batch_packages(package_count, status="received_in_storage")
    request_ids = list(reversed(package_ids))
    monkeypatch.setattr(package_routes, "log_action", lambda *_args, **_kwargs: None)

    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        current.department
        result, statements = _select_trace(
            db.bind,
            lambda: package_routes.api_batch_place_on_map(
                PackageBatchStoragePlacementIn(
                    package_ids=[*request_ids, request_ids[0]],
                    storage_cell="C-03",
                    storage_shelf="S2",
                ),
                db,
                current,
            ),
        )

    assert result["count"] == package_count
    assert [row["id"] for row in result["packages"]] == request_ids
    assert all((row["storage_cell"], row["storage_shelf"]) == ("C-03", "S2") for row in result["packages"])
    assert all(
        len(row["items"]) == 1
        and len(row["scan_logs"]) == 1
        and row["scan_logs"][0]["scan_type"] == "relocated_storage"
        and row["scan_logs"][0]["location"] == "C-03/S2"
        for row in result["packages"]
    )
    expected_chunks = ceil(package_count / 400)
    assert _table_selects(statements, "models") == expected_chunks
    assert _table_selects(statements, "package_items") == expected_chunks
    assert _table_selects(statements, "package_scan_logs") == expected_chunks
    assert _table_selects(statements, "production_orders") == 2 * expected_chunks
    assert len(statements) <= 12 * expected_chunks


def test_batch_place_rejects_other_factory_before_any_mutation():
    package_ids = _batch_packages(2, status="received_in_storage")
    with SessionLocal() as db:
        first = db.get(Package, package_ids[0])
        second = db.get(Package, package_ids[1])
        first.packaging_department_code = "PKG"
        second.packaging_department_code = "BPK"
        db.commit()

    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        with pytest.raises(HTTPException) as exc_info:
            package_routes.api_batch_place_on_map(
                PackageBatchStoragePlacementIn(
                    package_ids=package_ids,
                    storage_cell="C-03",
                    storage_shelf="S2",
                ),
                db,
                current,
            )
        assert exc_info.value.status_code == 403

    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        assert [(row.storage_cell, row.storage_shelf) for row in packages] == [("A-01", "S1"), ("A-01", "S1")]
        assert db.query(PackageScanLog).filter(PackageScanLog.package_id.in_(package_ids)).count() == 0


def test_batch_place_usluga_rejection_rolls_back_and_preserves_audits(client, auth_headers):
    package_ids = _batch_packages(2, status="received_in_storage")
    with SessionLocal() as db:
        second = db.get(Package, package_ids[1])
        db.get(ProductionOrder, second.production_order_id).source_type = "usluga"
        before_audits = db.query(AuditLog).count()
        db.commit()

    response = client.post(
        "/api/packages/batch/place-on-map",
        json={"package_ids": package_ids, "storage_cell": "C-03", "storage_shelf": "S2"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "cannot enter warehouse flow" in response.json()["detail"]

    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        assert [(row.storage_cell, row.storage_shelf) for row in packages] == [("A-01", "S1"), ("A-01", "S1")]
        assert db.query(PackageScanLog).filter(PackageScanLog.package_id.in_(package_ids)).count() == 0
        assert db.query(AuditLog).count() == before_audits


def test_batch_place_reads_fresh_uncommitted_source_type():
    package_id = _batch_packages(1, status="received_in_storage")[0]
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package = db.get(Package, package_id)
        db.get(ProductionOrder, package.production_order_id).source_type = "usluga"

        with pytest.raises(HTTPException, match="cannot enter warehouse flow"):
            package_routes.api_batch_place_on_map(
                PackageBatchStoragePlacementIn(
                    package_ids=[package_id],
                    storage_cell="C-03",
                    storage_shelf="S2",
                ),
                db,
                current,
            )
        db.rollback()

    with SessionLocal() as db:
        package = db.get(Package, package_id)
        assert (package.storage_cell, package.storage_shelf) == ("A-01", "S1")
        assert db.query(PackageScanLog).filter_by(package_id=package_id).count() == 0


def test_batch_place_writes_one_ordered_audit_per_package(client, auth_headers):
    package_ids = _batch_packages(2, status="received_in_storage")
    request_ids = list(reversed(package_ids))
    response = client.post(
        "/api/packages/batch/place-on-map",
        json={"package_ids": request_ids, "storage_cell": "C-03", "storage_shelf": "S2"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "place_storage_map",
                AuditLog.entity_type == "Package",
                AuditLog.entity_id.in_(package_ids),
            )
            .order_by(AuditLog.id)
            .all()
        )
        assert [int(row.entity_id) for row in audits] == request_ids
        assert [row.new_value_json for row in audits] == [
            {"storage_cell": "C-03", "storage_shelf": "S2", "mode": "batch"},
            {"storage_cell": "C-03", "storage_shelf": "S2", "mode": "batch"},
        ]


def test_batch_receive_gate_rejects_other_package_identity_session_and_transaction():
    package_id = _batch_packages(1, status="packed")[0]
    with SessionLocal() as db:
        gate = package_service.prepare_locked_package_receive(db, [package_id])
        package = gate.packages_by_id[package_id]
        db.expunge(package)
        replacement = db.get(Package, package_id)
        with pytest.raises(HTTPException, match="locked package context"):
            package_service.receive_at_storage(db, replacement, None, None, receive_gate=gate)

    with SessionLocal() as db:
        gate = package_service.prepare_locked_package_receive(db, [package_id])
        db.commit()
        replacement = db.get(Package, package_id)
        with pytest.raises(HTTPException, match="locked package context"):
            package_service.receive_at_storage(db, replacement, None, None, receive_gate=gate)

    with SessionLocal() as db:
        savepoint = db.begin_nested()
        gate = package_service.prepare_locked_package_receive(db, [package_id])
        package = gate.packages_by_id[package_id]
        savepoint.rollback()
        with pytest.raises(HTTPException, match="locked package context"):
            package_service.receive_at_storage(db, package, None, None, receive_gate=gate)

    with SessionLocal() as first, SessionLocal() as second:
        gate = package_service.prepare_locked_package_receive(first, [package_id])
        other = second.get(Package, package_id)
        with pytest.raises(HTTPException, match="locked package context"):
            package_service.receive_at_storage(second, other, None, None, receive_gate=gate)


def test_batch_receive_gate_rejects_after_outer_rollback():
    package_id = _batch_packages(1, status="packed")[0]
    with SessionLocal() as db:
        gate = package_service.prepare_locked_package_receive(db, [package_id])
        package = gate.packages_by_id[package_id]
        db.rollback()
        db.get(Package, package_id)

        with pytest.raises(HTTPException, match="locked package context"):
            package_service.receive_at_storage(db, package, None, None, receive_gate=gate)


def test_batch_receive_cached_gate_rejects_usluga_package():
    package_id = _batch_packages(1, status="packed")[0]
    with SessionLocal() as db:
        package = db.get(Package, package_id)
        order = db.get(ProductionOrder, package.production_order_id)
        order.source_type = "usluga"
        db.commit()

        gate = package_service.prepare_locked_package_receive(db, [package_id])
        with pytest.raises(HTTPException, match="cannot enter warehouse flow"):
            package_service.receive_at_storage(
                db,
                gate.packages_by_id[package_id],
                None,
                None,
                receive_gate=gate,
            )


def test_batch_receive_missing_id_does_not_mutate_valid_package(client, auth_headers):
    package_id = _batch_packages(1, status="packed")[0]
    response = client.post(
        "/api/packages/batch/receive-storage",
        json={"package_ids": [package_id, 2_147_483_647], "storage_cell": "B-02"},
        headers=auth_headers,
    )
    assert response.status_code == 404

    with SessionLocal() as db:
        package = db.get(Package, package_id)
        assert package.status == "packed"
        assert package.storage_cell is None
        assert db.query(PackageScanLog).filter_by(package_id=package_id).count() == 0


def test_batch_receive_print_member_rejection_rolls_back_earlier_package(client, auth_headers):
    first_id, member_id = _batch_packages(2, status="packed")
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        print_run = PackagePrintRun(
            run_no=f"PERF10-RUN-{uuid4().hex[:8]}",
            code=f"PERF10-CODE-{uuid4().hex[:8]}",
            packaging_department_code="cutting",
            package_ids=[member_id],
            created_by=current.id,
        )
        db.add(print_run)
        db.flush()
        db.add(PackagePrintRunMember(run_id=print_run.id, package_id=member_id, snapshot={}))
        db.commit()

    response = client.post(
        "/api/packages/batch/receive-storage",
        json={"package_ids": [first_id, member_id], "storage_cell": "B-02"},
        headers=auth_headers,
    )
    assert response.status_code == 409

    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_([first_id, member_id])).all()
        assert {package.status for package in packages} == {"packed"}
        assert db.query(PackageScanLog).filter(PackageScanLog.package_id.in_([first_id, member_id])).count() == 0


def test_batch_receive_builds_response_before_commit(monkeypatch, client, auth_headers):
    package_id = _batch_packages(1, status="packed")[0]
    monkeypatch.setattr(package_routes, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "_sync_package_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        package_routes,
        "_package_detail_payloads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("serialization failed")),
    )

    with pytest.raises(RuntimeError, match="serialization failed"):
        client.post(
            "/api/packages/batch/receive-storage",
            json={"package_ids": [package_id], "storage_cell": "B-02"},
            headers=auth_headers,
        )

    with SessionLocal() as db:
        package = db.get(Package, package_id)
        assert package.status == "packed"
        assert package.storage_cell is None
        assert db.query(PackageScanLog).filter(PackageScanLog.package_id == package_id).count() == 0


def test_scalar_receive_keeps_print_member_conflict_precedence():
    package_id = _batch_packages(1, status="received_in_storage")[0]
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package = db.get(Package, package_id)
        order = db.get(ProductionOrder, package.production_order_id)
        order.source_type = "usluga"
        print_run = PackagePrintRun(
            run_no=f"PERF10-RUN-{uuid4().hex[:8]}",
            code=f"PERF10-CODE-{uuid4().hex[:8]}",
            packaging_department_code="cutting",
            package_ids=[package_id],
            created_by=current.id,
        )
        db.add(print_run)
        db.flush()
        db.add(PackagePrintRunMember(run_id=print_run.id, package_id=package_id, snapshot={}))
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            package_service.receive_at_storage(db, package, None, current.id)
        assert exc_info.value.status_code == 409
        assert "print run" in exc_info.value.detail


def test_batch_storage_endpoints_keep_authentication(client):
    receive = client.post(
        "/api/packages/batch/receive-storage",
        json={"package_ids": [1], "storage_cell": "A-01", "storage_shelf": "S1"},
    )
    place = client.post(
        "/api/packages/batch/place-on-map",
        json={"package_ids": [1], "storage_cell": "A-01", "storage_shelf": "S1"},
    )
    assert receive.status_code in {401, 403}
    assert place.status_code in {401, 403}

    with SessionLocal() as db:
        user = User(
            name="PERF10 denied actor",
            email=f"perf10-denied-{uuid4().hex}@example.invalid",
            password_hash="unused-by-synthetic-token-test",
            is_active=True,
            extra_permissions=[],
        )
        db.add(user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    denied_receive = client.post(
        "/api/packages/batch/receive-storage",
        json={"package_ids": [1], "storage_cell": "A-01", "storage_shelf": "S1"},
        headers=denied_headers,
    )
    denied_place = client.post(
        "/api/packages/batch/place-on-map",
        json={"package_ids": [1], "storage_cell": "A-01", "storage_shelf": "S1"},
        headers=denied_headers,
    )
    assert denied_receive.status_code == 403
    assert denied_place.status_code == 403
