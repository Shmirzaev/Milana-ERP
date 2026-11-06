"""Mutation challenges for the read-only reviewer tool; no application/DB imports."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "boundary_audit", Path(__file__).parents[1] / "scripts/audit_refactor_boundaries.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def rules(source, path="api/routes/example.py", strict=False):
    return {f["rule"] for f in MODULE.analyze(source, path, schema_writes=strict)}


def test_thin_route_passes_but_insert_and_commit_mutation_is_detected():
    assert not rules("def create(db, payload):\n return service.create(db, payload)\n")
    assert rules("def create(db, payload):\n db.add(payload)\n db.commit()\n") == {"route-write", "route-transaction"}


def test_query_update_and_annotated_session_alias_are_detected():
    assert "route-write" in rules("def change(store: Session):\n store.query(Item).filter(Item.id == 1).update({'x': 1})\n")


def test_response_header_update_is_not_a_database_write():
    assert not rules("def page(db, response):\n response.headers.update({'x': 'y'})\n")


def test_service_and_relative_import_cannot_reach_route_helpers():
    assert "reverse-route-import" in rules("from app.api.routes.sales import hidden", "models/sales/thing.py")
    assert "reverse-route-import" in rules("from ..api.routes.sales import hidden", "models/thing.py")


def test_schema_cannot_import_service_but_can_own_persistence():
    assert "contract-imports-service" in rules("from app.models.sales import orders_service", "schemas/sales/sales.py")
    assert not rules("def insert(db, row):\n db.add(row)\n db.flush()\n", "schemas/sales/sales.py", True)


def test_strict_service_write_target_keeps_transaction_review_distinct():
    source = "def create(db, row):\n db.add(row)\n db.commit()\n"
    assert not rules(source, "models/sales/orders_service.py")
    assert rules(source, "models/sales/orders_service.py", True) == {"service-write-outside-schema", "transaction-owner-review"}


def test_unresolved_execute_and_syntax_cannot_disappear_from_report():
    assert "sql-execution-review" in rules("def report(db, sql):\n return db.execute(sql)\n")
    assert "syntax" in rules("def broken(: pass")


def test_session_info_transaction_sets_are_not_persistence():
    source = "def queue(db, transaction):\n db.info.setdefault('committed', set()).add(transaction)\n db.info.setdefault('rolled_back', set()).add(transaction)\n db.info.update({'flag': True})\n"
    assert not rules(source, "models/audit_service.py", True)


def test_real_insert_alongside_metadata_update_is_still_detected():
    source = "def finalize(db, entries, transaction):\n db.info.setdefault('committed', set()).add(transaction)\n db.add_all(entries)\n db.flush()\n"
    findings = MODULE.analyze(source, "models/audit_service.py", schema_writes=True)
    errors = [f for f in findings if f['severity'] == 'error']
    assert [(f['line'], f['rule']) for f in errors] == [(3, 'service-write-outside-schema')]


def test_metadata_used_as_query_argument_does_not_hide_real_update_or_delete():
    source = "def change(store: Session):\n store.query(Item).filter(Item.id == store.info['item']).update({'x': 1})\n store.query(Item).filter(Item.id == store.info['item']).delete()\n"
    findings = MODULE.analyze(source, "models/example.py", schema_writes=True)
    assert len([f for f in findings if f['rule'] == 'service-write-outside-schema']) == 2
