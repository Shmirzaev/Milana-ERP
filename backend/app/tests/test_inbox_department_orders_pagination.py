from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes import inbox
from app.models import Bundle, Department, Model, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def _enable_inbox_access(monkeypatch):
    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])


def _dept_id(db, code: str) -> int:
    return int(db.query(Department.id).filter(Department.code == code).scalar())


def _production_order(db, model_id: int, suffix: str, *, status="new") -> ProductionOrder:
    row = ProductionOrder(
        production_no=f"CORE-INBOX-{suffix}",
        production_type="client_order",
        model_id=model_id,
        status=status,
        planned_quantity=20,
    )
    db.add(row)
    db.flush()
    return row


def _work_order(
    db,
    production_order_id: int,
    department_id: int,
    operation: str,
    suffix: str,
    *,
    status="pending",
    passed_qty=0,
    planned_input_qty=0,
    planned_output_qty=20,
    actual_input_qty=0,
    end_time=None,
) -> WorkOrder:
    row = WorkOrder(
        production_order_id=production_order_id,
        department_id=department_id,
        operation=operation,
        status=status,
        passed_qty=passed_qty,
        actual_output_qty=passed_qty,
        planned_input_qty=planned_input_qty,
        planned_output_qty=planned_output_qty,
        actual_input_qty=actual_input_qty,
        end_time=end_time,
    )
    db.add(row)
    db.flush()
    return row


def _legacy_department_rows(db, dept: str, *, tz="UTC"):
    legacy = inbox.department_inbox(
        db,
        SimpleNamespace(department_id=None),
        dept=dept,
        tz=tz,
    )
    incoming_work = legacy["incoming_work_orders"]
    incoming_pos = {int(row["production_order_id"]) for row in incoming_work}
    incoming_groups = [
        row for row in legacy["incoming_bundle_groups"]
        if int(row["production_order_id"]) not in incoming_pos
    ]
    queues = (
        ("incoming", [*incoming_work, *incoming_groups]),
        ("pending", legacy["pending_work_orders"]),
        ("in_progress", legacy["in_progress_work_orders"]),
        ("completed", legacy["done_today"]),
    )
    merged = {}
    for queue_kind, rows in queues:
        for row in rows:
            key = inbox._core_inbox_identity_key(row)
            merged[key] = {**merged.get(key, {}), **row, "queue_kind": queue_kind}
    return list(merged.values())


def _read_all_core_pages(db, dept: str, *, tz="UTC", page_size=37):
    rows = []
    offset = 0
    while True:
        page = inbox.department_order_page(
            db,
            SimpleNamespace(department_id=None),
            dept=dept,
            tz=tz,
            limit=page_size,
            offset=offset,
        )
        rows.extend(page["rows"])
        if not page["has_more"]:
            assert offset + len(page["rows"]) == page["total"]
            break
        offset += page_size
    return rows


def test_department_order_pages_match_legacy_merge_and_keep_later_winner_and_po_suppression(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"CORE-INBOX-{suffix}", name="Canonical inbox model")
        db.add(model)
        db.flush()
        cutting_id = _dept_id(db, "CUT")
        sewing_id = _dept_id(db, "SEW")

        duplicate_po = _production_order(db, int(model.id), f"{suffix}-winner")
        _work_order(
            db, int(duplicate_po.id), cutting_id, "cutting", f"{suffix}-source",
            status="completed", passed_qty=14,
        )
        sewing = _work_order(
            db, int(duplicate_po.id), sewing_id, "sewing", f"{suffix}-sewing",
            status="pending", planned_input_qty=14,
        )
        db.add(Bundle(
            bundle_no=f"CORE-INBOX-{suffix}-suppressed",
            barcode=f"CORE-INBOX-{suffix}-suppressed",
            production_order_id=duplicate_po.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=14,
            next_department_id=sewing_id,
            sewing_factory_code="BESTTEX",
            status="sent_to_sewing",
        ))

        bundle_po = _production_order(db, int(model.id), f"{suffix}-group")
        db.add_all([
            Bundle(
                bundle_no=f"CORE-INBOX-{suffix}-group-a",
                barcode=f"CORE-INBOX-{suffix}-group-a",
                production_order_id=bundle_po.id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=4,
                next_department_id=sewing_id,
                sewing_factory_code="BTX",
                status="sent_to_sewing",
            ),
            Bundle(
                bundle_no=f"CORE-INBOX-{suffix}-group-b",
                barcode=f"CORE-INBOX-{suffix}-group-b",
                production_order_id=bundle_po.id,
                model_id=model.id,
                color="navy",
                size="L",
                quantity=6,
                next_department_id=sewing_id,
                sewing_factory_code="BST",
                status="sent_to_sewing",
            ),
        ])
        in_progress_po = _production_order(db, int(model.id), f"{suffix}-progress")
        in_progress = _work_order(
            db, int(in_progress_po.id), sewing_id, "sewing", f"{suffix}-progress",
            status="in_progress",
        )
        db.commit()

        expected = _legacy_department_rows(db, "SEW")
        actual = _read_all_core_pages(db, "SEW", page_size=2)

    assert actual == expected
    winner = next(row for row in actual if row.get("id") == sewing.id)
    assert winner["queue_kind"] == "pending"
    assert winner["status"] == "pending"
    assert winner["ready_qty"] == 14
    assert "bundle_count" not in winner
    assert sum(row.get("bundle_count", 0) for row in actual) == 2
    assert next(row for row in actual if row.get("id") == in_progress.id)["queue_kind"] == "in_progress"


def test_department_order_pages_extend_past_legacy_five_hundred_row_cap(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        before = inbox.department_order_page(db, SimpleNamespace(department_id=None), dept="PRT")
        baseline = before["total"]
        model = Model(code=f"CORE-INBOX-LARGE-{suffix}", name="Large inbox model")
        db.add(model)
        db.flush()
        printing_id = _dept_id(db, "PRT")
        production_orders = [
            ProductionOrder(
                production_no=f"CORE-INBOX-LARGE-{suffix}-{index:04}",
                production_type="client_order",
                model_id=model.id,
                status="new",
                planned_quantity=1,
            )
            for index in range(501)
        ]
        db.add_all(production_orders)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=row.id,
                department_id=printing_id,
                operation="printing",
                status="pending",
                planned_output_qty=1,
            )
            for row in production_orders
        ]
        db.add_all(work_orders)
        db.flush()
        work_order_ids = [int(row.id) for row in work_orders]
        db.commit()

        expected_total = baseline + 501
        full_page_rows = _read_all_core_pages(db, "PRT", page_size=100)
        legacy_rows = _legacy_department_rows(db, "PRT")

    actual_ids = {int(row["id"]) for row in full_page_rows if row.get("id") in work_order_ids}
    assert actual_ids == set(work_order_ids)
    assert len(full_page_rows) == expected_total
    legacy_new_ids = {int(row["id"]) for row in legacy_rows if row.get("id") in work_order_ids}
    assert len(legacy_new_ids) == 500
    assert min(work_order_ids) not in legacy_new_ids
    by_id = {int(row["id"]): row for row in full_page_rows if row.get("id") in work_order_ids}
    assert all(by_id[work_order_id]["queue_kind"] == "pending" for work_order_id in legacy_new_ids)


def test_department_order_pages_include_incoming_work_beyond_legacy_two_hundred_row_cap(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        baseline = inbox.department_order_page(db, SimpleNamespace(department_id=None), dept="PRT")["total"]
        model = Model(code=f"CORE-INBOX-INCOMING-{suffix}", name="Large incoming inbox model")
        db.add(model)
        db.flush()
        cutting_id = _dept_id(db, "CUT")
        printing_id = _dept_id(db, "PRT")
        production_orders = [
            ProductionOrder(
                production_no=f"CORE-INBOX-INCOMING-{suffix}-{index:04}",
                production_type="client_order",
                model_id=model.id,
                status="new",
                planned_quantity=1,
            )
            for index in range(205)
        ]
        db.add_all(production_orders)
        db.flush()
        cutting_work = [
            WorkOrder(
                production_order_id=row.id,
                department_id=cutting_id,
                operation="cutting",
                status="completed",
                planned_output_qty=1,
                actual_output_qty=1,
                passed_qty=1,
            )
            for row in production_orders
        ]
        db.add_all(cutting_work)
        db.flush()
        printing_work = [
            WorkOrder(
                production_order_id=row.id,
                department_id=printing_id,
                operation="printing",
                status="pending",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            for row in production_orders
        ]
        db.add_all(printing_work)
        db.flush()
        work_order_ids = [int(row.id) for row in printing_work]
        db.commit()

        legacy_rows = _legacy_department_rows(db, "PRT")
        actual_rows = _read_all_core_pages(db, "PRT", page_size=31)

    legacy_new_ids = [int(row["id"]) for row in legacy_rows if row.get("id") in work_order_ids]
    actual_new_rows = [row for row in actual_rows if row.get("id") in work_order_ids]
    assert len(actual_rows) == baseline + 205
    assert [int(row["id"]) for row in actual_new_rows] == legacy_new_ids
    assert len(legacy_new_ids) == 205
    assert all(row["ready_qty"] == 1 for row in actual_new_rows)
    # The legacy array caps incoming rows at 200. The remaining identities still
    # arrive through pending, but their incoming quantity fields are absent.
    legacy_by_id = {int(row["id"]): row for row in legacy_rows if row.get("id") in work_order_ids}
    omitted_incoming_ids = set(work_order_ids) - {
        int(row["work_order_id"])
        for row in inbox._incoming_work_items(db, "PRT", [printing_id])
    }
    assert len(omitted_incoming_ids) == 5
    assert all("ready_qty" not in legacy_by_id[work_order_id] for work_order_id in omitted_incoming_ids)


def test_department_order_pages_include_bundle_groups_beyond_legacy_two_hundred_cap(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        baseline = inbox.department_order_page(db, SimpleNamespace(department_id=None), dept="SEW")["total"]
        model = Model(code=f"CORE-INBOX-GROUPS-{suffix}", name="Large bundle-group inbox model")
        db.add(model)
        db.flush()
        sewing_id = _dept_id(db, "SEW")
        production_orders = [
            ProductionOrder(
                production_no=f"CORE-INBOX-GROUPS-{suffix}-{index:04}",
                production_type="client_order",
                model_id=model.id,
                status="new",
                planned_quantity=1,
            )
            for index in range(201)
        ]
        db.add_all(production_orders)
        db.flush()
        bundles = [
            Bundle(
                bundle_no=f"CORE-INBOX-GROUPS-{suffix}-{index:04}",
                barcode=f"CORE-INBOX-GROUPS-{suffix}-{index:04}",
                production_order_id=row.id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=1,
                next_department_id=sewing_id,
                sewing_factory_code="MIL",
                status="sent_to_sewing",
            )
            for index, row in enumerate(production_orders)
        ]
        db.add_all(bundles)
        db.flush()
        po_ids = [int(row.id) for row in production_orders]
        db.commit()

        legacy_rows = _legacy_department_rows(db, "SEW")
        actual_rows = _read_all_core_pages(db, "SEW", page_size=29)

    actual_group_rows = [row for row in actual_rows if row.get("production_order_id") in po_ids]
    legacy_group_rows = [row for row in legacy_rows if row.get("production_order_id") in po_ids]
    assert len(actual_rows) == baseline + 201
    assert len(actual_group_rows) == 201
    assert len(legacy_group_rows) == 200


def test_single_page_hydrates_all_bundle_groups_for_merged_work_order_identities(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"CORE-INBOX-PAGE-GROUPS-{suffix}", name="Merged bundle group page")
        db.add(model)
        db.flush()
        sewing_id = _dept_id(db, "SEW")
        production_orders = [
            ProductionOrder(
                production_no=f"CORE-INBOX-PAGE-GROUPS-{suffix}-{index:03}",
                production_type="client_order",
                model_id=model.id,
                status="new",
                planned_quantity=3,
            )
            for index in range(100)
        ]
        db.add_all(production_orders)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=row.id,
                department_id=sewing_id,
                operation="sewing",
                status="pending",
                planned_output_qty=3,
            )
            for row in production_orders
        ]
        db.add_all(work_orders)
        db.flush()
        factories = ("MIL", "BST", "ECO")
        bundles = [
            Bundle(
                bundle_no=f"CORE-INBOX-PAGE-GROUPS-{suffix}-{index:03}-{factory}",
                barcode=f"CORE-INBOX-PAGE-GROUPS-{suffix}-{index:03}-{factory}",
                production_order_id=po.id,
                model_id=model.id,
                color="navy",
                size=factory,
                quantity=1,
                next_department_id=sewing_id,
                sewing_factory_code=factory,
                status="sent_to_sewing",
            )
            for index, po in enumerate(production_orders)
            for factory in factories
        ]
        db.add_all(bundles)
        db.commit()

        page = inbox.department_order_page(
            db,
            SimpleNamespace(department_id=None),
            dept="SEW",
            limit=100,
            offset=0,
        )

    assert page["total"] == 100
    assert len(page["rows"]) == 100
    assert all(row.get("production_order_id") for row in page["rows"])
    assert all(row.get("bundle_count") == 3 for row in page["rows"])


def test_legacy_inbox_can_skip_core_orders_without_skipping_fgs_package_widgets(monkeypatch):
    _enable_inbox_access(monkeypatch)
    with TestSessionLocal() as db:
        expected = inbox.department_inbox(
            db, SimpleNamespace(department_id=None), dept="FGS",
        )

        original_query = db.query

        def reject_core_entity_queries(*entities, **kwargs):
            assert WorkOrder not in entities
            assert Bundle not in entities
            return original_query(*entities, **kwargs)

        db.query = reject_core_entity_queries
        actual = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            include_core_orders=False,
        )

    for key in (
        "incoming_bundles",
        "incoming_bundle_groups",
        "incoming_work_orders",
        "cutting_work_orders",
        "active_work_orders",
        "pending_work_orders",
        "in_progress_work_orders",
        "blocked",
        "overdue",
        "needs_qc",
        "done_today",
    ):
        assert actual[key] == []
    for key in (
        "pending_packages",
        "ready_packages",
        "pending_packages_total",
        "ready_packages_total",
        "ready_to_ship",
        "ready_to_ship_total",
        "replacement_cutting_work",
        "replacement_sewing_work",
    ):
        assert actual[key] == expected[key]
    assert [row["production_order_id"] for row in actual_group_rows[1:]] == [
        row["production_order_id"] for row in legacy_group_rows
    ]
    assert set(row["production_order_id"] for row in actual_group_rows) == set(po_ids)


def test_department_order_pages_apply_factory_alias_before_counting(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"CORE-INBOX-FACTORY-{suffix}", name="Factory inbox model")
        db.add(model)
        db.flush()
        besttex_id = _dept_id(db, "BST")
        expected_po = _production_order(db, int(model.id), f"{suffix}-besttex")
        expected = _work_order(
            db, int(expected_po.id), besttex_id, "sewing", f"{suffix}-bst",
            status="pending",
        )
        db.add(Bundle(
            bundle_no=f"CORE-INBOX-{suffix}-besttex-factory",
            barcode=f"CORE-INBOX-{suffix}-besttex-factory",
            production_order_id=expected_po.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=1,
            next_department_id=besttex_id,
            sewing_factory_code="BESTTEX",
            status="sent_to_sewing",
        ))
        excluded_po = _production_order(db, int(model.id), f"{suffix}-milana")
        excluded = _work_order(
            db, int(excluded_po.id), besttex_id, "sewing", f"{suffix}-mil",
            status="pending",
        )
        db.add(Bundle(
            bundle_no=f"CORE-INBOX-{suffix}-milana-factory",
            barcode=f"CORE-INBOX-{suffix}-milana-factory",
            production_order_id=excluded_po.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=1,
            next_department_id=besttex_id,
            sewing_factory_code="SML",
            status="sent_to_sewing",
        ))
        db.commit()

        expected_rows = _legacy_department_rows(db, "BST")
        actual_rows = _read_all_core_pages(db, "BST", page_size=1)

    assert actual_rows == expected_rows
    actual_ids = {row.get("id") for row in actual_rows}
    assert expected.id in actual_ids
    assert excluded.id not in actual_ids
    assert len(actual_rows) == len(expected_rows)


def test_department_order_completed_page_uses_requested_timezone(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8]
    fixed_now = datetime(2026, 1, 2, 17, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(inbox, "datetime", FrozenDateTime)
    with TestSessionLocal() as db:
        model = Model(code=f"CORE-INBOX-TZ-{suffix}", name="Timezone inbox model")
        db.add(model)
        db.flush()
        printing_id = _dept_id(db, "PRT")
        local_today_po = _production_order(db, int(model.id), f"{suffix}-local-today")
        included = _work_order(
            db,
            int(local_today_po.id),
            printing_id,
            "printing",
            f"{suffix}-included",
            status="completed",
            end_time=datetime(2026, 1, 2, 16, 30, tzinfo=timezone.utc),
        )
        local_yesterday_po = _production_order(db, int(model.id), f"{suffix}-local-yesterday")
        excluded = _work_order(
            db,
            int(local_yesterday_po.id),
            printing_id,
            "printing",
            f"{suffix}-excluded",
            status="completed",
            end_time=datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc),
        )
        db.commit()

        expected = _legacy_department_rows(db, "PRT", tz="Asia/Seoul")
        actual = _read_all_core_pages(db, "PRT", tz="Asia/Seoul", page_size=1)

    assert actual == expected
    actual_ids = {row.get("id") for row in actual}
    assert included.id in actual_ids
    assert excluded.id not in actual_ids
    assert next(row for row in actual if row.get("id") == included.id)["queue_kind"] == "completed"
