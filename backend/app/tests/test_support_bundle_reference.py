"""Bundle-reference reservation remains part of its caller's transaction."""

from copy import deepcopy

import pytest
from sqlalchemy import event

from app.models import numbering_service as numbering
from app.schemas import AuditLog, Bundle, BusinessOrderAlias, SystemSetting
from app.tests.test_support_variant_reference import reference_db  # noqa: F401 - shared dual-database fixture


def aliases(db):
    return db.query(BusinessOrderAlias).filter_by(namespace="BND").order_by(BusinessOrderAlias.id).all()


def test_bundle_reference_keeps_lock_flush_reservation_and_caller_commit(reference_db, monkeypatch):
    db = reference_db
    locks, flushes, commits = [], [], []
    original_lock = numbering._acquire_numbering_lock

    def lock(supplied, resource):
        locks.append((supplied, resource))
        return original_lock(supplied, resource)

    monkeypatch.setattr(numbering, "_acquire_numbering_lock", lock)
    event.listen(db, "before_flush", lambda *args: flushes.append(True))
    event.listen(db, "after_commit", lambda *args: commits.append(True))
    db.add(SystemSetting(key="bundle_pending_participant", value_json={"keep": True}))
    assert numbering.next_bundle_no(db) == "BND-0001"
    assert numbering.next_bundle_no(db) == "BND-0002"
    assert [(row.entity_id, row.reference, row.canonical_reference) for row in aliases(db)] == [
        (0, "BND-0001", "BND-0001"), (0, "BND-0002", "BND-0002"),
    ]
    assert db.query(Bundle).count() == db.query(AuditLog).count() == 0
    assert len(flushes) == 2 and not commits
    assert locks == [(db, "bundles:bundle_no:BND:compact")] * 2
    db.commit()
    assert commits == [True]
    db.expire_all()
    assert len(aliases(db)) == 2
    assert db.query(SystemSetting).filter_by(key="bundle_pending_participant").one().value_json == {"keep": True}


@pytest.mark.parametrize("existing", [False, True])
def test_bundle_outer_rollback_restores_reference_and_pending_participant(reference_db, existing):
    db = reference_db
    if existing:
        db.add(BusinessOrderAlias(namespace="BND", entity_id=15,
                                  reference="BND-0009", canonical_reference="BND-0009"))
        db.commit()
    before = [(row.entity_id, row.reference, row.canonical_reference) for row in aliases(db)]
    db.add(SystemSetting(key="bundle_rollback_participant", value_json={"rollback": True}))
    expected = "BND-0010" if existing else "BND-0001"
    assert numbering.next_bundle_no(db) == expected
    assert db.query(SystemSetting).filter_by(key="bundle_rollback_participant").count() == 1
    db.rollback()
    assert [(row.entity_id, row.reference, row.canonical_reference) for row in aliases(db)] == before
    assert db.query(SystemSetting).filter_by(key="bundle_rollback_participant").count() == 0
    assert numbering.next_bundle_no(db) == expected


@pytest.mark.parametrize("reference,canonical,expected", [
    ("BND-9999", "BND-0001", "BND-10000"),
    ("BND-2026-009999", "BND-0042", "BND-0043"),
    ("custom legacy", "BND-0100", "BND-0101"),
])
def test_bundle_advances_both_alias_columns_and_keeps_other_namespaces(reference_db, reference, canonical, expected):
    db = reference_db
    db.add_all([
        BusinessOrderAlias(namespace="BND", entity_id=7, reference=reference, canonical_reference=canonical),
        BusinessOrderAlias(namespace="SO", entity_id=8, reference="BND-99999", canonical_reference="BND-99999"),
    ])
    db.commit()
    before = deepcopy([(row.entity_id, row.reference, row.canonical_reference) for row in aliases(db)])
    assert numbering.next_bundle_no(db) == expected
    assert [(row.entity_id, row.reference, row.canonical_reference) for row in aliases(db)[:-1]] == before
    reserved = aliases(db)[-1]
    assert (reserved.entity_id, reserved.reference, reserved.canonical_reference) == (0, expected, expected)
    assert db.query(BusinessOrderAlias).filter_by(namespace="SO").one().reference == "BND-99999"


def test_bundle_flush_failure_propagates_without_committing(reference_db):
    db = reference_db
    commits = []
    event.listen(db, "after_commit", lambda *args: commits.append(True))

    def fail_flush(*args):
        raise RuntimeError("Synthetic bundle reservation flush failure")

    event.listen(db, "before_flush", fail_flush)
    try:
        with pytest.raises(RuntimeError, match="Synthetic bundle reservation flush failure"):
            numbering.next_bundle_no(db)
    finally:
        event.remove(db, "before_flush", fail_flush)
    assert commits == []
    db.rollback()
    assert aliases(db) == []
    assert numbering.next_bundle_no(db) == "BND-0001"
