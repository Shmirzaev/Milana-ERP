"""FG numbering on an approved, freshly migrated disposable PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import numbering_service as numbering
from app.schemas import Model, SystemSetting
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture
def fg_pg_sessions():
    """Each case owns its database, including generated model-family columns."""
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        ini = Path(__file__).resolve().parents[2] / "alembic.ini"
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(ini)), "head")
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        finalize_target(target, engine)


def test_pg_fg_starts_at_202001_and_preview_preserves_unrelated_streams(fg_pg_sessions):
    sessions, _ = fg_pg_sessions
    with sessions() as db:
        before = db.query(SystemSetting).count()
        assert numbering.next_model_no(db, "FG") == "FG202001"
        assert numbering.next_model_no(db, "fg") == "FG202001"
        assert numbering.next_model_no(db, "XJ") == "XJ3201"
        assert numbering.next_model_no(db, "XD") == "XD109001"
        assert db.query(SystemSetting).count() == before
        assert numbering.next_model_no(db, "FG", reserve=True) == "FG202001"
        db.add(Model(code="FG202001", name="FG PostgreSQL first model"))
        db.commit()
    with sessions() as db:
        assert numbering.next_model_no(db, "FG") == "FG202002"
        assert numbering.next_model_no(db, "XJ") == "XJ3201"
        assert numbering.next_model_no(db, "XD") == "XD109001"
        setting = db.query(SystemSetting).filter_by(key=numbering.MODEL_NUMBER_SETTING_KEY).one()
        assert setting.value_json == {"last_assigned": {"FG": 202001}}


def test_pg_parallel_fg_reservations_wait_and_commit_distinct_first_numbers(fg_pg_sessions):
    sessions, engine = fg_pg_sessions
    ready = Queue()
    start = Event()

    def reserve():
        with sessions() as db:
            # Both operators saw the same preview before either reserved it.
            assert numbering.next_model_no(db, "FG") == "FG202001"
            ready.put(db.scalar(sa.text("SELECT pg_backend_pid()")))
            assert start.wait(10)
            reference = numbering.next_model_no(db, "FG", reserve=True)
            db.add(Model(code=reference, name="FG PostgreSQL concurrent model"))
            db.commit()
            return reference

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(sa.text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
                       {"namespace": numbering._NUMBERING_LOCK_NAMESPACE,
                        "resource": numbering.MODEL_NUMBER_SETTING_KEY})
        futures = [workers.submit(reserve) for _ in range(2)]
        pids = [ready.get(timeout=10) for _ in futures]
        start.set()
        try:
            deadline = monotonic() + 10
            waiting = False
            while monotonic() < deadline:
                with engine.connect() as connection:
                    waiting = all(connection.scalar(sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                                    {"pid": pid}) for pid in pids)
                if waiting:
                    break
                sleep(0.02)
            assert waiting, "Both FG reservations must contend on the advisory lock"
        finally:
            holder.rollback()
        references = sorted(future.result(timeout=15) for future in futures)
    assert references == ["FG202001", "FG202002"]
    with sessions() as db:
        assert [row.code for row in db.query(Model).filter(Model.code.in_(references)).order_by(Model.code)] == references
        assert numbering.next_model_no(db, "FG") == "FG202003"
        assert numbering.next_model_no(db, "XJ") == "XJ3201"
        assert numbering.next_model_no(db, "XD") == "XD109001"


def test_pg_fg_stale_preview_skips_code_and_metadata_families_without_following_outlier(fg_pg_sessions):
    sessions, _ = fg_pg_sessions
    with sessions() as stale:
        assert numbering.next_model_no(stale, "FG") == "FG202001"
        with sessions.begin() as writer:
            writer.add_all([
                Model(code="FG202001-V-9000", name="FG occupied variant family"),
                Model(code="FG-EXPLICIT-FAMILY", name="FG metadata family",
                      details_json={"general": {"model_no": "FG202002"}}),
                Model(code="FG999999", name="FG historical outlier"),
            ])
        assert numbering.next_model_no(stale, "FG", reserve=True) == "FG202003"
        stale.add(Model(code="FG202003", name="FG after stale preview"))
        stale.commit()
    with sessions() as db:
        assert numbering.next_model_no(db, "FG") == "FG202004"
        assert numbering.next_model_no(db, "XJ") == "XJ3201"
        assert numbering.next_model_no(db, "XD") == "XD109001"


@pytest.mark.parametrize("existing", [False, True])
def test_pg_fg_outer_rollback_preserves_number_and_unrelated_counters(fg_pg_sessions, existing):
    sessions, _ = fg_pg_sessions
    prior = {"last_assigned": {"XJ": 3500, "XD": 110000}, "note": {"keep": [1, 2]}}
    if existing:
        with sessions.begin() as db:
            db.add(SystemSetting(key=numbering.MODEL_NUMBER_SETTING_KEY, value_json=prior))
    with sessions() as db:
        assert numbering.next_model_no(db, "FG", reserve=True) == "FG202001"
        db.add(Model(code="FG202001", name="FG transaction to roll back"))
        db.flush()
        assert db.query(Model).filter_by(code="FG202001").count() == 1
        db.rollback()
    with sessions() as db:
        assert db.query(Model).filter_by(code="FG202001").count() == 0
        setting = db.query(SystemSetting).filter_by(key=numbering.MODEL_NUMBER_SETTING_KEY).one_or_none()
        assert (setting.value_json if setting else None) == (prior if existing else None)
        assert numbering.next_model_no(db, "FG", reserve=True) == "FG202001"
        db.add(Model(code="FG202001", name="FG retried committed transaction"))
        db.commit()
    with sessions() as db:
        assert numbering.next_model_no(db, "FG") == "FG202002"
        expected = {**prior, "last_assigned": {**prior["last_assigned"], "FG": 202001}} if existing else {"last_assigned": {"FG": 202001}}
        assert db.query(SystemSetting).filter_by(key=numbering.MODEL_NUMBER_SETTING_KEY).one().value_json == expected
        assert numbering.next_model_no(db, "XJ") == ("XJ3501" if existing else "XJ3201")
        assert numbering.next_model_no(db, "XD") == ("XD110001" if existing else "XD109001")
