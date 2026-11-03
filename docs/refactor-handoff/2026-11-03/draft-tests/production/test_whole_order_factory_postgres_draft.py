"""G009 pre-edit lock characterization draft; guarded, not a passing PG gate."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import threading
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import production
from app.core.deps import get_current_user, get_db
from app.models import audit_service, cutting_sewing_factory_service as service
from app.schemas import (
    AuditLog,
    Bundle,
    Department,
    Model,
    ProductionBatch,
    ProductionOrder,
    SewingAssignment,
    SewingFlow,
    SewingRecord,
    User,
    WorkOrder,
)
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable,
    create_target_database,
    finalize_target,
    load_approved_instance,
    owned_target_name,
    require_or_skip,
    target_engine,
    verify_approved_instance,
    preflight_connection,
)


def record(event_name, **fields):
    # Evidence failure never diverts ownership or cleanup. It makes this run fail.
    try:
        print(
            json.dumps({"event": event_name, **fields}, sort_keys=True, default=str),
            flush=True,
        )
    except BaseException:
        record.failed = True


record.failed = False


def hold(reason, target=None):
    record("BLOCKED_live_owner", reason=reason, returned_handle=target is not None)
    Event().wait()  # Keep this process and the actual guard registry/handle alive.


def owned_create(instance, create):
    owner = {}

    def retain(target, attempted, created, errors):
        # This assignment precedes telemetry, so a failed writer cannot lose it.
        owner["target"] = target
        record(
            "create_retained",
            attempted=attempted,
            created=created,
            error_types=[type(error).__name__ for error in errors],
        )
        hold("canonical CREATE or setup cleanup uncertain", target)
        raise RuntimeError("retention hold unexpectedly returned")

    try:
        return create(instance, on_setup_error=retain)
    except BaseException as error:
        record("create_exception", error_type=type(error).__name__)
        hold(
            "canonical CREATE or its internal cleanup has uncertain outcome",
            owner.get("target"),
        )
        raise


def owned_finalize(target, engine, finalize):
    try:
        finalize(target, engine)
    except BaseException as error:
        record("canonical_finalize_exception", error_type=type(error).__name__)
        hold("canonical finalization failed or uncertain", target)
        raise


class OwnerPolicy:
    """Fixture-local signal and one-stage release correlation; files are not authority."""

    def __init__(self, signal_api=signal, is_main=None):
        self.signals = signal_api
        self.is_main = is_main or (
            lambda: threading.current_thread() is threading.main_thread()
        )
        self.stop = False
        self.prior = {}
        self.active_sessions = set()
        self.active_workers = 0
        self.lock = threading.Lock()
        self.consumed = False

    def _stop(self, _signum, _frame):
        self.stop = True  # No I/O, cleanup or exceptions in the signal handler.

    def install(self):
        if not self.is_main():
            raise RuntimeError("signal policy requires main thread before CREATE")
        try:
            for sig in (self.signals.SIGINT, self.signals.SIGTERM):
                prior = self.signals.getsignal(sig)
                self.prior[sig] = prior
                self.signals.signal(sig, self._stop)
        except BaseException:
            self.restore()
            raise

    def restore(self):
        for sig, previous in reversed(list(self.prior.items())):
            self.signals.signal(sig, previous)
            del self.prior[sig]

    def gate(self):
        if self.stop or record.failed:
            raise RuntimeError("BLOCKED: stop requested or evidence unavailable")

    def admit_session(self, obj):
        with self.lock:
            self.gate()
            self.active_sessions.add(obj)

    def close_session(self, obj):
        with self.lock:
            self.active_sessions.discard(obj)

    def submit(self, pool, fn):
        with self.lock:
            self.gate()
            self.active_workers += 1

        def wrapped():
            try:
                return fn()
            finally:
                with self.lock:
                    self.active_workers -= 1

        try:
            return pool.submit(wrapped)
        except BaseException:
            with self.lock:
                self.active_workers -= 1
            raise

    def drained(self):
        with self.lock:
            return not self.active_sessions and self.active_workers == 0


def private_dir(path):
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise RuntimeError("control directory must be owned non-symlink 0700")


def write_control(directory, name, value):
    private_dir(directory)
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dfd,
        )
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(dfd)
    finally:
        os.close(dfd)


def read_control(directory, name):
    private_dir(directory)
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise RuntimeError("invalid control file")
            with os.fdopen(fd, encoding="utf8") as stream:
                fd = -1
                return json.load(stream)
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        os.close(dfd)


def release_matches(binding, proof, release):
    # Correlation only; independent Root inspection/release is external authority.
    raw = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return (
        not set(proof) ^ {"stage", "binding", "allowed_target_pids", "prepared"}
        and proof
        == {
            "stage": "finalize",
            "binding": binding,
            "allowed_target_pids": [],
            "prepared": 0,
        }
        and release
        == {
            "stage": "finalize",
            "binding": binding,
            "proof_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )


def await_finalizer_release(policy, target, instance, directory, binding, check_live):
    if not policy.drained():
        hold("owned sessions or workers have not drained", target)
        raise RuntimeError("hold returned")
    write_control(
        directory, "finalize-parked.json", {"stage": "finalize", "binding": binding}
    )
    while True:
        try:
            proof = read_control(directory, "finalize-proof.json")
            release = read_control(directory, "finalize-approved.json")
        except FileNotFoundError:
            sleep(1)
            continue
        except BaseException:
            hold("invalid finalizer control evidence", target)
            raise
        if policy.consumed or not release_matches(binding, proof, release):
            hold("finalizer release mismatch or replay", target)
            raise RuntimeError("hold returned")
        try:
            check_live(instance, binding)
        except BaseException:
            hold("finalizer live revalidation failed", target)
            raise
        policy.consumed = True
        return


def await_precreate_release(
    policy, instance, directory, binding, source_manifest, source_digest
):
    """Root must independently inspect and release; control files are correlation only."""
    policy.gate()
    engine = sa.create_engine(
        instance.admin_url,
        poolclass=sa.pool.NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as conn:
            preflight_connection(conn, instance, "postgres")
            pid = conn.execute(text("select pg_backend_pid()")).scalar_one()
            write_control(
                directory,
                "precreate-parked.json",
                {"stage": "pre_create", "binding": binding, "probe_pid": pid},
            )
            while True:
                policy.gate()
                try:
                    proof = read_control(directory, "precreate-proof.json")
                    release = read_control(directory, "precreate-approved.json")
                except FileNotFoundError:
                    sleep(1)
                    continue
                raw = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
                if (
                    set(proof)
                    != {
                        "stage",
                        "binding",
                        "probe_pid",
                        "allowed_client_pids",
                        "prepared",
                    }
                    or proof["stage"] != "pre_create"
                    or proof["binding"] != binding
                    or proof["probe_pid"] != pid
                    or proof["prepared"] != 0
                    or release
                    != {
                        "stage": "pre_create",
                        "binding": binding,
                        "proof_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ):
                    raise RuntimeError("precreate release mismatch")
                allowed = proof["allowed_client_pids"]
                if (
                    not isinstance(allowed, list)
                    or any(type(x) is not int or x <= 0 for x in allowed)
                    or len(set(allowed)) != len(allowed)
                ):
                    raise RuntimeError("invalid precreate client allowlist")
                preflight_connection(conn, instance, "postgres")
                clients = set(
                    conn.execute(
                        text(
                            "select pid from pg_stat_activity where backend_type='client backend' "
                        )
                    ).scalars()
                )
                targets = conn.execute(
                    text(
                        "select count(*) from pg_database where left(datname,length(:prefix))=:prefix"
                    ),
                    {"prefix": instance.target_prefix},
                ).scalar_one()
                prepared = conn.execute(
                    text("select count(*) from pg_prepared_xacts")
                ).scalar_one()
                check_source(source_manifest, source_digest)
                if (
                    clients != set(allowed)
                    or pid not in clients
                    or targets != 0
                    or prepared != 0
                ):
                    raise RuntimeError(
                        "precreate client/namespace/prepared state changed"
                    )
                policy.gate()
                return
    finally:
        engine.dispose()


def check_source(manifest_file, expected_digest):
    raw = Path(manifest_file).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise RuntimeError("source manifest mismatch")
    expected = json.loads(raw)
    source = Path(__file__).resolve().parents[3]
    actual = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(source).parts
    }
    if actual != expected:
        raise RuntimeError("source closed-world mismatch")


def check_live_finalizer(instance, binding):
    # Own admin-only observer; no target connections survive this check.
    engine = sa.create_engine(
        instance.admin_url,
        poolclass=sa.pool.NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as conn:
            preflight_connection(conn, instance, "postgres")
            targets = conn.execute(
                text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                {"name": binding["target"]},
            ).scalar_one()
            clients = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=:name AND backend_type='client backend'"
                ),
                {"name": binding["target"]},
            ).scalar_one()
            prepared = conn.execute(
                text("SELECT count(*) FROM pg_prepared_xacts WHERE database=:name"),
                {"name": binding["target"]},
            ).scalar_one()
            if (targets, clients, prepared) != (1, 0, 0):
                raise RuntimeError("target/client/prepared state changed")
    finally:
        engine.dispose()


class OwnedSession(Session):
    policy = None

    def __init__(self, *args, **kwargs):
        if kwargs.get("close_resets_only", False) is not False:
            raise ValueError("owned sessions must not be reusable after close")
        kwargs["close_resets_only"] = False
        super().__init__(*args, **kwargs)
        self.policy.admit_session(self)
        event.listen(
            self,
            "after_transaction_create",
            lambda _session, _transaction: self.policy.gate(),
        )

    def close(self):
        super().close()
        self.policy.close_session(self)

    def commit(self):
        if not self.in_transaction():
            self.policy.gate()
        try:
            return super().commit()
        except BaseException as error:
            record("commit_outcome_unknown", error_type=type(error).__name__)
            hold("commit outcome unknown; preserve owner and do not retry")
            raise


@pytest.fixture(scope="module")
def pg_sessions():
    policy = OwnerPolicy()
    policy.install()
    create_attempted = False
    try:
        if "MILANA_TEST_PG_INSTANCE" not in os.environ:
            require_or_skip(
                ApprovedInstanceUnavailable(
                    "explicit approved PostgreSQL instance not configured"
                )
            )
        instance = load_approved_instance()
        control = os.environ["G009_PG_CONTROL_DIR"]
        container_id = os.environ["G009_CONTAINER_ID"]
        source_digest = os.environ["G009_SOURCE_MANIFEST_SHA256"]
        source_manifest = os.environ["G009_SOURCE_MANIFEST"]
        if (
            not re.fullmatch(r"[0-9a-f]{64}", container_id)
            or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
            or os.getpid() != 1
        ):
            raise RuntimeError("owner/container/source identity is invalid")
        private_dir(control)
        if os.listdir(control):
            raise RuntimeError("control directory is not empty")
        check_source(source_manifest, source_digest)
        policy.gate()
        verify_approved_instance(instance)
        precreate_binding = {
            "target": None,
            "target_prefix": instance.target_prefix,
            "container_id": container_id,
            "owner_pid": os.getpid(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_manifest_sha256": source_digest,
            "system_identifier": instance.system_identifier,
            "host": instance.host,
            "port": instance.port,
            "server_version": instance.server_version,
            "data_directory": instance.data_directory,
            "nonce": secrets.token_hex(32),
        }
        await_precreate_release(
            policy, instance, control, precreate_binding, source_manifest, source_digest
        )
        policy.gate()
        create_attempted = True  # Set before calling canonical CREATE.
        target = owned_create(instance, create_target_database)
    except BaseException:
        if not create_attempted:
            policy.restore()
        raise
    engine = None
    try:
        name = owned_target_name(target)
        binding = {
            "target": name,
            "container_id": container_id,
            "owner_pid": os.getpid(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_manifest_sha256": source_digest,
            "system_identifier": instance.system_identifier,
            "host": instance.host,
            "port": instance.port,
            "server_version": instance.server_version,
            "data_directory": instance.data_directory,
            "nonce": secrets.token_hex(32),
        }
        policy.gate()
        record("created", target=name)
        if record.failed:
            raise RuntimeError("BLOCKED: evidence failure")
        engine = target_engine(
            target, options="-cstatement_timeout=30000 -clock_timeout=30000"
        )
        assert engine.dialect.name == "postgresql"
        with engine.connect() as conn:
            assert sa.inspect(conn).get_table_names(schema="public") == []
        from app.core.config import settings

        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "alembic")
        )
        head = ScriptDirectory.from_config(config).get_current_head()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                settings,
                "DATABASE_URL",
                engine.url.render_as_string(hide_password=False).replace("%", "%%"),
            )
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(config, "head")
        with engine.connect() as conn:
            prep = conn.dialect.identifier_preparer
            tables = sorted(sa.inspect(conn).get_table_names(schema="public"))
            counts = {
                table: conn.exec_driver_sql(
                    "select count(*) from " + prep.quote(table)
                ).scalar_one()
                for table in tables
            }
            flows = {
                tuple(row)
                for row in conn.execute(
                    text("select factory_code,name,code from sewing_flows")
                )
            }
            departments = {
                tuple(row)
                for row in conn.execute(text("select code,name from departments"))
            }
            warehouses = {
                tuple(row)
                for row in conn.execute(
                    text(
                        "select w.name,w.type,d.code from warehouses w join departments d on d.id=w.department_id"
                    )
                )
            }
            roles = [
                tuple(row)
                for row in conn.execute(text("select name,permissions from roles"))
            ]
            heads = (
                conn.execute(text("select version_num from alembic_version"))
                .scalars()
                .all()
            )
            expected_flows = {
                ("MIL", name, code)
                for name, code in [
                    ("Maxmudova Nargiza", "SEW-11"),
                    ("Muxlisa", "SEW-12"),
                    ("Sevara", "SEW-13"),
                ]
            } | {("ECO", f"{n}-Band", f"ECO-BAND-{n:02d}") for n in range(1, 21)}
            expected_departments = {
                ("ECO", "Eco Cotton Sewing Factory"),
                ("ECP", "Eco Cotton Packaging"),
                ("ECT", "Eco Cotton Cutting"),
            }
            expected_warehouses = {
                ("Eco Cotton Packaging Floor", "eco_cotton_packaging", "ECP"),
                ("Eco Cotton Cutting Floor", "eco_cotton_cutting", "ECT"),
            }
            expected_permissions = {
                "usluga.view",
                "usluga.manage",
                "usluga.handover",
                "planning.production",
                "usluga.cutting.approve",
            }
            expected_counts = {
                "alembic_version": 1,
                "sewing_flows": len(expected_flows),
                "departments": len(expected_departments),
                "warehouses": len(expected_warehouses),
                "roles": 1,
            }
            record(
                "migration_census",
                counts=counts,
                flows=sorted(flows),
                departments=sorted(departments),
                warehouses=sorted(warehouses),
                roles=roles,
                heads=heads,
                candidate_head=head,
            )
            assert heads == [head]
            assert {
                key: value for key, value in counts.items() if value
            } == expected_counts
            assert (
                flows == expected_flows
                and departments == expected_departments
                and warehouses == expected_warehouses
            )
            assert len(roles) == 1 and roles[0][0] == "Eco Cotton Usluga"
            assert (
                len(roles[0][1]) == len(expected_permissions)
                and set(roles[0][1]) == expected_permissions
            )
        if record.failed:
            raise RuntimeError("BLOCKED: migration evidence recording failed")
        policy.gate()
        OwnedSession.policy = policy
        yield sessionmaker(
            bind=engine, class_=OwnedSession, autoflush=False, expire_on_commit=False
        )
    finally:
        # Never infer cleanup authority from a drained test suite or files alone.
        if not policy.drained():
            hold("owned sessions or worker operations not drained", target)
        try:
            binding
        except UnboundLocalError:
            hold("target binding unavailable", target)
            raise
        try:
            if engine is not None:
                engine.dispose()  # close our idle pool before Root's inspection
            check_source(source_manifest, source_digest)

            def revalidate_for_finalizer(current_instance, current_binding):
                check_source(source_manifest, source_digest)
                check_live_finalizer(current_instance, current_binding)

            await_finalizer_release(
                policy, target, instance, control, binding, revalidate_for_finalizer
            )
        except BaseException:
            hold("finalizer preflight or release uncertain", target)
            raise
        owned_finalize(target, engine, finalize_target)
        record("canonical_finalization_returned")
        policy.restore()
        OwnedSession.policy = None
        if policy.stop or record.failed:
            raise RuntimeError("BLOCKED: stop requested or evidence recording failed")


@pytest.fixture(autouse=True)
def stop_admission(pg_sessions):
    policy = OwnedSession.policy
    policy.gate()
    yield
    policy.gate()


def order_fixture(sessions):
    marker = uuid4().hex
    with sessions() as db:
        departments = {x.code: x for x in db.query(Department).all()}
        for code in ("CUT", "MIL", "BST", "PKG", "BPK"):
            if code not in departments:
                departments[code] = Department(code=code, name=code)
                db.add(departments[code])
        actor = User(
            name="Synthetic G009",
            email=f"{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["admin.super", "cutting.records"],
        )
        model = Model(code=marker, name="Synthetic G009")
        db.add_all([actor, model])
        db.flush()
        order = ProductionOrder(
            production_no=marker,
            model_id=model.id,
            production_type="branded_stock",
            planned_quantity=1,
            status="cutting",
        )
        db.add(order)
        db.flush()
        works = {
            op: WorkOrder(
                production_order_id=order.id,
                operation=op,
                department_id=departments[code].id,
                status="in_progress",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            for op, code in [
                ("cutting", "CUT"),
                ("sewing", "CUT"),
                ("packaging", "PKG"),
            ]
        }
        db.add_all(works.values())
        db.flush()
        bundle = Bundle(
            bundle_no=marker,
            barcode=marker,
            production_order_id=order.id,
            model_id=model.id,
            color="Synthetic",
            size="S",
            quantity=1,
            status="created",
            sewing_factory_code="MIL",
            current_department_id=departments["CUT"].id,
            next_department_id=departments["MIL"].id,
        )
        db.add(bundle)
        db.flush()
        flow = db.query(SewingFlow).filter_by(factory_code="MIL").first()
        assignment = SewingAssignment(
            work_order_id=works["sewing"].id, sewing_flow_id=flow.id, quantity=1
        )
        db.add(assignment)
        db.flush()
        db.commit()
        return {
            "actor": actor.id,
            "order": order.id,
            "cutting": works["cutting"].id,
            "sewing": works["sewing"].id,
            "packaging": works["packaging"].id,
            "bundle": bundle.id,
            "assignment": assignment.id,
        }


@pytest.mark.parametrize(
    ("table", "field"),
    [
        ("work_orders", "sewing"),
        ("production_orders", "order"),
        ("work_orders", "packaging"),
        ("bundles", "bundle"),
        ("sewing_assignments", "assignment"),
    ],
)
def test_real_nowait_lock_returns_409_without_effect(pg_sessions, table, field):
    case = order_fixture(pg_sessions)
    before = state(pg_sessions, case)
    with pg_sessions() as holder, pg_sessions() as request:
        holder.execute(
            text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE"), {"id": case[field]}
        )
        try:
            with pytest.raises(HTTPException) as caught:
                production.update_cutting_sewing_factory(
                    case["cutting"],
                    production.CuttingSewingFactoryIn(sewing_factory_code="BST"),
                    request,
                    request.get(User, case["actor"]),
                )
            assert caught.value.status_code == 409
            assert (
                caught.value.detail
                == "Sewing is being updated. Reload this batch and try again."
            )
            cause = caught.value.__cause__
            assert isinstance(cause, OperationalError)
            assert (
                getattr(cause.orig, "sqlstate", None) == "55P03"
                or getattr(cause.orig, "pgcode", None) == "55P03"
            )
            request.rollback()
        finally:
            holder.rollback()
    assert state(pg_sessions, case) == before
    with pg_sessions() as retry:
        assert call_route(retry, case) == {
            "sewing_factory_code": "BST",
            "changed": True,
        }
    assert_chain(pg_sessions, case)


def state(sessions, case):
    with sessions() as db:
        works = (
            db.query(WorkOrder)
            .filter_by(production_order_id=case["order"])
            .order_by(WorkOrder.id)
            .all()
        )
        bundle = db.get(Bundle, case["bundle"])
        assignment = db.get(SewingAssignment, case["assignment"])
        audits = (
            db.query(AuditLog)
            .filter_by(
                entity_type="ProductionOrder",
                entity_id=case["order"],
                action="change_sewing_factory",
            )
            .order_by(AuditLog.id)
            .all()
        )
        return {
            "works": [
                (
                    w.id,
                    w.department_id,
                    w.sewing_flow_id,
                    w.status,
                    w.actual_output_qty,
                    w.passed_qty,
                    w.failed_qty,
                )
                for w in works
            ],
            "bundle": (
                bundle.id,
                bundle.sewing_factory_code,
                bundle.current_department_id,
                bundle.next_department_id,
                bundle.quantity,
                bundle.status,
            ),
            "assignment": (assignment.id, assignment.status, assignment.completed_qty),
            "audits": [
                (
                    a.id,
                    a.prev_hash,
                    a.entry_hash,
                    a.user_id,
                    a.action,
                    a.entity_type,
                    a.entity_id,
                    a.old_value_json,
                    a.new_value_json,
                )
                for a in audits
            ],
        }


def call_route(db, case, factory="BST", batch_ids=None):
    before_commit = []
    after_commit = []
    event.listen(db, "before_commit", lambda session: before_commit.append(True))
    event.listen(db, "after_commit", lambda session: after_commit.append(True))
    try:
        return production.update_cutting_sewing_factory(
            case["cutting"],
            production.CuttingSewingFactoryIn(
                sewing_factory_code=factory, production_batch_ids=batch_ids
            ),
            db,
            db.get(User, case["actor"]),
        )
    except BaseException as error:
        if before_commit and not after_commit:
            record("unknown_commit_outcome", error_type=type(error).__name__)
            hold("request reached commit but completion unknown; no automatic retry")
        raise


def assert_chain(sessions, case):
    with sessions() as db:
        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        previous = None
        for row in rows:
            assert row.prev_hash == previous
            assert row.entry_hash == audit_service._audit_entry_hash(
                prev_hash=row.prev_hash,
                user_id=row.user_id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                old_value=row.old_value_json,
                new_value=row.new_value_json,
            )
            previous = row.entry_hash
        assert (
            sum(
                row.entity_id == case["order"] and row.action == "change_sewing_factory"
                for row in rows
            )
            == 1
        )


def test_cutting_lock_timeout_is_unmapped_then_retry(pg_sessions):
    case = order_fixture(pg_sessions)
    before = state(pg_sessions, case)
    with pg_sessions() as holder:
        holder.execute(
            text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE"),
            {"id": case["cutting"]},
        )
        try:
            with pg_sessions() as request:
                request.execute(text("SET LOCAL lock_timeout='1000ms'"))
                with pytest.raises(OperationalError) as caught:
                    call_route(request, case)
                assert (
                    getattr(caught.value.orig, "pgcode", None) == "55P03"
                    or getattr(caught.value.orig, "sqlstate", None) == "55P03"
                )
                request.rollback()
            assert state(pg_sessions, case) == before
        finally:
            holder.rollback()
    with pg_sessions() as retry:
        assert call_route(retry, case) == {
            "sewing_factory_code": "BST",
            "changed": True,
        }
    assert_chain(pg_sessions, case)


def test_cutting_lock_wait_observed_then_released(pg_sessions):
    case = order_fixture(pg_sessions)
    ready = Queue()
    pool = ThreadPoolExecutor(max_workers=1)

    def worker():
        with pg_sessions() as request:
            request.execute(text("SET LOCAL lock_timeout='10s'"))
            ready.put(request.execute(text("select pg_backend_pid()")).scalar_one())
            return call_route(request, case)

    future = None
    try:
        with pg_sessions() as holder:
            holder.execute(
                text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE"),
                {"id": case["cutting"]},
            )
            try:
                future = OwnedSession.policy.submit(pool, worker)
                pid = ready.get(timeout=5)
                deadline = monotonic() + 5
                observed = False
                with pg_sessions() as observer:
                    while monotonic() < deadline:
                        row = observer.execute(
                            text(
                                "select wait_event_type, cardinality(pg_blocking_pids(:pid)) from pg_stat_activity where pid=:pid"
                            ),
                            {"pid": pid},
                        ).first()
                        if row and row[0] == "Lock" and row[1] > 0:
                            observed = True
                            break
                        observer.rollback()
                        sleep(0.05)
                assert observed, "cutting route lock wait not observed"
            finally:
                holder.rollback()
        if future is not None:
            try:
                result = future.result(timeout=12)
            except TimeoutError:
                hold(
                    "route waiter did not drain; original owner and in-flight session retained"
                )
                raise
            assert result == {"sewing_factory_code": "BST", "changed": True}
        assert_chain(pg_sessions, case)
    finally:
        if future is not None and not future.done():
            hold("worker still active during cleanup")
        pool.shutdown(wait=True)


def test_committed_sewing_output_blocks_after_real_row_contention(pg_sessions):
    case = order_fixture(pg_sessions)
    before = state(pg_sessions, case)
    with pg_sessions() as writer, pg_sessions() as request:
        writer.execute(
            text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE"),
            {"id": case["sewing"]},
        )
        try:
            with pytest.raises(HTTPException) as caught:
                call_route(request, case)
            assert caught.value.status_code == 409
            request.rollback()
            assert state(pg_sessions, case) == before
            writer.add(
                SewingRecord(
                    work_order_id=case["sewing"], input_qty=1, sewn_qty=1, passed_qty=1
                )
            )
            writer.commit()
        finally:
            writer.rollback()
    with pg_sessions() as retry:
        with pytest.raises(HTTPException) as caught:
            call_route(retry, case)
        assert (
            caught.value.status_code == 409 and "Sewing output" in caught.value.detail
        )
        retry.rollback()
    with pg_sessions() as db:
        assert (
            db.query(SewingRecord).filter_by(work_order_id=case["sewing"]).count() == 1
        )
    assert state(pg_sessions, case) == before


@pytest.mark.parametrize("fault", ["flush", "audit"])
def test_http_dependency_teardown_rollback_and_authorized_retry(
    pg_sessions, monkeypatch, fault
):
    case = order_fixture(pg_sessions)
    before = state(pg_sessions, case)
    app = FastAPI()
    app.include_router(production.router, prefix="/api")

    def request_session():
        with pg_sessions() as db:
            commit_started = []
            commit_done = []
            event.listen(db, "before_commit", lambda _: commit_started.append(True))
            event.listen(db, "after_commit", lambda _: commit_done.append(True))
            if fault == "flush":
                event.listen(
                    db,
                    "before_flush",
                    lambda *_: (_ for _ in ()).throw(
                        RuntimeError("synthetic before-flush")
                    ),
                )
            try:
                yield db
            except BaseException:
                if commit_started and not commit_done:
                    hold("HTTP commit outcome unknown; no retry")
                raise

    def actor():
        with pg_sessions() as db:
            user = db.get(User, case["actor"])
            _ = user.role, user.department
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = request_session
    app.dependency_overrides[get_current_user] = actor
    original = service.log_action

    def fail_after_actual_audit_queue(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.flush()
        raise RuntimeError("synthetic after audit queue and flush")

    with monkeypatch.context() as patch:
        if fault == "audit":
            patch.setattr(service, "log_action", fail_after_actual_audit_queue)
        with TestClient(app, raise_server_exceptions=True) as client:
            with pytest.raises(RuntimeError, match="synthetic"):
                client.patch(
                    f"/api/work-orders/{case['cutting']}/sewing-factory",
                    json={"sewing_factory_code": "BST"},
                )
    assert state(pg_sessions, case) == before

    def normal_session():
        with pg_sessions() as db:
            started = []
            done = []
            event.listen(db, "before_commit", lambda _: started.append(True))
            event.listen(db, "after_commit", lambda _: done.append(True))
            try:
                yield db
            except BaseException:
                if started and not done:
                    hold("HTTP retry commit outcome unknown; no further retry")
                raise

    app.dependency_overrides[get_db] = normal_session
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/work-orders/{case['cutting']}/sewing-factory",
            json={"sewing_factory_code": "BST"},
        )
    assert response.status_code == 200 and response.json() == {
        "sewing_factory_code": "BST",
        "changed": True,
    }
    assert_chain(pg_sessions, case)


def test_concurrent_same_factory_serializes_once(pg_sessions):
    case = order_fixture(pg_sessions)
    ready = Queue()
    start = Event()
    pool = ThreadPoolExecutor(max_workers=2)
    futures = []

    def worker():
        with pg_sessions() as db:
            db.execute(text("SET LOCAL lock_timeout='10s'"))
            ready.put(True)
            if not start.wait(5):
                raise RuntimeError("worker start timeout")
            return call_route(db, case)

    try:
        futures = [OwnedSession.policy.submit(pool, worker) for _ in range(2)]
        ready.get(timeout=5)
        ready.get(timeout=5)
        start.set()
        results = []
        for future in futures:
            try:
                results.append(future.result(timeout=15))
            except TimeoutError:
                hold("concurrent route request unknown; no retry or forced cleanup")
                raise
        assert sorted(r["changed"] for r in results) == [False, True]
        assert all(r["sewing_factory_code"] == "BST" for r in results)
        assert_chain(pg_sessions, case)
        with pg_sessions() as db:
            assert db.get(Bundle, case["bundle"]).sewing_factory_code == "BST"
            assert db.get(SewingAssignment, case["assignment"]).status == "cancelled"
    finally:
        start.set()
        if any(not f.done() for f in futures):
            hold("concurrent workers not drained")
        pool.shutdown(wait=True)


def test_selected_control_cannot_touch_sibling(pg_sessions):
    case = order_fixture(pg_sessions)
    marker = uuid4().hex
    with pg_sessions() as db:
        order = db.get(ProductionOrder, case["order"])
        bundle = db.get(Bundle, case["bundle"])
        order.planned_quantity = 2
        for key in ("cutting", "sewing", "packaging"):
            work = db.get(WorkOrder, case[key])
            assert work.actual_output_qty == work.passed_qty == work.failed_qty == 0
            work.planned_input_qty = work.planned_output_qty = 2
        batch_numbers = [f"{marker[:24]}-{i}" for i in (1, 2)]
        assert len(set(batch_numbers)) == 2
        assert all(
            len(number) <= ProductionBatch.__table__.c.batch_no.type.length
            for number in batch_numbers
        )
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=batch_numbers[i - 1],
                batch_index=i,
                planned_quantity=1,
            )
            for i in (1, 2)
        ]
        db.add_all(batches)
        db.flush()
        bundle.production_batch_id = batches[0].id
        db.get(SewingAssignment, case["assignment"]).production_batch_id = batches[0].id
        sibling = Bundle(
            bundle_no=marker,
            barcode=marker,
            production_order_id=order.id,
            production_batch_id=batches[1].id,
            model_id=order.model_id,
            color="Sibling",
            size="S",
            quantity=1,
            status="created",
            sewing_factory_code="MIL",
            current_department_id=bundle.current_department_id,
            next_department_id=bundle.next_department_id,
        )
        db.add(sibling)
        db.flush()
        selected = batches[0].id
        sibling_id = sibling.id
        assert bundle.production_batch_id == batches[0].id
        assert (
            db.get(SewingAssignment, case["assignment"]).production_batch_id
            == batches[0].id
        )
        assert sibling.production_batch_id == batches[1].id
        assert (
            order.planned_quantity
            == sum(batch.planned_quantity for batch in batches)
            == bundle.quantity + sibling.quantity
            == 2
        )
        sibling_before = (
            sibling.sewing_factory_code,
            sibling.current_department_id,
            sibling.next_department_id,
            sibling.quantity,
        )
        db.commit()
    with pg_sessions() as db:
        result = call_route(db, case, batch_ids=[selected])
        assert result == {
            "sewing_factory_code": "BST",
            "production_batch_ids": [selected],
            "changed": True,
        }
    with pg_sessions() as db:
        sibling = db.get(Bundle, sibling_id)
        assert (
            sibling.sewing_factory_code,
            sibling.current_department_id,
            sibling.next_department_id,
            sibling.quantity,
        ) == sibling_before
        assert db.get(Bundle, case["bundle"]).sewing_factory_code == "BST"
        assert (
            db.query(AuditLog)
            .filter_by(
                entity_type="ProductionOrder",
                entity_id=case["order"],
                action="change_nastil_factory",
            )
            .count()
            == 1
        )
