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
from dataclasses import dataclass

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, make_url

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


def _require_owned(target: OwnedTarget) -> tuple[ApprovedInstance, str]:
    try:
        instance, name = _owned_targets[target]
    except (KeyError, TypeError) as error:
        raise ApprovedInstanceUnavailable("target is not an active owned database") from error
    if target in _pending_targets:
        raise ApprovedInstanceUnavailable("target creation outcome is uncertain; inspect the recorded name")
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


def create_target_database(instance: ApprovedInstance) -> OwnedTarget:
    _validate_instance(instance)
    name = target_database_name(instance)
    sql = create_database_sql(name)
    # Record before any mutation; a statement whose outcome is unknown must not
    # authorize dropping a potentially pre-existing database with this name.
    target = OwnedTarget()
    _owned_targets[target] = (instance, name)
    _pending_targets.add(target)
    engine = None
    attempted = False
    created = False
    errors: list[BaseException] = []
    try:
        engine = create_engine(instance.admin_url, isolation_level="AUTOCOMMIT",
                               connect_args={"connect_timeout": 5}, future=True)
        with engine.connect() as conn:
            try:
                preflight_connection(conn, instance, "postgres")
                attempted = True
                conn.exec_driver_sql(sql)
                created = True
                _pending_targets.remove(target)
            except BaseException as error:
                errors.append(error)
    except BaseException as error:
        errors.append(error)
    if engine is not None:
        try:
            engine.dispose()
        except BaseException as error:
            errors.append(error)
    if errors:
        for error in errors:
            error.add_note(f"recorded target: {name}")
        if created:
            try:
                drop_target_database(target)
            except BaseException as error:
                errors.append(error)
        elif attempted:
            errors.append(ApprovedInstanceUnavailable(
                f"CREATE outcome uncertain for recorded target {name}; no automatic DROP authorized"))
        else:
            _pending_targets.discard(target)
            del _owned_targets[target]
        _raise_failures(f"owned target {name} setup and cleanup failures", errors)
    return target


def finalize_target(target: OwnedTarget, engine=None) -> None:
    """Dispose and drop even if either fails, preserving an active setup error."""
    active = sys.exception()
    errors: list[BaseException] = []
    if engine is not None:
        try:
            engine.dispose()
        except BaseException as error:
            errors.append(error)
    try:
        drop_target_database(target)
    except BaseException as error:
        errors.append(error)
    if errors:
        if active is not None:
            errors.insert(0, active)
        _raise_failures("target setup/teardown failures", errors)


def target_engine(target: OwnedTarget, *, options: str | None = None):
    """Build an engine which checks every checked-out connection before use."""
    instance, name = _require_owned(target)
    args = {"connect_timeout": 5}
    if options:
        args["options"] = options
    engine = create_engine(instance.admin_url.set(database=name),
                           connect_args=args, future=True)

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
    instance, name = _require_owned(target)
    sql = drop_database_sql(name)
    engine = None
    dropped = False
    errors: list[BaseException] = []
    try:
        engine = create_engine(instance.admin_url, isolation_level="AUTOCOMMIT",
                               connect_args={"connect_timeout": 5}, future=True)
        with engine.connect() as conn:
            try:
                preflight_connection(conn, instance, "postgres")
                conn.exec_driver_sql(sql)
                dropped = True
                del _owned_targets[target]
            except BaseException as error:
                errors.append(error)
    except BaseException as error:
        errors.append(error)
    if engine is not None:
        try:
            engine.dispose()
        except BaseException as error:
            errors.append(error)
    if errors and not dropped:
        errors.append(ApprovedInstanceUnavailable(f"cleanup incomplete for recorded target {name}"))
    _raise_failures(f"owned target {name} cleanup failures", errors)
