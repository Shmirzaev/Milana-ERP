"""PERF40: uploads decoded images, wrote files and ran SQL on the event loop.

`store_uploaded_image` was an ``async def`` that only awaited the body read, so
Pillow decoding, the WebP re-encode, the atomic disk writes, the thumbnail
builds and the route's own SQL all ran inline on the event loop thread. One
20 MiB upload stalled every other request in the worker for the whole
conversion, and nothing bounded how many uploads one process would admit at
once, cancel a half-finished upload, or remove a replaced logo.

The central proof here is a heartbeat: a periodic coroutine counts how many
times the event loop got control while uploads were in flight. Blocking the
loop collapses that count to ~0, so a test that passes on the unfixed code
would prove nothing. The safety half is proved separately: the admission
bound rejects the excess, a cancelled request leaves no orphan row or partial
file, a replaced logo's files are removed, and the catalog scope/employee
factory is re-verified on the worker's own session at the moment of the write.

The route-level proofs need real PostgreSQL: the writes happen in
worker-owned Sessions on the request's engine, and SQLite's locking and
single-connection behaviour prove nothing about that hand-off. Set
STABILIZATION_POSTGRES_URL to run them.
"""

import asyncio
import os
import time
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Timer, get_ident
from uuid import uuid4

import pytest
from anyio import CapacityLimiter
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import catalog as catalog_routes
from app.api.routes import hr_workspace as hr_routes
from app.core.config import settings
from app.db.base import Base
from app.models import (
    AuditLog,
    Employee,
    HrEmployeeDocument,
    Model,
    ModelImage,
    User,
)
from app.services import image_storage


# --- helpers ---------------------------------------------------------------


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    stream = BytesIO()
    with Image.new("RGB", size, "blue") as image:
        image.save(stream, format="PNG")
    return stream.getvalue()


def _upload(filename: str = "synthetic.png") -> UploadFile:
    return UploadFile(file=BytesIO(_png_bytes()), filename=filename)


def _document_upload(filename: str = "employment.txt") -> UploadFile:
    return UploadFile(file=BytesIO(b"employment contract bytes"), filename=filename)


def _require_postgres_url() -> str:
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL upload-lifecycle coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Upload lifecycle tests require a loopback PostgreSQL URL without connection overrides")
    return raw_url


@pytest.fixture(scope="module")
def upload_postgres():
    url = _require_postgres_url()
    schema = f"perf40_upload_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=20000"},
        pool_size=6,
        max_overflow=0,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables: set = set()
        pending = [
            AuditLog.__table__,
            Model.__table__,
            ModelImage.__table__,
            User.__table__,
            Employee.__table__,
            HrEmployeeDocument.__table__,
        ]
        while pending:
            table = pending.pop()
            if table in tables:
                continue
            tables.add(table)
            pending.extend(fk.column.table for fk in table.foreign_keys)
        Base.metadata.create_all(engine, tables=list(tables))
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed_model(sessions, *, scope: str = "standard") -> tuple[int, int]:
    marker = uuid4().hex
    with sessions.begin() as db:
        user = User(
            name=f"PERF40 uploader {marker}",
            email=f"perf40-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["*"],
            is_active=True,
        )
        db.add(user)
        db.flush()
        model = Model(
            code=f"PERF40-{marker}",
            name=f"PERF40 model {marker}",
            catalog_scope=scope,
            created_by=user.id,
        )
        db.add(model)
        db.flush()
        return int(model.id), int(user.id)


def _seed_employee(sessions, *, factory: str = "MIL") -> tuple[int, int]:
    marker = uuid4().hex
    with sessions.begin() as db:
        user = User(
            name=f"PERF40 hr {marker}",
            email=f"perf40-hr-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["hr.employees", "*"],
            is_active=True,
        )
        db.add(user)
        db.flush()
        employee = Employee(
            factory_code=factory,
            employee_no=f"HR{marker[:8]}",
            full_name=f"PERF40 employee {marker}",
            hr_profile_json={},
        )
        db.add(employee)
        db.flush()
        return int(employee.id), int(user.id)


# --- the central claim: the event loop stays free ----------------------------


def test_upload_work_keeps_the_event_loop_responsive(tmp_path, monkeypatch, capsys):
    """A heartbeat must keep ticking while uploads are in flight."""
    loop_thread = get_ident()
    on_loop_thread: list[str] = []
    written: list[str] = []
    real_convert = image_storage.convert_image_to_webp
    real_write = image_storage._atomic_write
    real_thumbnails = image_storage.prebuild_webp_thumbnails
    # Stand-in for real decode/re-encode cost, which is what blocked the loop.
    block_seconds = 0.15

    def slow_convert(content):
        if get_ident() == loop_thread:
            on_loop_thread.append("convert_image_to_webp")
        time.sleep(block_seconds)
        return real_convert(content)

    def tracked_write(path, data):
        if get_ident() == loop_thread:
            on_loop_thread.append("_atomic_write")
        written.append(path.name)
        return real_write(path, data)

    def tracked_thumbnails(*args, **kwargs):
        if get_ident() == loop_thread:
            on_loop_thread.append("prebuild_webp_thumbnails")
        return real_thumbnails(*args, **kwargs)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", slow_convert)
    monkeypatch.setattr(image_storage, "_atomic_write", tracked_write)
    monkeypatch.setattr(image_storage, "prebuild_webp_thumbnails", tracked_thumbnails)

    async def run():
        uploads = [_upload() for _ in range(3)]
        ticks = 0
        finished = False

        async def heartbeat():
            nonlocal ticks
            while not finished:
                await asyncio.sleep(0.005)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        started = time.perf_counter()
        try:
            results = await asyncio.gather(*[
                image_storage.store_uploaded_image(
                    upload,
                    target_dir=str(tmp_path),
                    file_url_base="/storage/test",
                    name_prefix="synthetic",
                    max_bytes=4096,
                    prebuild_thumbnails=True,
                )
                for upload in uploads
            ])
        finally:
            finished = True
            await beat
            for upload in uploads:
                await upload.close()
        return results, ticks, time.perf_counter() - started

    results, ticks, elapsed = asyncio.run(run())
    with capsys.disabled():
        print(f"\nheartbeat ticks={ticks} elapsed={elapsed:.3f}s blocking_calls_on_loop={len(on_loop_thread)}")

    assert len({result.file_name for result in results}) == 3
    for result in results:
        assert Path(result.absolute_path).is_file()
        assert len(list((tmp_path / "_thumbs").glob(f"*{result.file_name}.webp"))) == 2
    # The blocking window is ~0.45s here, so a free loop ticks ~90 times.
    assert ticks >= 30, (
        f"event loop was blocked: only {ticks} heartbeat ticks in {elapsed:.3f}s "
        f"(expected >= 30 while 3 uploads x {block_seconds}s of decode ran)"
    )
    assert not on_loop_thread, f"blocking upload work ran on the event loop thread: {sorted(set(on_loop_thread))}"


# --- admission control ------------------------------------------------------


def test_admission_bound_caps_concurrent_upload_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(image_storage, "UPLOAD_PROCESSING_LIMITER", CapacityLimiter(1))
    real_convert = image_storage.convert_image_to_webp
    guard = Lock()
    active = peak = 0

    def counting_convert(content):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            return real_convert(content)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(image_storage, "convert_image_to_webp", counting_convert)

    async def run():
        uploads = [_upload() for _ in range(3)]
        try:
            return await asyncio.gather(*[
                image_storage.store_uploaded_image(
                    upload,
                    target_dir=str(tmp_path),
                    file_url_base="/storage/test",
                    name_prefix="synthetic",
                    max_bytes=4096,
                )
                for upload in uploads
            ])
        finally:
            for upload in uploads:
                await upload.close()

    results = asyncio.run(run())

    assert peak == 1, f"{peak} uploads were processed at once; the bound of 1 was not applied"
    assert len({result.file_name for result in results}) == 3


def test_upload_beyond_the_bound_and_queue_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(image_storage, "UPLOAD_PROCESSING_LIMITER", CapacityLimiter(1))
    monkeypatch.setattr(image_storage, "UPLOAD_MAX_QUEUED", 0)
    real_convert = image_storage.convert_image_to_webp
    entered = Event()
    release = Event()

    def gated_convert(content):
        entered.set()
        release.wait(5)
        return real_convert(content)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", gated_convert)

    async def run():
        first = _upload()
        second = _upload()
        try:
            task = asyncio.create_task(image_storage.store_uploaded_image(
                first, target_dir=str(tmp_path), file_url_base="/storage/test",
                name_prefix="synthetic", max_bytes=4096,
            ))
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "the first upload never reached the blocking section"
            with pytest.raises(HTTPException) as rejected:
                await image_storage.store_uploaded_image(
                    second, target_dir=str(tmp_path), file_url_base="/storage/test",
                    name_prefix="synthetic", max_bytes=4096,
                )
            release.set()
            return rejected.value, await task
        finally:
            release.set()
            for upload in (first, second):
                await upload.close()

    rejected, stored = asyncio.run(run())

    assert rejected.status_code == 429, rejected.detail
    assert Path(stored.absolute_path).is_file()
    # Only the admitted upload produced a file.
    assert len(list(tmp_path.glob("*.webp"))) == 1


def test_admission_bounds_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "4")
    monkeypatch.setenv("UPLOAD_MAX_QUEUED_PER_PROCESS", "12")
    assert image_storage._upload_concurrency_from_environment() == 4
    assert image_storage._queued_upload_bound_from_environment() == 12

    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "0")
    with pytest.raises(RuntimeError, match="UPLOAD_MAX_CONCURRENCY_PER_PROCESS"):
        image_storage._upload_concurrency_from_environment()
    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "nope")
    with pytest.raises(RuntimeError, match="UPLOAD_MAX_CONCURRENCY_PER_PROCESS"):
        image_storage._upload_concurrency_from_environment()

    monkeypatch.setenv("UPLOAD_MAX_QUEUED_PER_PROCESS", "-1")
    with pytest.raises(RuntimeError, match="UPLOAD_MAX_QUEUED_PER_PROCESS"):
        image_storage._queued_upload_bound_from_environment()
    monkeypatch.setenv("UPLOAD_MAX_QUEUED_PER_PROCESS", "many")
    with pytest.raises(RuntimeError, match="UPLOAD_MAX_QUEUED_PER_PROCESS"):
        image_storage._queued_upload_bound_from_environment()


# --- cancellation cleanup at the service level -------------------------------


def _stored_files(root) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_cancelled_upload_leaves_no_partial_file(tmp_path, monkeypatch):
    """A dropped connection mid-conversion must not strand the stored file."""
    real_convert = image_storage.convert_image_to_webp
    real_write = image_storage._atomic_write
    written: list[str] = []
    entered = Event()
    release = Event()

    def gated_convert(content):
        entered.set()
        release.wait(5)
        return real_convert(content)

    def tracked_write(path, data):
        written.append(path.name)
        return real_write(path, data)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", gated_convert)
    monkeypatch.setattr(image_storage, "_atomic_write", tracked_write)

    async def run():
        upload = _upload()
        try:
            task = asyncio.create_task(image_storage.store_uploaded_image(
                upload, target_dir=str(tmp_path), file_url_base="/storage/test",
                name_prefix="synthetic", max_bytes=4096, prebuild_thumbnails=True,
            ))
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "the upload never reached the blocking section"
            # The client disconnects: cancel the request task itself, exactly
            # as the server does, while the worker thread is mid-conversion.
            task.cancel()
            Timer(0.2, release.set).start()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            await upload.close()

    asyncio.run(run())

    # The worker thread finished the write after the cancel, so the file really
    # was created and the cleanup really did remove it.
    assert written, "the worker thread never wrote a file, so nothing was cleaned up"
    assert _stored_files(tmp_path) == set(), "an orphaned upload file survived the cancel"


# --- replaced logo cleanup --------------------------------------------------


def test_replaced_logo_and_its_thumbnails_are_removed(tmp_path):
    stored = asyncio.run(image_storage.store_uploaded_image(
        _upload(), target_dir=str(tmp_path), file_url_base="/storage/model-files",
        name_prefix="company_logo", max_bytes=4096, prebuild_thumbnails=True,
    ))
    logo = tmp_path / stored.file_name
    assert logo.is_file()
    assert len(list((tmp_path / "_thumbs").glob(f"*{stored.file_name}.webp"))) == 2

    assert image_storage.discard_replaced_managed_image(stored.file_url, storage_root=tmp_path) is True

    assert not logo.exists()
    assert list((tmp_path / "_thumbs").glob("*.webp")) == []


def test_replaced_logo_cleanup_refuses_anything_it_did_not_store(tmp_path):
    stored = asyncio.run(image_storage.store_uploaded_image(
        _upload(), target_dir=str(tmp_path), file_url_base="/storage/model-files",
        name_prefix="company_logo", max_bytes=4096, prebuild_thumbnails=True,
    ))
    logo = tmp_path / stored.file_name

    # Not a managed storage URL, and a foreign host.
    assert image_storage.discard_replaced_managed_image(None, storage_root=tmp_path) is False
    assert image_storage.discard_replaced_managed_image("", storage_root=tmp_path) is False
    assert image_storage.discard_replaced_managed_image(
        f"https://cdn.example.com/{stored.file_name}", storage_root=tmp_path,
    ) is False
    # A name this service never mints.
    assert image_storage.discard_replaced_managed_image(
        "/storage/model-files/uploaded-by-hand.webp", storage_root=tmp_path,
    ) is False
    # A managed-looking name in a directory this service does not own.
    assert image_storage.discard_replaced_managed_image(
        stored.file_url, storage_root=tmp_path / "elsewhere",
    ) is False

    assert logo.is_file()


# --- PostgreSQL: worker-owned sessions, scope recheck, cancellation ----------


def test_postgres_coverage_skips_loudly_without_the_url(monkeypatch):
    monkeypatch.delenv("STABILIZATION_POSTGRES_URL", raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        _require_postgres_url()
    assert "STABILIZATION_POSTGRES_URL" in str(skipped.value)


def _audit_count(sessions) -> int:
    with sessions() as db:
        return db.query(AuditLog).count()


def test_model_image_upload_commits_its_row_and_audit(upload_postgres, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id = _seed_model(upload_postgres)
    upload = _upload()
    audits_before = _audit_count(upload_postgres)

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)
        result = asyncio.run(catalog_routes.upload_image(
            model_id, request_db, file=upload, image_type="model",
            current=current, catalog_scope="standard",
        ))

    assert result["file_url"].startswith("/storage/model-files/")
    assert (tmp_path / Path(result["file_url"]).name).is_file()
    with upload_postgres() as db:
        image = db.get(ModelImage, result["id"])
        assert image.model_id == model_id
        assert image.is_primary is True
        assert image.content_type == "image/webp"
        audit = db.query(AuditLog).filter(
            AuditLog.action == "create",
            AuditLog.entity_type == "ModelImage",
            AuditLog.entity_id == image.id,
        ).one()
        assert audit.entry_hash, "the audit chain was not finalized in the worker transaction"
    assert _audit_count(upload_postgres) == audits_before + 1


def test_model_image_upload_cancel_rolls_back_the_row_and_removes_the_file(
    upload_postgres, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id = _seed_model(upload_postgres)
    real_convert = image_storage.convert_image_to_webp
    real_write = image_storage._atomic_write
    written: list[str] = []
    entered = Event()
    release = Event()

    def gated_convert(content):
        entered.set()
        release.wait(5)
        return real_convert(content)

    def tracked_write(path, data):
        written.append(path.name)
        return real_write(path, data)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", gated_convert)
    monkeypatch.setattr(image_storage, "_atomic_write", tracked_write)
    upload = _upload()
    audits_before = _audit_count(upload_postgres)

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)

        async def run():
            task = asyncio.create_task(catalog_routes.upload_image(
                model_id, request_db, file=upload, image_type="material",
                current=current, catalog_scope="standard",
            ))
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "the upload never reached the blocking section"
            task.cancel()
            Timer(0.2, release.set).start()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())

    with upload_postgres() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
    assert _audit_count(upload_postgres) == audits_before
    assert written, "the worker thread never stored a file, so cleanup proved nothing"
    assert _stored_files(tmp_path) == set(), "an orphaned upload file survived the cancel"


def test_model_image_upload_keeps_the_file_when_the_transaction_committed(
    upload_postgres, tmp_path, monkeypatch
):
    """Cancellation must never delete a file whose row is already committed."""
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id = _seed_model(upload_postgres)
    real_create = catalog_routes._create_uploaded_model_image
    entered = Event()
    release = Event()

    def slow_create(db, **kwargs):
        entered.set()
        release.wait(5)
        return real_create(db, **kwargs)

    monkeypatch.setattr(catalog_routes, "_create_uploaded_model_image", slow_create)
    upload = _upload()

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)

        async def run():
            task = asyncio.create_task(catalog_routes.upload_image(
                model_id, request_db, file=upload, image_type="material",
                current=current, catalog_scope="standard",
            ))
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "the write never reached the worker session"
            task.cancel()
            Timer(0.2, release.set).start()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())

    with upload_postgres() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 1
    assert len(list(tmp_path.glob("*.webp"))) == 1


def test_model_image_upload_rejects_a_model_outside_the_requested_scope(
    upload_postgres, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    usluga_model_id, user_id = _seed_model(upload_postgres, scope="usluga")
    upload = _upload()

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(HTTPException) as refused:
            asyncio.run(catalog_routes.upload_image(
                usluga_model_id, request_db, file=upload, image_type="model",
                current=current, catalog_scope="standard",
            ))

    assert refused.value.status_code == 404
    with upload_postgres() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == usluga_model_id).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_model_image_scope_is_rechecked_where_the_worker_writes(upload_postgres, tmp_path, monkeypatch):
    """A model that leaves the scope mid-upload must still be refused.

    The pre-flight check runs before the file is stored; the write runs later
    in a worker-owned session. This is the only place that proves the scope
    decision survived the offload.
    """
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id = _seed_model(upload_postgres)
    real_store = image_storage.store_uploaded_image

    async def store_then_move_scope(*args, **kwargs):
        stored = await real_store(*args, **kwargs)
        with upload_postgres.begin() as db:
            db.execute(
                text("UPDATE models SET catalog_scope = 'usluga' WHERE id = :mid"),
                {"mid": model_id},
            )
        return stored

    monkeypatch.setattr(image_storage, "store_uploaded_image", store_then_move_scope)
    upload = _upload()
    audits_before = _audit_count(upload_postgres)

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(HTTPException) as refused:
            asyncio.run(catalog_routes.upload_image(
                model_id, request_db, file=upload, image_type="model",
                current=current, catalog_scope="standard",
            ))

    assert refused.value.status_code == 404
    with upload_postgres() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
    assert _audit_count(upload_postgres) == audits_before
    # The stored file was discarded rather than left orphaned on disk.
    assert list(tmp_path.rglob("*.webp")) == []


def test_hr_document_upload_rechecks_the_employee_factory_where_it_writes(
    upload_postgres, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    employee_id, user_id = _seed_employee(upload_postgres)
    real_write = hr_routes._write_new_hr_document

    def write_then_move_employee(target, content):
        real_write(target, content)
        with upload_postgres.begin() as db:
            db.execute(
                text("UPDATE employees SET factory_code = 'ECO' WHERE id = :eid"),
                {"eid": employee_id},
            )

    monkeypatch.setattr(hr_routes, "_write_new_hr_document", write_then_move_employee)
    upload = _document_upload()
    audits_before = _audit_count(upload_postgres)

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(HTTPException) as refused:
            asyncio.run(hr_routes.upload_document(
                request_db, current=current, employee_id=employee_id,
                category="employment_contract", title="Contract",
                expires_on=None, file=upload,
            ))

    assert refused.value.status_code == 404
    with upload_postgres() as db:
        assert db.query(HrEmployeeDocument).filter(
            HrEmployeeDocument.employee_id == employee_id,
        ).count() == 0
    assert _audit_count(upload_postgres) == audits_before
    assert list(tmp_path.iterdir()) == []


def test_hr_document_upload_commits_its_row(upload_postgres, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    employee_id, user_id = _seed_employee(upload_postgres)
    upload = _document_upload()

    with upload_postgres() as request_db:
        current = request_db.get(User, user_id)
        document = asyncio.run(hr_routes.upload_document(
            request_db, current=current, employee_id=employee_id,
            category="employment_contract", title="Contract",
            expires_on=None, file=upload,
        ))

    assert document["employee_id"] == employee_id
    assert document["category"] == "employment_contract"
    with upload_postgres() as db:
        row = db.get(HrEmployeeDocument, document["id"])
        assert row.factory_code == "MIL"
        assert row.uploaded_by == user_id
        assert (tmp_path / row.stored_name).is_file()
        assert db.query(AuditLog).filter(
            AuditLog.action == "create",
            AuditLog.entity_type == "HrEmployeeDocument",
            AuditLog.entity_id == row.id,
        ).one().entry_hash
