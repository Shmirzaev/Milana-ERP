"""Pure operation tests: no ERP imports, engines, application or database.

Execute the actual service/helper function AST with controlled collaborators.
These tests prove delegation, refusal order and exception/transaction boundaries;
they do not replace PostgreSQL cascade/rollback or signed-route/UI verification.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


APP = Path(__file__).resolve().parents[1]


def load_function(relative, name, collaborators):
    tree = ast.parse((APP / relative).read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    isolated = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    namespace = dict(collaborators)
    exec(compile(ast.fix_missing_locations(isolated), str(APP / relative), "exec"), namespace)
    return namespace[name]


class Refusal(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


class InjectedFailure(Exception):
    pass


class Column:
    def __init__(self, model):
        self.model = model

    def __eq__(self, value):
        return self.model, value


SalesOrder = type("SalesOrder", (), {})
ProductionOrder = type("ProductionOrder", (), {"sales_order_id": Column("ProductionOrder")})
Shipment = type("Shipment", (), {"sales_order_id": Column("Shipment")})
StockReservation = type("StockReservation", (), {"sales_order_id": Column("StockReservation")})


class Query:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, expression):
        if expression != (self.model.__name__, 17):
            raise AssertionError("reference lookup changed its order ID or model")
        return self

    def first(self):
        self.db.events.append(self.model.__name__)
        return object() if self.model.__name__ in self.db.references else None


class SessionDouble:
    def __init__(self, status="draft", *, exists=True, references=(), failure=None):
        self.order = SimpleNamespace(id=17, order_no="SO-DELETE-17", status=status) if exists else None
        self.references = set(references)
        self.failure = failure
        self.events = []
        self.deleted = []

    def get(self, model, identifier):
        if model is not SalesOrder or identifier != 17:
            raise AssertionError("order lookup changed its model or ID")
        self.events.append("get")
        return self.order

    def query(self, model):
        return Query(self, model)

    def delete(self, row):
        self.events.append("delete")
        if self.failure == "delete":
            raise InjectedFailure("delete")
        self.deleted.append(row)

    def commit(self):
        self.events.append("commit")
        if self.failure == "commit":
            raise InjectedFailure("commit")

    def flush(self):
        raise AssertionError("extraction added a flush")

    def rollback(self):
        raise AssertionError("extraction took over caller rollback")


def operation(db):
    actor = object()
    writes = []
    audits = []
    helper = load_function("schemas/sales/sales_order_persistence.py", "delete_sales_order_row", {})

    def writer(supplied, row):
        writes.append((supplied, row))
        return helper(supplied, row)

    def audit(supplied, acting, action, entity, identifier, **kwargs):
        supplied.events.append("audit")
        audits.append((supplied, acting, action, entity, identifier, kwargs))
        if db.failure == "audit":
            raise InjectedFailure("audit")

    service = load_function("models/sales/orders_service.py", "delete_sales_order", {
        "SalesOrder": SalesOrder,
        "ProductionOrder": ProductionOrder,
        "Shipment": Shipment,
        "StockReservation": StockReservation,
        "HTTPException": Refusal,
        "delete_sales_order_row": writer,
        "log_action": audit,
    })
    return lambda: service(17, db, actor), actor, writes, audits


class SalesDeleteOperationTests(unittest.TestCase):
    def test_allowed_states_delegate_same_row_session_then_audit_and_commit(self):
        for status in ("draft", "cancelled"):
            with self.subTest(status=status):
                db = SessionDouble(status)
                delete, actor, writes, audits = operation(db)
                self.assertIsNone(delete())
                self.assertEqual(writes, [(db, db.order)])
                self.assertEqual(db.deleted, [db.order])
                self.assertEqual(audits, [(
                    db, actor, "delete", "SalesOrder", 17,
                    {"new_value": {"order_no": "SO-DELETE-17"}},
                )])
                self.assertEqual(db.events, [
                    "get", "ProductionOrder", "Shipment", "StockReservation", "delete", "audit", "commit",
                ])

    def test_missing_order_refuses_before_references_writer_audit_or_commit(self):
        db = SessionDouble(exists=False)
        delete, _, writes, audits = operation(db)
        with self.assertRaises(Refusal) as failure:
            delete()
        self.assertEqual((failure.exception.status_code, failure.exception.detail), (404, "Sales order not found"))
        self.assertEqual(db.events, ["get"])
        self.assertEqual((writes, audits), ([], []))

    def test_non_deletable_states_refuse_before_reference_checks_or_effects(self):
        for status in (
            "pending_sales_approval", "confirmed", "planning", "planning_approved",
            "in_production", "production", "cutting", "printing", "sewing", "packaging",
            "storage", "ready_to_ship", "ready", "reserved", "shipped", "delivered", "closed",
            "completed", "DRAFT", "unknown", None,
        ):
            with self.subTest(status=status):
                db = SessionDouble(status, references=("ProductionOrder",))
                delete, _, writes, audits = operation(db)
                with self.assertRaises(Refusal) as failure:
                    delete()
                self.assertEqual((failure.exception.status_code, failure.exception.detail), (
                    409, "Only draft or cancelled sales orders can be deleted",
                ))
                self.assertEqual(db.events, ["get"])
                self.assertEqual((writes, audits), ([], []))

    def test_reference_refusals_preserve_precedence_and_do_not_write(self):
        kinds = ("ProductionOrder", "Shipment", "StockReservation")
        messages = (
            "Sales order already has linked production orders",
            "Sales order already has linked shipments",
            "Sales order already has stock reservations",
        )
        for mask in range(1, 8):
            references = {kind for index, kind in enumerate(kinds) if mask & (1 << index)}
            with self.subTest(references=references):
                db = SessionDouble(references=references)
                delete, _, writes, audits = operation(db)
                first = next(index for index, kind in enumerate(kinds) if kind in references)
                with self.assertRaises(Refusal) as failure:
                    delete()
                self.assertEqual((failure.exception.status_code, failure.exception.detail), (409, messages[first]))
                self.assertEqual(db.events, ["get", *kinds[:first + 1]])
                self.assertEqual((writes, audits, db.deleted), ([], [], []))

    def test_delete_audit_and_commit_failures_propagate_without_new_flush_or_rollback(self):
        events = ["get", "ProductionOrder", "Shipment", "StockReservation", "delete", "audit", "commit"]
        for point in ("delete", "audit", "commit"):
            with self.subTest(point=point):
                db = SessionDouble(failure=point)
                delete, _, writes, audits = operation(db)
                with self.assertRaisesRegex(InjectedFailure, point):
                    delete()
                self.assertEqual(db.events, events[:events.index(point) + 1])
                self.assertEqual(writes, [(db, db.order)])
                self.assertEqual(len(audits), 0 if point == "delete" else 1)

    def test_schema_helper_only_marks_the_supplied_row(self):
        db = SessionDouble()
        helper = load_function("schemas/sales/sales_order_persistence.py", "delete_sales_order_row", {})
        self.assertIsNone(helper(db, db.order))
        self.assertEqual(db.events, ["delete"])
        self.assertEqual(db.deleted, [db.order])


if __name__ == "__main__":
    unittest.main()
