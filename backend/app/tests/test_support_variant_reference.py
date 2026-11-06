"""Variant-reference participant: preserve previews, reservation and caller commit."""

from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core import model_search  # noqa: F401 - SQLite normalizer registration
from app.db.base import Base
from app.models import numbering_service as numbering
from app.schemas import Model, SystemSetting
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(params=["sqlite", "postgres"])
def reference_db(request):
    target = None
    if request.param == "sqlite":
        engine = create_engine("sqlite:///:memory:")
    else:
        try:
            instance = load_approved_instance()
        except ApprovedInstanceUnavailable as exc:
            require_or_skip(exc)
        target = create_target_database(instance)
        engine = target_engine(target, options="-ctimezone=UTC")
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            yield db
            db.rollback()
    finally:
        if target is not None:
            finalize_target(target, engine)
        else:
            engine.dispose()


def variant_setting(db):
    return db.query(SystemSetting).filter_by(key=numbering.MODEL_VARIANT_SETTING_KEY).one_or_none()


def test_variant_preview_and_reservations_keep_lock_flush_and_caller_commit(reference_db, monkeypatch):
    db = reference_db
    locks, flushes, commits = [], [], []
    original_lock = numbering._acquire_numbering_lock

    def lock(supplied, resource):
        locks.append((supplied, resource))
        return original_lock(supplied, resource)

    monkeypatch.setattr(numbering, "_acquire_numbering_lock", lock)
    event.listen(db, "before_flush", lambda *args: flushes.append(True))
    event.listen(db, "after_commit", lambda *args: commits.append(True))
    assert numbering.next_model_variant_no(db) == "V-6455"
    assert variant_setting(db) is None
    assert locks == flushes == commits == []
    assert numbering.next_model_variant_no(db, reserve=True) == "V-6455"
    first = variant_setting(db)
    assert first.id is not None and first.value_json == {"last_assigned": 6455}
    assert numbering.next_model_variant_no(db, reserve=True) == "V-6456"
    assert variant_setting(db) is first
    assert first.value_json == {"last_assigned": 6456}
    assert len(flushes) == 2 and not commits
    assert locks == [(db, numbering.MODEL_VARIANT_SETTING_KEY)] * 2
    db.commit()
    assert commits == [True]
    db.expire_all()
    assert variant_setting(db).value_json == {"last_assigned": 6456}


@pytest.mark.parametrize("existing", [False, True])
def test_variant_outer_rollback_restores_counter_and_other_pending_work(reference_db, existing):
    db = reference_db
    original = {"last_assigned": 6500, "legacy": {"keep_until_reserved": True}}
    if existing:
        db.add(SystemSetting(key=numbering.MODEL_VARIANT_SETTING_KEY, value_json=deepcopy(original)))
        db.commit()
    db.add(Model(code="VARIANT-ROLLBACK-PARTICIPANT", name="Pending model"))
    expected = "V-6501" if existing else "V-6455"
    assert numbering.next_model_variant_no(db, reserve=True) == expected
    assert db.query(Model).count() == 1
    db.rollback()
    assert db.query(Model).count() == 0
    assert (variant_setting(db).value_json if variant_setting(db) else None) == (original if existing else None)
    assert numbering.next_model_variant_no(db, reserve=True) == expected


@pytest.mark.parametrize("value,expected", [
    (None, 6455), ([], 6455), ({}, 6455),
    ({"last_assigned": "legacy"}, 6455),
    ({"last_assigned": -1, "extra": "discarded"}, 6455),
    ({"last_assigned": "6500", "extra": {"discarded": True}}, 6501),
])
def test_variant_legacy_counter_fallback_and_replacement_are_unchanged(reference_db, value, expected):
    db = reference_db
    db.add(SystemSetting(key=numbering.MODEL_VARIANT_SETTING_KEY, value_json=deepcopy(value)))
    db.commit()
    assert numbering.next_model_variant_no(db) == f"V-{expected}"
    assert variant_setting(db).value_json == value
    assert numbering.next_model_variant_no(db, reserve=True) == f"V-{expected}"
    assert variant_setting(db).value_json == {"last_assigned": expected}


def test_variant_skips_legacy_codes_and_metadata_without_following_outliers(reference_db):
    db = reference_db
    db.add_all([
        Model(code="XJ3200-06455", name="Legacy variant suffix"),
        Model(code="SPECIAL", name="Explicit variant", details_json={"general": {"variant_no": "V6456"}}),
        Model(code="PJ1164-43891", name="Historical outlier"),
    ])
    db.commit()
    assert numbering.next_model_variant_no(db) == "V-6457"
    assert numbering.next_model_variant_no(db, reserve=True) == "V-6457"
    assert numbering.next_model_variant_no(db) == "V-6458"
