from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import BusinessOrderAlias
from app.services import numbering
from app.services.numbering import next_bundle_no


@pytest.fixture(scope="module")
def numbering_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Numbering races require loopback PostgreSQL without connection overrides")
    schema = f"numbering_races_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_bundle_numbers_serialize_across_9999(numbering_postgres_sessions):
    sessions, engine = numbering_postgres_sessions
    with sessions.begin() as db:
        db.add(BusinessOrderAlias(
            namespace="BND",
            entity_id=9999,
            reference="BND-9999",
            canonical_reference="BND-9999",
        ))

    ready: Queue[int] = Queue()
    start = Event()

    def generate() -> str:
        with sessions() as db:
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            ready.put(pid)
            assert start.wait(10)
            reference = next_bundle_no(db)
            db.commit()
            return reference

    resource = "bundles:bundle_no:BND:compact"
    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
            {"namespace": numbering._NUMBERING_LOCK_NAMESPACE, "resource": resource},
        )
        futures = [workers.submit(generate) for _ in range(2)]
        pids = [ready.get(timeout=10) for _ in futures]
        start.set()
        deadline = monotonic() + 10
        while monotonic() < deadline:
            blockers = [
                holder.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                ).scalar_one()
                for pid in pids
            ]
            if all(blockers):
                break
            sleep(0.02)
        else:
            pytest.fail("Both numbering transactions should wait for the namespace lock")
        holder.commit()
        references = sorted(future.result(timeout=10) for future in futures)

    assert references == ["BND-10000", "BND-10001"]
    with sessions() as db:
        reservations = db.query(BusinessOrderAlias).filter(
            BusinessOrderAlias.namespace == "BND",
            BusinessOrderAlias.reference.in_(references),
        ).order_by(BusinessOrderAlias.reference).all()
        assert [row.reference for row in reservations] == references
        assert all(row.entity_id == 0 for row in reservations)
