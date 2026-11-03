"""The approved PostgreSQL instance boundary for the real-PostgreSQL fixtures.

Reusable repository tests must not carry a machine-specific database URL. They
read the explicitly approved test configuration from the environment, verify
that the live server really is that approved instance, create exactly one
recorded target database, and drop exactly that database again.

Nothing here widens the boundary: no wildcard cleanup, no prefix scan, no
terminating of other connections and no `FORCE`. A configuration that is absent
or that does not match the live server fails closed, so a fixture never runs
against an unapproved server.
"""

from __future__ import annotations

import json
import ipaddress
import re
import os
import secrets
import sys
from dataclasses import dataclass, field
from enum import Enum
from threading import Event, Thread, current_thread, enumerate as live_threads
from time import monotonic, sleep
from typing import Literal, NoReturn

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine, URL, make_url

CONFIG_ENV = "MILANA_TEST_PG_INSTANCE"
REQUIRE_ENV = "MILANA_REQUIRE_TEST_PG"

_IDENTITY_SQL = """
SELECT host(inet_server_addr()) AS host,
       inet_server_port() AS port,
       current_setting('server_version') AS server_version,
       (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier,
       current_setting('data_directory') AS data_directory,
       current_database() AS database
"""

_REQUIRED_KEYS = (
    "admin_dsn",
    "host",
    "port",
    "server_version",
    "system_identifier",
    "data_directory",
    "target_prefix",
)


class ApprovedInstanceUnavailable(RuntimeError):
    """The approved test instance is not configured, or does not match."""


@dataclass(frozen=True)
class ApprovedInstance:
    """The approved test instance and the target-namespace it may create in."""

    admin_dsn: str
    host: str
    port: int
    server_version: str
    system_identifier: str
    data_directory: str
    target_prefix: str

    @property
    def admin_url(self) -> URL:
        return make_url(self.admin_dsn)


def load_approved_instance() -> ApprovedInstance:
    """Read the approved configuration, or fail closed."""
    raw = os.environ.get(CONFIG_ENV)
    if not raw:
        raise ApprovedInstanceUnavailable(
            f"{CONFIG_ENV} is not set; the real-PostgreSQL fixtures run only against the "
            "explicitly approved test instance"
        )
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} is not valid JSON") from error
    if not isinstance(data, dict):
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} must be a JSON object")
    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} is missing: {', '.join(sorted(missing))}")
    try:
        instance = ApprovedInstance(
            admin_dsn=str(data["admin_dsn"]), host=str(data["host"]),
            port=int(data["port"]), server_version=str(data["server_version"]),
            system_identifier=str(data["system_identifier"]),
            data_directory=str(data["data_directory"]), target_prefix=str(data["target_prefix"]),
        )
        _validate_instance(instance)
    except (ValueError, TypeError, KeyError) as error:
        raise ApprovedInstanceUnavailable("invalid approved PostgreSQL configuration") from error
    return instance



def _validate_instance(instance: ApprovedInstance) -> None:
    try:
        url = instance.admin_url
        host = ipaddress.ip_address(instance.host)
        if (not host.is_loopback or url.drivername != "postgresql+psycopg2"
                or not url.host or ipaddress.ip_address(url.host) != host
                or url.port != instance.port or not 1 <= instance.port <= 65535
                or url.database != "postgres" or url.query
                or not instance.server_version or not instance.system_identifier.isdecimal()
                or not instance.data_directory):
            raise ValueError("invalid endpoint or identity")
        if not re.fullmatch(r"[a-z][a-z0-9_]*_", instance.target_prefix):
            raise ValueError("invalid target namespace")
        if len(instance.target_prefix) + 12 > 63:
            raise ValueError("target namespace is too long")
    except (ValueError, TypeError, KeyError) as error:
        raise ApprovedInstanceUnavailable("invalid approved PostgreSQL configuration") from error

def identity_of(row) -> dict:
    """The identity fields of a live server row."""
    return {
        "host": str(row.host),
        "port": int(row.port),
        "server_version": str(row.server_version),
        "system_identifier": str(row.system_identifier),
        "data_directory": str(row.data_directory),
    }


def compare_identity(expected: ApprovedInstance, actual: dict) -> None:
    """Fail closed unless the live server is exactly the approved instance."""
    wanted = {
        "host": expected.host,
        "port": expected.port,
        "server_version": expected.server_version,
        "system_identifier": expected.system_identifier,
        "data_directory": expected.data_directory,
    }
    mismatched = sorted(key for key, value in wanted.items() if actual.get(key) != value)
    if mismatched:
        raise ApprovedInstanceUnavailable(
            "the live PostgreSQL server is not the approved test instance: "
            + ", ".join(f"{key}={actual.get(key)!r} != {wanted[key]!r}" for key in mismatched)
        )


def preflight_connection(connection, instance: ApprovedInstance, expected_database: str) -> dict:
    """Verify the *actual* connection immediately before it is used for writes."""
    _validate_instance(instance)
    row = connection.execute(text(_IDENTITY_SQL)).one()
    actual = identity_of(row)
    compare_identity(instance, actual)
    if row.database != expected_database:
        raise ApprovedInstanceUnavailable("connection is attached to an unexpected database")
    return actual


def verify_approved_instance(instance: ApprovedInstance) -> dict:
    _validate_instance(instance)
    engine = None
    actual = None
    errors: list[BaseException] = []
    try:
        engine = create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
        with engine.connect() as conn:
            try:
                actual = preflight_connection(conn, instance, "postgres")
            except BaseException as error:
                errors.append(error)
    except BaseException as error:
        errors.append(error)
    if engine is not None:
        try:
            engine.dispose()
        except BaseException as error:
            errors.append(error)
    _raise_failures("approved instance preflight failures", errors)
    return actual


def target_database_name(instance: ApprovedInstance) -> str:
    return f"{instance.target_prefix}{secrets.token_hex(6)}"


def _validated_name(name: str) -> str:
    if not isinstance(name, str) or len(name) > 63 or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ApprovedInstanceUnavailable("invalid target database identifier")
    return name


def create_database_sql(name: str) -> str:
    return f'CREATE DATABASE "{_validated_name(name)}"'


def drop_database_sql(name: str) -> str:
    return f'DROP DATABASE "{_validated_name(name)}"'


class OwnedTarget:
    """Opaque handle; ownership is recorded separately from the caller's handle."""
    __slots__ = ("__weakref__",)


_owned_targets: dict[OwnedTarget, tuple[ApprovedInstance, str]] = {}
_pending_targets: set[OwnedTarget] = set()


class _OperationState(Enum):
    NOT_ISSUED = "not_issued"
    ISSUED_UNKNOWN = "issued_unknown"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class _Lifecycle:
    target: OwnedTarget
    instance: ApprovedInstance
    name: str
    owner_thread: Thread
    baseline_threads: frozenset[Thread]
    create: _OperationState = _OperationState.NOT_ISSUED
    drop: _OperationState = _OperationState.NOT_ISSUED
    admin_close: _OperationState = _OperationState.NOT_ISSUED
    admin_dispose: _OperationState = _OperationState.NOT_ISSUED
    target_dispose: _OperationState = _OperationState.NOT_ISSUED
    held: bool = False
    admin_engine: Engine | None = None
    connection_context: Connection | None = None
    connection: Connection | None = None
    target_engine: Engine | None = None
    fixture_sessions: object | None = None
    resources: list[object] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)


_lifecycles: dict[OwnedTarget, _Lifecycle] = {}
_ADMIN_ARGS = {"connect_timeout": 5, "options": "-c statement_timeout=10000 -c lock_timeout=3000"}
_DRAIN_SQL = """
SELECT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
           OR pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') AS stats_visible,
       EXISTS (SELECT 1 FROM pg_database WHERE datname=:database_name) AS target_exists,
       (SELECT count(*) FROM pg_stat_activity WHERE datname=:database_name) AS clients,
       (SELECT count(*) FROM pg_prepared_xacts WHERE database=:database_name) AS prepared,
       (SELECT count(*) FROM pg_locks
          WHERE database=(SELECT oid FROM pg_database WHERE datname=:database_name)) AS locks
"""


def _park(operation: str, retained: tuple[object, ...], errors: list[BaseException]) -> NoReturn:
    """No environment toggle or cleanup grant; fake-only tests may observe this seam."""
    try:
        print(json.dumps({"event": "OWNED_PG_LIFECYCLE_HOLD", "operation": operation}), flush=True)
    except BaseException as error:
        # Logging must never turn retention into an unwind/cleanup grant.
        errors.append(error)
    wake = None
    while True:
        try:
            if wake is None:
                wake = Event()
            wake.wait()
        except BaseException as error:
            if len(errors) < 16:
                errors.append(error)
            # Keep the exact original objects in this live frame. Even failure
            # constructing the local wait primitive cannot unwind this owner.
            assert retained
            try:
                sleep(0.05)
            except BaseException as pause_error:
                if len(errors) < 16:
                    errors.append(pause_error)


def _retain(owner: _Lifecycle, operation: str) -> NoReturn:
    owner.held = True
    _park(operation, (owner,), owner.errors)
    raise ApprovedInstanceUnavailable("HOLD observer unexpectedly returned")


def _lifecycle(target: OwnedTarget) -> _Lifecycle:
    try:
        owner = _lifecycles[target]
    except (KeyError, TypeError) as error:
        raise ApprovedInstanceUnavailable("original target lifecycle is unavailable") from error
    if owner.held:
        _retain(owner, "REUSE_BLOCKED")
    return owner


def _assert_threads_drained(owner: _Lifecycle) -> None:
    if current_thread() is not owner.owner_thread:
        raise ApprovedInstanceUnavailable("target finalization changed its original owning thread")
    if any(thread not in owner.baseline_threads for thread in live_threads()):
        raise ApprovedInstanceUnavailable("target workers are not proven closed")


def _native_drain(connection: Connection, owner: _Lifecycle) -> None:
    deadline = monotonic() + 5
    while True:
        _assert_threads_drained(owner)
        row = connection.execute(text(_DRAIN_SQL), {"database_name": owner.name}).one()
        if row.stats_visible is not True or row.target_exists is not True:
            raise ApprovedInstanceUnavailable("target drain visibility or existence is unproven")
        counts = (row.clients, row.prepared, row.locks)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ApprovedInstanceUnavailable("target drain census is invalid")
        if counts == (0, 0, 0):
            return
        if monotonic() >= deadline:
            raise ApprovedInstanceUnavailable("target clients, prepared transactions or locks remain")
        sleep(0.05)


def retain_fixture_uncertainty(
    target: OwnedTarget, engine, sessions, error: BaseException,
    *, prior_error: BaseException | None = None,
) -> NoReturn:
    """Retain setup/name/unbind failures before a yield fixture can unwind."""
    errors = [prior_error] if prior_error is not None and prior_error is not error else []
    errors.append(error)
    try:
        owner = _lifecycles.get(target)
    except TypeError:
        owner = None
    if owner is None:
        _park("FIXTURE_OWNER_UNAVAILABLE", (target, engine, sessions), errors)
        raise ApprovedInstanceUnavailable("HOLD observer unexpectedly returned")
    # Preserve the originally constructed engine even if assignment in the
    # fixture did not complete; retain any supplied differing object separately.
    owner.resources.extend(value for value in (engine, sessions) if value is not None)
    if owner.target_engine is None:
        owner.target_engine = engine
    owner.fixture_sessions = sessions
    owner.errors.extend(errors)
    _retain(owner, "FIXTURE")


def _require_owned(target: OwnedTarget) -> tuple[ApprovedInstance, str]:
    try:
        owner = _lifecycles.get(target)
        if owner is not None and owner.held:
            raise ApprovedInstanceUnavailable("target lifecycle is retained; reuse and cleanup are blocked")
        instance, name = _owned_targets[target]
    except (KeyError, TypeError) as error:
        raise ApprovedInstanceUnavailable("target is not an active owned database") from error
    if target in _pending_targets:
        raise ApprovedInstanceUnavailable("target creation outcome is uncertain; inspect the recorded name")
    if owner is None or owner.target is not target or owner.instance is not instance or owner.name != name:
        raise ApprovedInstanceUnavailable("target no longer matches its original lifecycle")
    _validate_instance(instance)
    if not re.fullmatch(re.escape(instance.target_prefix) + r"[0-9a-f]{12}", name):
        raise ApprovedInstanceUnavailable("target does not match its approved namespace")
    _validated_name(name)
    return instance, name


def owned_target_name(target: OwnedTarget) -> str:
    return _require_owned(target)[1]


def _raise_failures(message: str, errors: list[BaseException]) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(message, errors)


def require_or_skip(error: ApprovedInstanceUnavailable) -> None:
    """Missing configuration may skip locally; required CI must fail."""
    import pytest
    if os.environ.get(REQUIRE_ENV) == "1" or os.environ.get(CONFIG_ENV):
        pytest.fail(f"required PostgreSQL gate BLOCKED: {error}", pytrace=False)
    pytest.skip(f"required PostgreSQL gate BLOCKED: {error}")


def _admin_ddl(owner: _Lifecycle, operation: Literal["create", "drop"]) -> None:
    """Run one owned statement; uncertainty retains this exact live stack."""
    creating = operation == "create"
    try:
        engine = create_engine(owner.instance.admin_url, isolation_level="AUTOCOMMIT",
                               connect_args=dict(_ADMIN_ARGS), future=True)
    except BaseException as error:
        owner.errors.append(error)
        if not creating:
            _retain(owner, "DROP_ADMIN_ENGINE")
        # No engine/connection exists and CREATE has not been issued.
        _pending_targets.discard(owner.target)
        del _owned_targets[owner.target]
        del _lifecycles[owner.target]
        raise
    owner.admin_engine = engine
    owner.resources.append(engine)
    owner.admin_close = _OperationState.NOT_ISSUED
    owner.admin_dispose = _OperationState.NOT_ISSUED
    try:
        context = engine.connect()
        owner.connection_context = context
        owner.resources.append(context)
        connection = context.__enter__()
        owner.connection = connection
        owner.resources.append(connection)
    except BaseException as error:
        owner.errors.append(error)
        _retain(owner, "ADMIN_CONNECT")

    preissue_error = None
    try:
        preflight_connection(connection, owner.instance, "postgres")
        if not creating:
            _native_drain(connection, owner)
    except BaseException as error:
        owner.errors.append(error)
        preissue_error = error

    if preissue_error is None:
        if creating:
            owner.create = _OperationState.ISSUED_UNKNOWN
        else:
            owner.drop = _OperationState.ISSUED_UNKNOWN
        try:
            connection.exec_driver_sql(
                create_database_sql(owner.name) if creating else drop_database_sql(owner.name)
            )
        except BaseException as error:
            owner.errors.append(error)
            # Do not unwind connection/context or guess rejection from SQLSTATE.
            _retain(owner, "CREATE_ISSUED" if creating else "DROP_ISSUED")
        if creating:
            owner.create = _OperationState.ACKNOWLEDGED
            _pending_targets.remove(owner.target)
        else:
            owner.drop = _OperationState.ACKNOWLEDGED
            # Acknowledged DROP retires live ownership exactly once, even if
            # subsequent admin closure cannot be confirmed.
            del _owned_targets[owner.target]
            try:
                absent = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                    {"name": owner.name},
                ).scalar_one()
                if absent is not False:
                    raise ApprovedInstanceUnavailable("acknowledged DROP readback did not prove absence")
            except BaseException as error:
                owner.errors.append(error)
                _retain(owner, "DROP_READBACK")

    owner.admin_close = _OperationState.ISSUED_UNKNOWN
    try:
        context.__exit__(
            type(preissue_error) if preissue_error is not None else None,
            preissue_error,
            preissue_error.__traceback__ if preissue_error is not None else None,
        )
    except BaseException as error:
        owner.errors.append(error)
        _retain(owner, "ADMIN_CLOSE")
    owner.admin_close = _OperationState.ACKNOWLEDGED
    owner.admin_dispose = _OperationState.ISSUED_UNKNOWN
    try:
        engine.dispose()
    except BaseException as error:
        owner.errors.append(error)
        _retain(owner, "ADMIN_DISPOSE")
    owner.admin_dispose = _OperationState.ACKNOWLEDGED

    if preissue_error is not None:
        if not creating:
            _retain(owner, "DROP_PREFLIGHT_OR_DRAIN")
        # Proven nonissued CREATE and acknowledged resource closure only.
        _pending_targets.discard(owner.target)
        del _owned_targets[owner.target]
        del _lifecycles[owner.target]
        raise preissue_error


def create_target_database(instance: ApprovedInstance) -> OwnedTarget:
    _validate_instance(instance)
    name = target_database_name(instance)
    create_database_sql(name)  # Validate before registering or opening resources.
    target = OwnedTarget()
    owner = _Lifecycle(target, instance, name, current_thread(), frozenset(live_threads()))
    _lifecycles[target] = owner
    _owned_targets[target] = (instance, name)
    _pending_targets.add(target)
    _admin_ddl(owner, "create")
    return target


def finalize_target(target: OwnedTarget, engine=None) -> None:
    """Drain before disposal and one DROP; retain original uncertainty in place."""
    active = sys.exception()
    owner = None
    try:
        owner = _lifecycles[target]
        _require_owned(target)
    except BaseException as error:
        errors = [active] if active is not None and active is not error else []
        errors.append(error)
        if owner is not None:
            owner.resources.append(engine)
            owner.errors.extend(errors)
            _retain(owner, "FINALIZE_IDENTITY")
        _park("FINALIZE_OWNER_UNAVAILABLE", (target, engine), errors)
        raise ApprovedInstanceUnavailable("HOLD observer unexpectedly returned")
    if active is not None and not any(error is active for error in owner.errors):
        owner.errors.append(active)
    try:
        _assert_threads_drained(owner)
        if engine is not owner.target_engine:
            raise ApprovedInstanceUnavailable("finalization did not supply the original target engine")
        if engine is not None:
            if owner.target_dispose is not _OperationState.NOT_ISSUED:
                raise ApprovedInstanceUnavailable("target disposal was already attempted")
            checkedout = engine.pool.checkedout()
            if type(checkedout) is not int or checkedout != 0:
                raise ApprovedInstanceUnavailable("target pool is not proven drained")
    except BaseException as error:
        owner.errors.append(error)
        _retain(owner, "TARGET_DRAIN")
    if engine is not None:
        owner.target_dispose = _OperationState.ISSUED_UNKNOWN
        try:
            engine.dispose()
        except BaseException as error:
            owner.errors.append(error)
            _retain(owner, "TARGET_DISPOSE")
        owner.target_dispose = _OperationState.ACKNOWLEDGED
    drop_target_database(target)
    # A known setup failure continues to propagate naturally from the fixture's
    # finally block. A failed test assertion is not thrown into a yield fixture.


def target_engine(target: OwnedTarget, *, options: str | None = None):
    """Build an engine which checks every checked-out connection before use."""
    instance, name = _require_owned(target)
    owner = _lifecycle(target)
    if owner.target_engine is not None:
        raise ApprovedInstanceUnavailable("target already has its original engine")
    args = {"connect_timeout": 5}
    if options:
        args["options"] = options
    engine = create_engine(instance.admin_url.set(database=name),
                           connect_args=args, future=True)
    owner.target_engine = engine
    owner.resources.append(engine)

    @event.listens_for(engine, "engine_connect")
    def _verify_target(conn):
        _require_owned(target)
        try:
            preflight_connection(conn, instance, name)
        finally:
            # SELECT identity starts SQLAlchemy's implicit transaction; leave the
            # connection ready for the caller's own begin/transaction lifecycle.
            conn.rollback()
    return engine


def drop_target_database(target: OwnedTarget) -> None:
    _require_owned(target)
    owner = _lifecycle(target)
    try:
        _assert_threads_drained(owner)
        if owner.target_engine is not None and owner.target_dispose is not _OperationState.ACKNOWLEDGED:
            raise ApprovedInstanceUnavailable("original target engine has not been drained and disposed")
        if owner.drop is not _OperationState.NOT_ISSUED:
            raise ApprovedInstanceUnavailable("DROP was already attempted")
    except BaseException as error:
        owner.errors.append(error)
        _retain(owner, "DROP_PREREQUISITES")
    _admin_ddl(owner, "drop")
    # No live database or unresolved resources remain. Remove the terminal record
    # only after both DDL and admin closure/disposal were acknowledged.
    del _lifecycles[target]
